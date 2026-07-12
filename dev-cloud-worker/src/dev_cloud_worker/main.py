"""Environment worker: polls control plane and executes commands locally."""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Callable

import requests

from dev_cloud_worker.poller import COMMS_SYNC_RETRIES, CloudPoller
from dev_sdk.agent_run import (
    AgentRunError,
    run_do,
    run_implement,
    run_merge_conflict_resolution,
    run_plan_implement,
    run_question_mode,
)
from dev_sdk.bash_runner import BashStreamHooks, run_bash_stream
from dev_sdk.comms import comms_dir
from dev_sdk.merge_from_main import MergeFromMainError, MergeFromMainHooks, run_merge_from_main
from dev_sdk.task_manager import TaskCancelled, TaskManager
from dev_sdk.worker_sync import (
    OutboxEntry,
    StreamsState,
    append_progress,
    has_outbox,
    write_outbox,
    write_streams,
)

logger = logging.getLogger("dev_cloud_worker")
POLL_INTERVAL_SEC = float(os.environ.get("DEV_CLOUD_POLL_INTERVAL", "1"))
WORKER_REBOOT_MESSAGE = (
    "Worker rebooted — command cancelled; workspace may have uncommitted changes"
)
CONFIG_DIR = Path.home() / ".config" / "dev-cloud"
ENV_ID_FILE = CONFIG_DIR / "environment_id"
DISPLAY_NAME_FILE = CONFIG_DIR / "display_name"


def _control_plane_url() -> str:
    url = os.environ.get("CONTROL_PLANE_URL", "").rstrip("/")
    if not url:
        raise RuntimeError("CONTROL_PLANE_URL environment variable required")
    return url


def _tasks_root() -> Path:
    root = os.environ.get("DEV_TASKS_ROOT", str(Path.home() / "tasks"))
    return Path(root)


def _load_environment_id() -> str:
    if ENV_ID_FILE.is_file():
        return ENV_ID_FILE.read_text(encoding="utf-8").strip()
    env_id = str(uuid.uuid4())
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    ENV_ID_FILE.write_text(env_id, encoding="utf-8")
    return env_id


def _load_display_name() -> str | None:
    if DISPLAY_NAME_FILE.is_file():
        name = DISPLAY_NAME_FILE.read_text(encoding="utf-8").strip()
        return name or None
    return None


def _load_cursor_api_key() -> None:
    """Load CURSOR_API_KEY from Secrets Manager when not already set."""
    if os.environ.get("CURSOR_API_KEY"):
        return
    secret_id = os.environ.get("CURSOR_API_KEY_SECRET_NAME", "").strip()
    if not secret_id:
        logger.warning("CURSOR_API_KEY_SECRET_NAME not set; Cursor agent may fail without a key")
        return
    try:
        import boto3

        region = (
            os.environ.get("AWS_REGION")
            or os.environ.get("AWS_DEFAULT_REGION")
            or "us-east-1"
        )
        client = boto3.client("secretsmanager", region_name=region)
        resp = client.get_secret_value(SecretId=secret_id)
        secret_str = (resp.get("SecretString") or "").strip()
        if not secret_str:
            logger.warning("Cursor API key secret %s is empty", secret_id)
            return
        if secret_str.startswith("{"):
            data = json.loads(secret_str)
            for key in ("api_key", "CURSOR_API_KEY", "cursor_api_key"):
                if isinstance(data.get(key), str) and data[key].strip():
                    secret_str = data[key].strip()
                    break
        if secret_str in ("REPLACE_IN_CONSOLE", "PASTE_CURSOR_API_KEY_IN_CONSOLE"):
            logger.warning("Cursor API key secret still has placeholder value; set it in AWS Console")
            return
        os.environ["CURSOR_API_KEY"] = secret_str
        logger.info("Loaded CURSOR_API_KEY from Secrets Manager (%s)", secret_id)
    except Exception:
        logger.exception("Failed to load Cursor API key from %s", secret_id)


