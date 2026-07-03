"""Environment worker: polls control plane and executes commands locally."""

from __future__ import annotations

import json
import logging
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

import requests

from dev_sdk.agent_run import (
    AgentRunError,
    run_do,
    run_implement,
    run_plan_implement,
    run_question_mode,
)
from dev_sdk.comms import (
    add_comms,
    bash_comms_input_header,
    begin_streaming_bash_comms,
    comms_dir,
    read_index,
)
from dev_sdk.task_manager import TaskCancelled, TaskManager

logger = logging.getLogger("dev_cloud_worker")
POLL_INTERVAL_SEC = float(os.environ.get("DEV_CLOUD_POLL_INTERVAL", "5"))
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

    def poll(self) -> dict:
        resp = self.session.post(
            f"{self.base}/worker/poll",
            json={"environment_id": self.env_id, "display_name": _load_display_name()},
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

    def upload_log_chunk(self, task_name: str, filename: str, chunk: bytes) -> None:
        import base64

        self.session.post(
            f"{self.base}/worker/tasks/{task_name}/logs",
            json={"filename": filename, "chunk_b64": base64.b64encode(chunk).decode("ascii")},
            timeout=30,
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
    def __init__(self, client: WorkerClient) -> None:
        self.client = client
        self.tasks_root = _tasks_root()
        self.manager = TaskManager(self.tasks_root)
        self._cancel_flags: dict[str, threading.Event] = {}
        self._cancel_lock = threading.Lock()

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
        try:
            if cmd == "create-task":
                self._create_task(task_name, payload, cancel_flag)
            elif cmd == "archive":
                self._archive(task_name, payload)
            elif cmd == "unarchive":
                self._unarchive(task_name, payload)
            elif cmd == "copy-from-archive":
                self._copy_from_archive(task_name, payload)
            elif cmd == "cancel":
                cancel_flag.set()
                return
            elif cmd in ("question", "plan-implement", "implement", "do"):
                self._run_agent(task_name, cmd, payload.get("prompt"), cancel_flag)
            elif cmd == "bash":
                self._run_bash(task_name, payload.get("prompt", ""), cancel_flag)
            else:
                raise RuntimeError(f"Unknown command: {cmd}")
            self.client.complete_command(task_name, result=self._task_result(task_name))
        except TaskCancelled as e:
            logger.info("Command cancelled for %s: %s", task_name, e)
            if cmd == "create-task":
                task_dir = self.tasks_root / task_name
                if task_dir.is_dir():
                    shutil.rmtree(task_dir, ignore_errors=True)
            self.client.complete_command(task_name, error="Cancelled")
        except Exception as e:
            logger.exception("Command failed for %s: %s", task_name, e)
            self.client.complete_command(task_name, error=str(e))
        finally:
            cancel_flag.clear()
            self._sync_comms(task_name)

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
        def on_progress(msg: str) -> None:
            self.client.progress(task_name, msg)

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

    def _run_agent(
        self,
        task_name: str,
        command: str,
        prompt: str | None,
        cancel_flag: threading.Event,
    ) -> None:
        task_dir = self.tasks_root / task_name
        log_path_holder: dict[str, Path | None] = {"path": None}
        uploaded_size = {"bytes": 0}

        def on_start(stream_log_path: Path) -> None:
            log_path_holder["path"] = stream_log_path
            uploaded_size["bytes"] = 0
            self.client.upload_log_chunk(task_name, stream_log_path.name, b"")

        def tail_log() -> None:
            while not cancel_flag.is_set():
                path = log_path_holder["path"]
                if path and path.is_file():
                    data = path.read_bytes()
                    if len(data) > uploaded_size["bytes"]:
                        self.client.upload_log_chunk(
                            task_name,
                            path.name,
                            data[uploaded_size["bytes"] :],
                        )
                        uploaded_size["bytes"] = len(data)
                time.sleep(1)

        t = threading.Thread(target=tail_log, daemon=True)
        t.start()
        try:
            if command == "question":
                run_question_mode(task_dir, on_start=on_start, cancel_event=cancel_flag)
            elif command == "plan-implement":
                run_plan_implement(task_dir, on_start=on_start, cancel_event=cancel_flag)
            elif command == "implement":
                run_implement(task_dir, on_start=on_start, cancel_event=cancel_flag)
            elif command == "do":
                if not prompt or not str(prompt).strip():
                    raise RuntimeError("Missing prompt for do command")
                run_do(task_dir, str(prompt).strip(), on_start=on_start, cancel_event=cancel_flag)
            else:
                raise RuntimeError(f"Unknown agent command: {command}")
        except AgentRunError as e:
            raise RuntimeError(str(e)) from e
        finally:
            cancel_flag.set()
            t.join(timeout=2)
            path = log_path_holder["path"]
            if path and path.is_file():
                data = path.read_bytes()
                if len(data) > uploaded_size["bytes"]:
                    self.client.upload_log_chunk(
                        task_name,
                        path.name,
                        data[uploaded_size["bytes"] :],
                    )

    def _run_bash(
        self,
        task_name: str,
        shell_command: str,
        cancel_flag: threading.Event,
    ) -> None:
        task_dir = self.tasks_root / task_name
        path = begin_streaming_bash_comms(task_dir, shell_command)
        proc = subprocess.Popen(
            ["bash", "-c", shell_command],
            cwd=str(task_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            if cancel_flag.is_set():
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                raise TaskCancelled("Cancelled during bash")
            with open(path, "ab") as f:
                f.write(line)
        proc.wait()
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"\n---\nExit code: {proc.returncode}\n")
        self._sync_comms(task_name)

    def _sync_comms(self, task_name: str) -> None:
        task_dir = self.tasks_root / task_name
        if not task_dir.is_dir():
            return
        push: list[dict] = []
        cdir = comms_dir(task_dir)
        if cdir.is_dir():
            for filename in read_index(task_dir):
                fp = cdir / filename
                if fp.is_file():
                    push.append(
                        {
                            "filename": filename,
                            "content": fp.read_text(encoding="utf-8", errors="replace"),
                            "origin": "worker",
                            "created_at": fp.stat().st_mtime,
                            "deletable": None,
                        }
                    )
        pull = self.client.sync_push(task_name, push)
        for item in pull:
            fp = cdir / item["filename"]
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_text(item["content"], encoding="utf-8")


def run_loop() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    _load_cursor_api_key()
    client = WorkerClient()
    executor = CommandExecutor(client)
    command_lock = threading.Lock()
    logger.info("Worker started env=%s tasks_root=%s", client.env_id, _tasks_root())

    def run_command(task_name: str, command: dict) -> None:
        with command_lock:
            executor.execute(task_name, command)

    while True:
        try:
            data = client.poll()
            for d in data.get("deletions", []):
                task_name = d["task_name"]
                filename = d["filename"]
                fp = comms_dir(_tasks_root() / task_name) / filename
                if fp.is_file():
                    fp.unlink()
                client.ack_deletion(task_name, filename)
            for item in data.get("work", []):
                task_name = item["task_name"]
                command = item["command"]
                if command.get("command") == "cancel":
                    executor.request_cancel(task_name)
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