class WorkerClient:
    def __init__(self) -> None:
        self.base = _control_plane_url()
        self.env_id = _load_environment_id()
        self.session = requests.Session()
        self.session.headers["Content-Type"] = "application/json"

    def poll(self, *, claim_work: bool = True) -> dict:
        resp = self.session.post(
            f"{self.base}/worker/poll",
            json={
                "environment_id": self.env_id,
                "display_name": _load_display_name(),
                "claim_work": claim_work,
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("environment_id"):
            self.env_id = data["environment_id"]
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            ENV_ID_FILE.write_text(self.env_id, encoding="utf-8")
        assigned_name = data.get("display_name")
        if isinstance(assigned_name, str) and assigned_name.strip():
            current = _load_display_name()
            if assigned_name != current:
                CONFIG_DIR.mkdir(parents=True, exist_ok=True)
                DISPLAY_NAME_FILE.write_text(assigned_name, encoding="utf-8")
        return data

    def complete_command(self, task_name: str, *, error: str | None = None, result: dict | None = None) -> None:
        self.session.post(
            f"{self.base}/worker/tasks/{task_name}/command/complete",
            json={"error": error, "result": result or {}},
            timeout=30,
        ).raise_for_status()

    def progress(self, task_name: str, message: str) -> None:
        self.session.post(
            f"{self.base}/worker/tasks/{task_name}/command/progress",
            json={"message": message},
            timeout=10,
        )

    def sync_push(self, task_name: str, items: list[dict]) -> list[dict]:
        resp = self.session.post(
            f"{self.base}/worker/tasks/{task_name}/sync",
            json={"push": items},
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json().get("pull", [])

    def upload_log_chunk(
        self, task_name: str, filename: str, chunk: bytes, *, kind: str = "log"
    ) -> None:
        import base64

        self.session.post(
            f"{self.base}/worker/tasks/{task_name}/logs",
            json={
                "filename": filename,
                "kind": kind,
                "chunk_b64": base64.b64encode(chunk).decode("ascii"),
            },
            timeout=30,
        ).raise_for_status()

    def command_start(self, task_name: str) -> None:
        self.session.post(
            f"{self.base}/worker/tasks/{task_name}/command/start",
            timeout=10,
        ).raise_for_status()

    def report_sync_health(self, task_name: str, *, sync_health: str) -> None:
        self.session.post(
            f"{self.base}/worker/tasks/{task_name}/sync-health",
            json={"sync_health": sync_health},
            timeout=10,
        ).raise_for_status()

    def ack_deletion(self, task_name: str, filename: str) -> None:
        self.session.post(
            f"{self.base}/worker/deletions/ack",
            json={"task_name": task_name, "filename": filename},
            timeout=30,
        ).raise_for_status()

    def git_token(self, owner: str) -> str:
        resp = self.session.post(
            f"{self.base}/worker/git-token",
            json={"owner": owner},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["token"]


class CommandExecutor:
    """Runs commands locally; poller owns all cloud writes except git-token reads."""

    def __init__(self, tasks_root: Path) -> None:
        self.tasks_root = tasks_root
        self.manager = TaskManager(tasks_root)
        self._cancel_flags: dict[str, threading.Event] = {}
        self._cancel_lock = threading.Lock()
        self._running_tasks: set[str] = set()
        self._running_lock = threading.Lock()

    def try_start(self, task_name: str) -> bool:
        with self._running_lock:
            if task_name in self._running_tasks:
                return False
            self._running_tasks.add(task_name)
            return True

    def is_running(self, task_name: str) -> bool:
        with self._running_lock:
            return task_name in self._running_tasks

    def discard_running(self, task_name: str) -> None:
        with self._running_lock:
            self._running_tasks.discard(task_name)

    def reconcile_orphans(self, active_commands: list[dict]) -> None:
        for item in active_commands:
            task_name = item.get("task_name")
            if not task_name or self.is_running(task_name):
                continue
            task_dir = self.tasks_root / task_name
            if has_outbox(task_dir):
                continue
            command = item.get("command") or {}
            if command.get("cancel_requested"):
                error = "Cancelled"
            else:
                error = WORKER_REBOOT_MESSAGE
            write_outbox(task_dir, OutboxEntry(error=error, result={}))
            logger.info("Queued orphan outbox for %s: %s", task_name, error)

    def _cancel_for(self, task_name: str) -> threading.Event:
        with self._cancel_lock:
            flag = self._cancel_flags.get(task_name)
            if flag is None:
                flag = threading.Event()
                self._cancel_flags[task_name] = flag
            return flag

    def request_cancel(self, task_name: str) -> None:
        self._cancel_for(task_name).set()

    def execute(self, task_name: str, command: dict) -> None:
        cmd = command.get("command")
        payload = command.get("payload") or {}
        cancel_flag = self._cancel_for(task_name)
        cancel_flag.clear()
        task_dir = self.tasks_root / task_name

        if cmd == "cancel":
            cancel_flag.set()
            return

        error: str | None = None
        result: dict | None = None
        try:
            if cmd == "create-task":
                self._create_task(task_name, payload, cancel_flag)
            elif cmd == "archive":
                self._archive(task_name, payload)
            elif cmd == "unarchive":
                self._unarchive(task_name, payload)
            elif cmd == "copy-from-archive":
                self._copy_from_archive(task_name, payload)
            elif cmd in ("question", "plan-implement", "implement", "do"):
                self._run_agent(task_name, cmd, payload.get("prompt"), cancel_flag)
            elif cmd == "bash":
                self._run_bash(task_name, payload.get("prompt", ""), cancel_flag)
            elif cmd == "merge-from-main":
                self._run_merge_from_main(task_name, cancel_flag)
            else:
                raise RuntimeError(f"Unknown command: {cmd}")
            result = self._task_result(task_name)
        except TaskCancelled as e:
            logger.info("Command cancelled for %s: %s", task_name, e)
            if cmd == "create-task":
                if task_dir.is_dir():
                    shutil.rmtree(task_dir, ignore_errors=True)
            error = "Cancelled"
        except MergeFromMainError as e:
            logger.info("Merge-from-main validation failed for %s: %s", task_name, e)
            error = str(e)
        except Exception as e:
            logger.exception("Command failed for %s: %s", task_name, e)
            error = str(e)
        finally:
            cancel_flag.clear()
            with self._running_lock:
                self._running_tasks.discard(task_name)

        write_outbox(task_dir, OutboxEntry(error=error, result=result or {}))

    def _task_result(self, task_name: str) -> dict:
        task_dir = self.tasks_root / task_name
        out: dict = {}
        for child in task_dir.iterdir() if task_dir.is_dir() else []:
            if child.is_dir() and not child.name.startswith("."):
                try:
                    r = subprocess.run(
                        ["git", "remote", "get-url", "origin"],
                        cwd=child,
                        capture_output=True,
                        text=True,
                        check=True,
                    )
                    url = r.stdout.strip()
                    from dev_sdk.create_pr import _parse_owner_repo

                    owner, repo_name = _parse_owner_repo(url)
                    out["owner"] = owner
                    out["repo_name"] = repo_name
                    br = subprocess.run(
                        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                        cwd=child,
                        capture_output=True,
                        text=True,
                        check=True,
                    )
                    out["branch"] = br.stdout.strip()
                except Exception:
                    pass
                break
        return out

    def _create_task(
        self,
        task_name: str,
        payload: dict,
        cancel_flag: threading.Event,
    ) -> None:
        task_dir = self.tasks_root / task_name

        def on_progress(msg: str) -> None:
            append_progress(task_dir, msg)

        self.manager.start_task(
            payload.get("title", task_name),
            task_name,
            payload.get("comment"),
            payload.get("repo_url"),
            on_progress=on_progress,
            cancel_check=cancel_flag.is_set,
        )

    def _archive(self, task_name: str, payload: dict) -> None:
        self.manager.archive_task(task_name)

    def _unarchive(self, task_name: str, payload: dict) -> None:
        archived_name = payload["archived_name"]
        self.manager.unarchive_task(archived_name)

    def _copy_from_archive(self, task_name: str, payload: dict) -> None:
        archived_name = payload["archived_name"]
        self.manager.copy_task_from_archive(archived_name, task_name_override=task_name)

    def _stream_hooks(self, task_dir: Path) -> BashStreamHooks:
        def on_comms_path(path: Path) -> None:
            write_streams(task_dir, StreamsState(active_bash=path.name))

        return BashStreamHooks(on_comms_path=on_comms_path, on_output_appended=None)

    def _run_agent_with_log(
        self,
        task_dir: Path,
        cancel_flag: threading.Event,
        runner: Callable[[Path, Callable[[Path], None], threading.Event], None],
    ) -> None:
        def on_start(stream_log_path: Path) -> None:
            write_streams(task_dir, StreamsState(active_log=stream_log_path.name))

        runner(task_dir, on_start, cancel_flag)

    def _run_agent(
        self,
        task_name: str,
        command: str,
        prompt: str | None,
        cancel_flag: threading.Event,
    ) -> None:
        task_dir = self.tasks_root / task_name

        def runner(task_dir_arg: Path, on_start: Callable[[Path], None], flag: threading.Event) -> None:
            if command == "question":
                run_question_mode(task_dir_arg, on_start=on_start, cancel_event=flag)
            elif command == "plan-implement":
                run_plan_implement(task_dir_arg, on_start=on_start, cancel_event=flag)
            elif command == "implement":
                run_implement(task_dir_arg, on_start=on_start, cancel_event=flag)
            elif command == "do":
                if not prompt or not str(prompt).strip():
                    raise RuntimeError("Missing prompt for do command")
                run_do(task_dir_arg, str(prompt).strip(), on_start=on_start, cancel_event=flag)
            else:
                raise RuntimeError(f"Unknown agent command: {command}")

        try:
            self._run_agent_with_log(task_dir, cancel_flag, runner)
        except AgentRunError as e:
            raise RuntimeError(str(e)) from e

    def _run_bash(
        self,
        task_name: str,
        shell_command: str,
        cancel_flag: threading.Event,
    ) -> None:
        task_dir = self.tasks_root / task_name
        hooks = self._stream_hooks(task_dir)
        result = run_bash_stream(
            task_dir,
            shell_command,
            cwd=task_dir,
            cancel_event=cancel_flag,
            hooks=hooks,
        )
        if result.cancelled or cancel_flag.is_set():
            raise TaskCancelled("Cancelled during bash")

    def _run_merge_from_main(self, task_name: str, cancel_flag: threading.Event) -> None:
        task_dir = self.tasks_root / task_name

        def stream_bash(
            td: Path,
            shell_command: str,
            cwd: Path,
            cancel_event: threading.Event,
        ):
            hooks = self._stream_hooks(task_dir)
            result = run_bash_stream(
                td,
                shell_command,
                cwd=cwd,
                cancel_event=cancel_event,
                hooks=hooks,
            )
            if result.cancelled or cancel_event.is_set():
                raise TaskCancelled("Cancelled during merge-from-main git phase")
            return result

        def run_conflict(
            td: Path,
            cancel_event: threading.Event,
            on_start: Callable[[Path], None] | None,
        ) -> None:
            def runner(task_dir_arg: Path, upload_on_start: Callable[[Path], None], flag: threading.Event) -> None:
                def combined_on_start(path: Path) -> None:
                    upload_on_start(path)
                    if on_start is not None:
                        on_start(path)

                run_merge_conflict_resolution(
                    task_dir_arg,
                    on_start=combined_on_start,
                    cancel_event=flag,
                )

            self._run_agent_with_log(task_dir, cancel_event, runner)

        hooks = MergeFromMainHooks(
            stream_bash=stream_bash,
            run_conflict_resolution=run_conflict,
        )
        run_merge_from_main(task_dir, cancel_event=cancel_flag, hooks=hooks)


def run_loop() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    _load_cursor_api_key()
    client = WorkerClient()
    tasks_root = _tasks_root()
    executor = CommandExecutor(tasks_root)
    poller = CloudPoller(client, tasks_root)
    task_locks: dict[str, threading.Lock] = {}
    task_locks_guard = threading.Lock()

    def task_lock(task_name: str) -> threading.Lock:
        with task_locks_guard:
            lock = task_locks.get(task_name)
            if lock is None:
                lock = threading.Lock()
                task_locks[task_name] = lock
            return lock

    logger.info("Worker started env=%s tasks_root=%s", client.env_id, tasks_root)

    def run_command(task_name: str, command: dict) -> None:
        with task_lock(task_name):
            executor.execute(task_name, command)

    while True:
        try:
            data = client.poll(claim_work=False)
            poller.run_sync_pass(data.get("sync_tasks", []))
            work_data = client.poll(claim_work=True)
            executor.reconcile_orphans(work_data.get("active_commands", []))
            for d in work_data.get("deletions", []):
                task_name = d["task_name"]
                filename = d["filename"]
                fp = comms_dir(tasks_root / task_name) / filename
                if fp.is_file():
                    fp.unlink()
                client.ack_deletion(task_name, filename)
            for item in work_data.get("work", []):
                task_name = item["task_name"]
                command = item["command"]
                if command.get("command") == "cancel":
                    executor.request_cancel(task_name)
                    continue
                if not executor.try_start(task_name):
                    continue
                try:
                    client.command_start(task_name)
                except Exception:
                    logger.exception("command_start failed for %s", task_name)
                    executor.discard_running(task_name)
                    continue
                threading.Thread(
                    target=run_command,
                    args=(task_name, command),
                    daemon=True,
                    name=f"dev-cmd-{task_name}",
                ).start()
        except Exception:
            logger.exception("Poll loop error")
        time.sleep(POLL_INTERVAL_SEC)


def main() -> None:
    run_loop()


if __name__ == "__main__":
    main()
