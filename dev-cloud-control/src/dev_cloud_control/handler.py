"""HTTP request routing for the cloud control plane."""

from __future__ import annotations

import base64
import json
import re
import time
import uuid
from decimal import Decimal
from typing import Any
from urllib.parse import parse_qs, unquote

from dev_sdk.create_pr import (
    CreatePRError,
    create_pull_request_from_metadata,
    find_pull_request_from_metadata,
    pull_pr_comments_from_metadata,
)
from dev_sdk.feed import FeedCursor, FeedEntry
from dev_sdk.question_answers import AnswerItem, build_answers_markdown
from dev_sdk.task_list_status import resolve_task_list_status, task_status_input_from_command_body

from dev_cloud_control.store import (
    ArchiveRecord,
    CloudStore,
    FeedItem,
    TaskRecord,
    collect_pr_comment_keys,
    next_comms_filename,
)
from dev_sdk.stream_sse import SSE_HEADERS, STREAM_MAX_DURATION_SEC, run_task_stream

SUPPORTED_COMMANDS = ("question", "plan-implement", "implement", "do", "bash", "merge-from-main")
WORKER_REBOOT_MESSAGE = (
    "Worker rebooted — command cancelled; workspace may have uncommitted changes"
)


def _command_execution_started(active: dict | None) -> bool:
    return bool(active and active.get("started"))


def _task_comms_synced(task: TaskRecord) -> bool:
    return int(task.worker_comms_epoch or 0) >= int(task.comms_cloud_epoch or 0)


def _environment_online(store: CloudStore, environment_id: str) -> bool:
    env = store.get_environment(environment_id)
    return bool(env and env.online)


def _command_cancelling(active: dict | None) -> bool:
    if not active:
        return False
    return bool(active.get("cancelling") or active.get("cancel_requested"))


def _append_cancelling_progress(progress: list[str]) -> list[str]:
    out = list(progress)
    if not out or out[-1] != "Cancelling…":
        out.append("Cancelling…")
    return out


def _force_clear_active_command(task: TaskRecord) -> dict[str, Any]:
    progress = _append_cancelling_progress(list(task.create_progress or []))
    return {
        "active_command": None,
        "create_progress": progress,
        "last_command_error": "Cancelled",
    }


def _json_default(obj: Any) -> Any:
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def _json(status: int, body: Any, headers: dict | None = None) -> dict:
    h = {"Content-Type": "application/json", "Access-Control-Allow-Origin": "*"}
    if headers:
        h.update(headers)
    return {
        "statusCode": status,
        "headers": h,
        "body": json.dumps(body, default=_json_default) if body is not None else "",
    }


def _text(status: int, body: str, content_type: str = "text/plain") -> dict:
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": content_type,
            "Access-Control-Allow-Origin": "*",
        },
        "body": body,
    }


def _no_content() -> dict:
    return {"statusCode": 204, "headers": {"Access-Control-Allow-Origin": "*"}, "body": ""}


def _parse_body(event: dict) -> Any:
    body = event.get("body") or ""
    if event.get("isBase64Encoded"):
        body = base64.b64decode(body).decode("utf-8")
    if not body:
        return None
    return json.loads(body)


def _path_params(event: dict) -> dict[str, str]:
    return event.get("pathParameters") or {}


def _query(event: dict) -> dict[str, list[str]]:
    return parse_qs(event.get("rawQueryString") or "")


def _normalize_path(path: str) -> str:
    if path.startswith("/api"):
        path = path[4:]
    if not path.startswith("/"):
        path = "/" + path
    return path.rstrip("/") or "/"


class Router:
    def __init__(self, store: CloudStore | None = None) -> None:
        self.store = store or CloudStore()

    def _notify_cloud_comms_changed(self, task_name: str) -> None:
        self.store.bump_comms_cloud_epoch(task_name)

    def _pending_command_state(self, task: TaskRecord) -> str | None:
        if not task.queued_command and not task.active_command:
            return None
        if _command_execution_started(task.active_command):
            return None
        if not _environment_online(self.store, task.environment_id):
            return "worker_offline"
        return "syncing"

    def _command_status_body(self, task: TaskRecord) -> dict[str, Any]:
        active = task.active_command
        queued = task.queued_command
        progress = list(task.create_progress or [])
        pending_state = self._pending_command_state(task)
        started = _command_execution_started(active)
        if started and active:
            pending_state = None
            if not _environment_online(self.store, task.environment_id):
                pending_state = "worker_offline"
            return {
                "active": True,
                "command": active.get("command"),
                "active_log_filename": active.get("active_log_filename"),
                "active_bash_comms_filename": active.get("active_bash_comms_filename"),
                "command_error": active.get("command_error"),
                "create_progress": progress,
                "queued": False,
                "cancelling": _command_cancelling(active),
                "pending_state": pending_state,
            }
        cmd = None
        if queued:
            cmd = queued.get("command")
        elif active:
            cmd = active.get("command")
        if queued or (active and not started):
            return {
                "active": False,
                "command": cmd,
                "active_log_filename": None,
                "active_bash_comms_filename": None,
                "command_error": None,
                "create_progress": progress,
                "queued": bool(queued),
                "cancelling": _command_cancelling(active),
                "pending_state": pending_state,
            }
        return {
            "active": False,
            "command": None,
            "active_log_filename": None,
            "active_bash_comms_filename": None,
            "command_error": task.last_command_error,
            "create_progress": progress,
            "queued": False,
            "cancelling": False,
            "pending_state": None,
        }

    def dispatch(self, event: dict, context: Any = None) -> dict:
        method = event.get("requestContext", {}).get("http", {}).get("method") or event.get("httpMethod", "GET")
        path = _normalize_path(event.get("rawPath") or event.get("path", "/"))

        if method == "OPTIONS":
            return {
                "statusCode": 204,
                "headers": {
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Methods": "GET,POST,PUT,DELETE,OPTIONS",
                    "Access-Control-Allow-Headers": "Content-Type,Authorization",
                },
                "body": "",
            }

        if path.startswith("/worker"):
            return self._worker_dispatch(method, path, event)

        routes = {
            ("GET", "/environments"): self.list_environments,
            ("GET", "/repos"): self.get_repos,
            ("POST", "/repos"): self.add_repo,
            ("GET", "/drafts/new-task"): self.get_new_task_draft,
            ("PUT", "/drafts/new-task"): self.set_new_task_draft,
            ("GET", "/tasks"): self.list_tasks,
            ("POST", "/tasks"): self.create_task,
            ("GET", "/archive"): self.list_archive,
            ("GET", "/config/bots"): self.get_bots,
            ("PUT", "/config/bots"): self.set_bots,
        }
        handler = routes.get((method, path))
        if handler:
            return handler(event)

        m = re.match(r"^/environments/([^/]+)$", path)
        if m and method == "GET":
            return self.get_environment(event, unquote(m.group(1)))
        if m and method == "PUT":
            return self.update_environment(event, unquote(m.group(1)))
        if m and method == "DELETE":
            return self.delete_environment(event, unquote(m.group(1)))

        m = re.match(r"^/repos/([^/]+)$", path)
        if m and method == "DELETE":
            return self.remove_repo(event, unquote(m.group(1)))

        m = re.match(r"^/tasks/([^/]+)/workspace$", path)
        if m and method == "GET":
            return self.get_task_workspace(event, unquote(m.group(1)))

        m = re.match(r"^/tasks/([^/]+)/drafts/comment$", path)
        if m and method == "GET":
            return self.get_comment_draft(event, unquote(m.group(1)))
        if m and method == "PUT":
            return self.set_comment_draft(event, unquote(m.group(1)))

        m = re.match(r"^/tasks/([^/]+)/drafts/bash$", path)
        if m and method == "GET":
            return self.get_bash_draft(event, unquote(m.group(1)))
        if m and method == "PUT":
            return self.set_bash_draft(event, unquote(m.group(1)))

        m = re.match(r"^/tasks/([^/]+)/drafts/question-answers/([^/]+)$", path)
        if m and method == "GET":
            return self.get_question_answers_draft(event, unquote(m.group(1)), unquote(m.group(2)))
        if m and method == "PUT":
            return self.set_question_answers_draft(event, unquote(m.group(1)), unquote(m.group(2)))

        m = re.match(r"^/tasks/([^/]+)/archive$", path)
        if m and method == "POST":
            return self.archive_task(event, unquote(m.group(1)))

        m = re.match(r"^/tasks/([^/]+)/comms$", path)
        if m and method == "GET":
            return self.list_comms(event, unquote(m.group(1)))
        if m and method == "POST":
            return self.post_comms(event, unquote(m.group(1)))

        m = re.match(r"^/tasks/([^/]+)/comms/question-answers$", path)
        if m and method == "POST":
            return self.post_question_answers(event, unquote(m.group(1)))

        m = re.match(r"^/tasks/([^/]+)/comms/([^/]+)$", path)
        if m and method == "GET":
            return self.get_comms_file(event, unquote(m.group(1)), unquote(m.group(2)))
        if m and method == "DELETE":
            return self.delete_comms(event, unquote(m.group(1)), unquote(m.group(2)))

        m = re.match(r"^/tasks/([^/]+)/feed$", path)
        if m and method == "GET":
            return self.get_feed(event, unquote(m.group(1)))

        m = re.match(r"^/tasks/([^/]+)/feed/deletable$", path)
        if m and method == "GET":
            return self.get_feed_deletable(event, unquote(m.group(1)))

        m = re.match(r"^/tasks/([^/]+)/logs/([^/]+)$", path)
        if m and method == "GET":
            return self.get_log_file(event, unquote(m.group(1)), unquote(m.group(2)))

        m = re.match(r"^/tasks/([^/]+)/stream$", path)
        if m and method == "GET":
            return self.task_stream(event, unquote(m.group(1)))

        m = re.match(r"^/tasks/([^/]+)/logs/stream$", path)
        if m and method == "GET":
            return self.log_stream(event, unquote(m.group(1)))

        m = re.match(r"^/tasks/([^/]+)/commands$", path)
        if m and method == "GET":
            return self.get_command_status(event, unquote(m.group(1)))
        if m and method == "POST":
            return self.start_command(event, unquote(m.group(1)))

        m = re.match(r"^/tasks/([^/]+)/commands/cancel$", path)
        if m and method == "POST":
            return self.cancel_command(event, unquote(m.group(1)))

        m = re.match(r"^/tasks/([^/]+)/create-pr$", path)
        if m and method == "POST":
            return self.create_pr(event, unquote(m.group(1)))

        m = re.match(r"^/tasks/([^/]+)/pr$", path)
        if m and method == "GET":
            return self.get_pr(event, unquote(m.group(1)))

        m = re.match(r"^/tasks/([^/]+)/pull-pr-comments$", path)
        if m and method == "POST":
            return self.pull_pr_comments(event, unquote(m.group(1)))

        m = re.match(r"^/archive/([^/]+)/unarchive$", path)
        if m and method == "POST":
            return self.unarchive(event, unquote(m.group(1)))

        m = re.match(r"^/archive/([^/]+)/copy$", path)
        if m and method == "POST":
            return self.copy_from_archive(event, unquote(m.group(1)))

        return _json(404, {"detail": f"Not found: {method} {path}"})

    # --- environments ---

    def list_environments(self, event: dict) -> dict:
        envs = self.store.list_environments()
        return _json(
            200,
            {
                "environments": [
                    {
                        "environment_id": e.environment_id,
                        "display_name": e.display_name,
                        "online": e.online,
                        "last_heartbeat": e.last_heartbeat,
                        "registered_at": e.registered_at,
                    }
                    for e in envs
                ]
            },
        )

    def get_environment(self, event: dict, environment_id: str) -> dict:
        env = self.store.get_environment(environment_id)
        if not env:
            return _json(404, {"detail": "Environment not found"})
        return _json(
            200,
            {
                "environment_id": env.environment_id,
                "display_name": env.display_name,
                "online": env.online,
                "last_heartbeat": env.last_heartbeat,
                "registered_at": env.registered_at,
            },
        )

    def update_environment(self, event: dict, environment_id: str) -> dict:
        body = _parse_body(event) or {}
        name = body.get("display_name")
        if not isinstance(name, str) or not name.strip():
            return _json(400, {"detail": "display_name required"})
        if not self.store.get_environment(environment_id):
            return _json(404, {"detail": "Environment not found"})
        display_name = self.store.update_environment_display_name(environment_id, name.strip())
        return _json(200, {"display_name": display_name})

    def delete_environment(self, event: dict, environment_id: str) -> dict:
        if not self.store.get_environment(environment_id):
            return _json(404, {"detail": "Environment not found"})
        active_tasks = self.store.count_tasks_for_environment(environment_id)
        if active_tasks > 0:
            return _json(
                409,
                {"detail": f"Cannot delete environment with {active_tasks} active task(s)"},
            )
        self.store.delete_environment(environment_id)
        return _no_content()

    # --- repos ---

    def get_repos(self, event: dict) -> dict:
        return _json(200, self.store.get_repos())

    def add_repo(self, event: dict) -> dict:
        body = _parse_body(event) or {}
        name = (body.get("name") or "").strip()
        url = (body.get("url") or "").strip()
        if not name or not url:
            return _json(400, {"detail": "name and url required"})
        repos = self.store.get_repos()
        repos[name] = url
        self.store.save_repos(repos)
        return _json(200, repos)

    def remove_repo(self, event: dict, shorthand: str) -> dict:
        repos = self.store.get_repos()
        if shorthand not in repos:
            return _json(404, {"detail": "Repo not found"})
        del repos[shorthand]
        self.store.save_repos(repos)
        return _no_content()

    def get_bots(self, event: dict) -> dict:
        return _json(200, {"bots": self.store.get_bots()})

    def set_bots(self, event: dict) -> dict:
        body = _parse_body(event) or {}
        bots = body.get("bots")
        if not isinstance(bots, list):
            return _json(400, {"detail": "bots array required"})
        cleaned: list[dict[str, str]] = []
        for b in bots:
            if isinstance(b, dict) and isinstance(b.get("org"), str) and isinstance(b.get("secret"), str):
                cleaned.append({"org": b["org"].strip(), "secret": b["secret"].strip()})
        self.store.save_bots(cleaned)
        return _json(200, {"bots": cleaned})

    # --- drafts ---

    def get_new_task_draft(self, event: dict) -> dict:
        data = self.store.get_draft("new-task") or {}
        return _json(200, data if isinstance(data, dict) else {})

    def set_new_task_draft(self, event: dict) -> dict:
        body = _parse_body(event) or {}
        self.store.set_draft("new-task", body)
        return _no_content()

    def get_comment_draft(self, event: dict, task_name: str) -> dict:
        data = self.store.get_draft(f"comment-{task_name}")
        return _text(200, data if isinstance(data, str) else "")

    def set_comment_draft(self, event: dict, task_name: str) -> dict:
        body = _parse_body(event) or {}
        content = body.get("content", "")
        sk = f"comment-{task_name}"
        if not str(content).strip():
            self.store.delete_draft(sk)
        else:
            self.store.set_draft(sk, str(content))
        return _no_content()

    def get_bash_draft(self, event: dict, task_name: str) -> dict:
        data = self.store.get_draft(f"bash-{task_name}")
        return _text(200, data if isinstance(data, str) else "")

    def set_bash_draft(self, event: dict, task_name: str) -> dict:
        body = _parse_body(event) or {}
        content = body.get("content", "")
        sk = f"bash-{task_name}"
        if not str(content).strip():
            self.store.delete_draft(sk)
        else:
            self.store.set_draft(sk, str(content))
        return _no_content()

    def get_question_answers_draft(self, event: dict, task_name: str, comms_filename: str) -> dict:
        sk = f"question-answers-{task_name}-{comms_filename.replace('/', '_')}"
        data = self.store.get_draft(sk)
        return _json(200, data if isinstance(data, dict) else {})

    def set_question_answers_draft(self, event: dict, task_name: str, comms_filename: str) -> dict:
        body = _parse_body(event) or {}
        sk = f"question-answers-{task_name}-{comms_filename.replace('/', '_')}"
        selections = body.get("selections") or {}
        free_text = body.get("freeText") or {}
        expanded = body.get("expandedFreeText") or {}
        editing = body.get("editing")
        if not selections and not free_text and not expanded and not editing:
            self.store.delete_draft(sk)
        else:
            self.store.set_draft(sk, body)
        return _no_content()

    # --- tasks ---

    def list_tasks(self, event: dict) -> dict:
        tasks = []
        for name in self.store.list_tasks():
            task = self.store.get_task(name)
            if not task:
                continue
            body = self._command_status_body(task)
            comms = self._comms_index(name)
            inp = task_status_input_from_command_body(body, comms_index=comms)
            status = resolve_task_list_status(inp).value
            tasks.append({"name": name, "status": status})
        return _json(200, {"tasks": tasks})

    def get_task_workspace(self, event: dict, task_name: str) -> dict:
        task = self.store.get_task(task_name)
        if not task:
            return _json(404, {"detail": "Task not found"})
        label = task.repo
        return _json(200, {"repo_label": label})

    def create_task(self, event: dict) -> dict:
        body = _parse_body(event) or {}
        title = (body.get("title") or "").strip()
        if not title:
            return _json(400, {"detail": "title required"})
        environment_id = (body.get("environment_id") or "").strip()
        if not environment_id:
            return _json(400, {"detail": "environment_id required"})
        env = self.store.get_environment(environment_id)
        if not env:
            return _json(400, {"detail": "Unknown environment"})
        task_name = self._unique_task_name(title)
        repo_shorthand = body.get("repo")
        repo_url: str | None = None
        owner: str | None = None
        repo_name: str | None = None
        if repo_shorthand:
            try:
                repo_url = self._resolve_repo(str(repo_shorthand))
            except ValueError as e:
                return _json(400, {"detail": str(e)})
            owner, repo_name = self._parse_github_owner_repo(repo_url)
        branch = f"task/{task_name}"
        record = TaskRecord(
            task_name=task_name,
            environment_id=environment_id,
            title=title,
            repo=repo_shorthand if repo_shorthand else None,
            owner=owner,
            repo_name=repo_name,
            branch=branch,
            queued_command={
                "command": "create-task",
                "payload": {
                    "title": title,
                    "comment": body.get("comment"),
                    "repo_url": repo_url,
                },
                "queued_at": time.time(),
            },
        )
        try:
            self.store.create_task(record)
        except Exception as e:
            if "ConditionalCheckFailed" in str(e):
                return _json(409, {"detail": "Task name collision"})
            raise
        self.store.delete_draft("new-task")
        lines = [
            json.dumps({"type": "progress", "message": "Task queued for environment."}),
            json.dumps(
                {
                    "type": "complete",
                    "task_name": task_name,
                    "task_dir": task_name,
                }
            ),
        ]
        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/x-ndjson",
                "Access-Control-Allow-Origin": "*",
            },
            "body": "\n".join(lines) + "\n",
        }

    def _resolve_repo(self, repo: str) -> str:
        if "://" in repo or repo.startswith("git@"):
            return repo
        repos = self.store.get_repos()
        if repo not in repos:
            raise ValueError(f"Unknown repo shorthand: {repo!r}")
        return repos[repo]

    def _unique_task_name(self, title: str) -> str:
        base = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-") or "task"
        name = base
        n = 2
        while self.store.get_task(name):
            name = f"{base}-{n}"
            n += 1
        return name

    def _parse_github_owner_repo(self, url: str) -> tuple[str | None, str | None]:
        m = re.match(r"https?://(?:[^@/]+@)?github\.com[/:]([^/]+)/([^/]+?)(?:\.git)?/?$", url)
        if m:
            return m.group(1), m.group(2)
        m = re.match(r"git@github\.com:([^/]+)/([^/]+?)(?:\.git)?/?$", url)
        if m:
            return m.group(1), m.group(2)
        return None, None

    # --- comms ---

    def list_comms(self, event: dict, task_name: str) -> dict:
        if not self.store.get_task(task_name):
            return _json(404, {"detail": "Task not found"})
        files = [f for f in self.store.list_comms_keys(task_name) if f != "index.txt"]
        index = self._comms_index(task_name)
        ordered = [f for f in index if f in files]
        for f in sorted(files):
            if f not in ordered:
                ordered.append(f)
        return _json(200, {"files": ordered})

    def _comms_index(self, task_name: str) -> list[str]:
        raw = self.store.get_comms(task_name, "index.txt")
        if not raw:
            return []
        return [ln.strip() for ln in raw.splitlines() if ln.strip()]

    def _append_comms_index(self, task_name: str, filename: str) -> None:
        index = self._comms_index(task_name)
        if filename not in index:
            index.append(filename)
            self.store.put_comms(task_name, "index.txt", "\n".join(index) + "\n", origin="cloud")

    def post_comms(self, event: dict, task_name: str) -> dict:
        if not self.store.get_task(task_name):
            return _json(404, {"detail": "Task not found"})
        body = _parse_body(event) or {}
        content = (body.get("content") or "").strip()
        if not content:
            return _json(400, {"detail": "content required"})
        existing = self.store.list_comms_keys(task_name)
        filename = next_comms_filename(existing, "user")
        self.store.put_comms(task_name, filename, content + "\n", origin="cloud")
        self._append_comms_index(task_name, filename)
        ts = time.time()
        self.store.put_feed_item(
            task_name,
            FeedItem(type="comms", id=filename, created_at=ts, deletable=True, origin="cloud"),
        )
        self._notify_cloud_comms_changed(task_name)
        self.store.delete_draft(f"comment-{task_name}")
        return _json(201, {"filename": filename})

    def post_question_answers(self, event: dict, task_name: str) -> dict:
        if not self.store.get_task(task_name):
            return _json(404, {"detail": "Task not found"})
        body = _parse_body(event) or {}
        answers_raw = body.get("answers") or []
        answers = [
            AnswerItem(
                id=a.get("id", ""),
                text=a.get("text", ""),
                selected=a.get("selected", ""),
                free_text=a.get("free_text", ""),
            )
            for a in answers_raw
            if isinstance(a, dict)
        ]
        content = build_answers_markdown(body.get("source", ""), answers)
        existing = self.store.list_comms_keys(task_name)
        filename = next_comms_filename(existing, "user")
        self.store.put_comms(task_name, filename, content, origin="cloud")
        self._append_comms_index(task_name, filename)
        ts = time.time()
        self.store.put_feed_item(
            task_name,
            FeedItem(type="comms", id=filename, created_at=ts, deletable=True, origin="cloud"),
        )
        self._notify_cloud_comms_changed(task_name)
        source = body.get("source", "")
        if source:
            sk = f"question-answers-{task_name}-{str(source).replace('/', '_')}"
            self.store.delete_draft(sk)
        return _json(201, {"filename": filename})

    def get_comms_file(self, event: dict, task_name: str, filename: str) -> dict:
        content = self.store.get_comms(task_name, filename)
        if content is None:
            return _json(404, {"detail": "Comms file not found"})
        return _text(200, content)

    def delete_comms(self, event: dict, task_name: str, filename: str) -> dict:
        items = self.store.list_feed_items(task_name)
        fi = next((i for i in items if i.type == "comms" and i.id == filename), None)
        if fi and fi.deletable is False:
            return _json(403, {"detail": "Comms file is not deletable"})
        self.store.update_feed_item(task_name, filename, delete_status="delete_pending")
        return _no_content()

    # --- feed ---

    def get_feed(self, event: dict, task_name: str) -> dict:
        if not self.store.get_task(task_name):
            return _json(404, {"detail": "Task not found"})
        q = _query(event)
        limit = int(q.get("limit", ["50"])[0])
        after = float(q["after"][0]) if "after" in q else None
        before_created = float(q["before_created_at"][0]) if "before_created_at" in q else None
        before_id = q.get("before_id", [None])[0]

        entries = self._feed_entries(task_name)
        if after is not None:
            entries = [e for e in entries if e.created_at > after]
        if before_created is not None and before_id:
            cursor = FeedCursor(created_at=before_created, id=before_id)
            entries = [
                e
                for e in entries
                if (e.created_at, e.id) < (cursor.created_at, cursor.id)
            ]
        total = len(entries)
        page = entries[-limit:] if limit else entries
        has_older = len(entries) > len(page)
        oldest = page[0] if page else None
        return _json(
            200,
            {
                "entries": [
                    {
                        "type": e.type,
                        "id": e.id,
                        "created_at": e.created_at,
                        "deletable": e.deletable,
                    }
                    for e in page
                ],
                "total": total,
                "has_older": has_older,
                "oldest_cursor": (
                    {"created_at": oldest.created_at, "id": oldest.id} if oldest else None
                ),
            },
        )

    def _feed_entries(self, task_name: str) -> list[FeedEntry]:
        items = self.store.list_feed_items(task_name)
        visible = [i for i in items if i.delete_status != "deleted"]
        return [
            FeedEntry(
                type=i.type,
                id=i.id,
                created_at=i.created_at,
                deletable=i.deletable,
            )
            for i in visible
        ]

    def get_feed_deletable(self, event: dict, task_name: str) -> dict:
        entries = self._feed_entries(task_name)
        return _json(
            200,
            {e.id: bool(e.deletable) for e in entries if e.type == "comms" and e.deletable is not None},
        )

    def get_log_file(self, event: dict, task_name: str, filename: str) -> dict:
        return _text(200, self.store.get_log(task_name, filename))

    def _stream_offsets(self, event: dict) -> tuple[int, int]:
        q = _query(event)
        try:
            log_offset = int(q.get("log_offset", ["0"])[0])
        except ValueError:
            log_offset = 0
        try:
            bash_offset = int(q.get("bash_offset", ["0"])[0])
        except ValueError:
            bash_offset = 0
        return max(0, log_offset), max(0, bash_offset)

    def _task_stream_active(self, task_name: str) -> tuple[dict | None, dict | None]:
        task = self.store.get_task(task_name)
        if not task or not task.active_command:
            return None, None
        active = task.active_command
        return active, task

    def _read_log_chunk(self, task_name: str, active: dict, offset: int) -> tuple[str, int] | None:
        log_name = active.get("active_log_filename")
        if not log_name:
            return None
        data, total = self.store.read_stream_from_offset(task_name, "log", log_name, offset)
        if not data and total <= offset:
            return "", total
        return data.decode("utf-8", errors="replace"), total

    def _read_bash_chunk(self, task_name: str, active: dict, offset: int) -> tuple[str, int] | None:
        bash_name = active.get("active_bash_comms_filename")
        if not bash_name:
            return None
        data, total = self.store.read_stream_from_offset(task_name, "bash", bash_name, offset)
        if not data and total <= offset:
            return "", total
        return data.decode("utf-8", errors="replace"), total

    def _stream_max_duration(self, event: dict) -> float:
        q = _query(event)
        try:
            val = float(q.get("stream_duration", [str(STREAM_MAX_DURATION_SEC)])[0])
        except ValueError:
            val = STREAM_MAX_DURATION_SEC
        return min(STREAM_MAX_DURATION_SEC, max(0.5, val))

    def run_task_stream_sse(
        self,
        task_name: str,
        log_offset: int,
        bash_offset: int,
        write: Any,
        *,
        max_duration_sec: float | None = None,
    ) -> tuple[int, int]:
        def is_active() -> bool:
            active, _task = self._task_stream_active(task_name)
            return active is not None

        def read_log(offset: int) -> tuple[str, int] | None:
            active, _task = self._task_stream_active(task_name)
            if not active:
                return None
            return self._read_log_chunk(task_name, active, offset)

        def read_bash(offset: int) -> tuple[str, int] | None:
            active, _task = self._task_stream_active(task_name)
            if not active:
                return None
            return self._read_bash_chunk(task_name, active, offset)

        return run_task_stream(
            log_offset=log_offset,
            bash_offset=bash_offset,
            read_log=read_log,
            read_bash=read_bash,
            is_active=is_active,
            write=write,
            max_duration_sec=max_duration_sec or STREAM_MAX_DURATION_SEC,
        )

    def task_stream(self, event: dict, task_name: str) -> dict:
        log_offset, bash_offset = self._stream_offsets(event)
        max_duration = self._stream_max_duration(event)
        parts: list[str] = []

        def write(chunk: str) -> None:
            parts.append(chunk)

        self.run_task_stream_sse(
            task_name, log_offset, bash_offset, write, max_duration_sec=max_duration
        )
        return {
            "statusCode": 200,
            "headers": dict(SSE_HEADERS),
            "body": "".join(parts),
        }

    def log_stream(self, event: dict, task_name: str) -> dict:
        """Legacy alias: multiplexed stream with bash offset pinned at zero."""
        return self.task_stream(event, task_name)

    # --- commands ---

    def _maybe_auto_clear_offline_cancelling(self, task_name: str, task: TaskRecord) -> TaskRecord:
        if not task.active_command or not _command_cancelling(task.active_command):
            return task
        if _environment_online(self.store, task.environment_id):
            return task
        self.store.update_task(task_name, **_force_clear_active_command(task))
        return self.store.get_task(task_name) or task

    def get_command_status(self, event: dict, task_name: str) -> dict:
        task = self.store.get_task(task_name)
        if not task:
            return _json(404, {"detail": "Task not found"})
        task = self._maybe_auto_clear_offline_cancelling(task_name, task)
        return _json(200, self._command_status_body(task))

    def start_command(self, event: dict, task_name: str) -> dict:
        task = self.store.get_task(task_name)
        if not task:
            return _json(404, {"detail": "Task not found"})
        if task.active_command or task.queued_command:
            return _json(409, {"detail": "A command is already active or queued"})
        body = _parse_body(event) or {}
        command = body.get("command")
        if command not in SUPPORTED_COMMANDS:
            return _json(400, {"detail": f"Unsupported command: {command}"})
        if command == "merge-from-main" and not task.repo:
            return _json(
                400,
                {
                    "detail": (
                        "This task has no cloned repository under the task root; "
                        "Merge from main is not available."
                    )
                },
            )
        payload: dict[str, Any] = {}
        if body.get("prompt") is not None:
            payload["prompt"] = body["prompt"]
        self.store.update_task(
            task_name,
            queued_command={
                "command": command,
                "payload": payload,
                "queued_at": time.time(),
            },
        )
        if command == "do":
            self.store.delete_draft(f"comment-{task_name}")
        return _json(201, {"command": command, "status": "queued"})

    def cancel_command(self, event: dict, task_name: str) -> dict:
        task = self.store.get_task(task_name)
        if not task:
            return _json(404, {"detail": "Task not found"})
        if task.queued_command:
            progress = _append_cancelling_progress(list(task.create_progress or []))
            self.store.update_task(
                task_name,
                queued_command=None,
                create_progress=progress,
                last_command_error="Cancelled",
            )
            return _no_content()
        if task.active_command:
            if not _environment_online(self.store, task.environment_id):
                self.store.update_task(task_name, **_force_clear_active_command(task))
                return _no_content()
            active = dict(task.active_command)
            if _command_cancelling(active):
                self.store.update_task(task_name, **_force_clear_active_command(task))
                return _no_content()
            active["cancel_requested"] = True
            active["cancelling"] = True
            updates: dict[str, Any] = {"active_command": active}
            if active.get("command") == "create-task":
                updates["create_progress"] = _append_cancelling_progress(
                    list(task.create_progress or [])
                )
            self.store.update_task(task_name, **updates)
            return _no_content()
        return _json(400, {"detail": "No command to cancel"})

    # --- archive ---

    def archive_task(self, event: dict, task_name: str) -> dict:
        task = self.store.get_task(task_name)
        if not task:
            return _json(404, {"detail": "Task not found"})
        if task.active_command:
            return _json(409, {"detail": "Cancel the running command before archiving"})
        archived_name = f"{task_name}-{uuid.uuid4().hex[:6]}"
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self.store.put_archive(
            ArchiveRecord(
                archived_name=archived_name,
                task_name=task_name,
                source_environment_id=task.environment_id,
                archived_date=time.strftime("%b-%d", time.gmtime()),
                archived_at=now,
                last_modified_at=now,
                repo=task.repo,
                branch=task.branch,
                owner=task.owner,
                repo_name=task.repo_name,
            )
        )
        self.store.update_task(
            task_name,
            status="archived",
            queued_command={
                "command": "archive",
                "payload": {"archived_name": archived_name},
                "queued_at": time.time(),
            },
        )
        return _json(200, {"archived_to": archived_name})

    def list_archive(self, event: dict) -> dict:
        q = _query(event)
        limit = int(q.get("limit", ["50"])[0])
        offset = int(q.get("offset", ["0"])[0])
        entries, total = self.store.list_archives(limit=limit, offset=offset)
        envs = {e.environment_id: e.display_name for e in self.store.list_environments()}
        return _json(
            200,
            {
                "entries": [
                    {
                        "archived_name": e.archived_name,
                        "task_name": e.task_name,
                        "archived_date": e.archived_date,
                        "archived_at": e.archived_at,
                        "last_modified_at": e.last_modified_at,
                        "source_environment_id": e.source_environment_id,
                        "source_environment_name": envs.get(e.source_environment_id, e.source_environment_id[:8]),
                    }
                    for e in entries
                ],
                "total": total,
                "next_offset": offset + len(entries) if offset + len(entries) < total else None,
            },
        )

    def unarchive(self, event: dict, archived_name: str) -> dict:
        rec = self.store.get_archive(archived_name)
        if not rec:
            return _json(404, {"detail": "Archive not found"})
        task = self.store.get_task(rec.task_name)
        env_id = rec.source_environment_id
        if not task:
            self.store.create_task(
                TaskRecord(
                    task_name=rec.task_name,
                    environment_id=env_id,
                    title=rec.task_name,
                    repo=rec.repo,
                    owner=rec.owner,
                    repo_name=rec.repo_name,
                    branch=rec.branch,
                    status="pending_unarchive",
                    queued_command={
                        "command": "unarchive",
                        "payload": {"archived_name": archived_name},
                        "queued_at": time.time(),
                    },
                )
            )
        else:
            self.store.update_task(
                rec.task_name,
                status="pending_unarchive",
                environment_id=env_id,
                queued_command={
                    "command": "unarchive",
                    "payload": {"archived_name": archived_name},
                    "queued_at": time.time(),
                },
            )
        return _json(200, {"restored_task_name": rec.task_name})

    def copy_from_archive(self, event: dict, archived_name: str) -> dict:
        rec = self.store.get_archive(archived_name)
        if not rec:
            return _json(404, {"detail": "Archive not found"})
        body = _parse_body(event) or {}
        task_name = (body.get("task_name") or "").strip() or self._unique_task_name(rec.task_name)
        environment_id = (body.get("environment_id") or rec.source_environment_id).strip()
        if self.store.get_task(task_name):
            return _json(409, {"detail": "Task already exists"})
        self.store.create_task(
            TaskRecord(
                task_name=task_name,
                environment_id=environment_id,
                title=rec.task_name,
                repo=rec.repo,
                owner=rec.owner,
                repo_name=rec.repo_name,
                branch=rec.branch or f"task/{task_name}",
                queued_command={
                    "command": "copy-from-archive",
                    "payload": {
                        "archived_name": archived_name,
                        "source_task_name": rec.task_name,
                        "repo_url": None,
                    },
                    "queued_at": time.time(),
                },
            )
        )
        return _json(201, {"task_name": task_name, "task_dir": task_name})

    # --- PR ---

    def create_pr(self, event: dict, task_name: str) -> dict:
        task = self.store.get_task(task_name)
        if not task or not task.owner or not task.repo_name or not task.branch:
            return _json(400, {"detail": "Task missing repo metadata"})
        try:
            url = create_pull_request_from_metadata(
                owner=task.owner,
                repo=task.repo_name,
                branch=task.branch,
                title=task.title,
                bots=self.store.get_bots(),
            )
        except CreatePRError as e:
            return _json(400, {"detail": str(e)})
        return _json(200, {"pr_url": url})

    def get_pr(self, event: dict, task_name: str) -> dict:
        task = self.store.get_task(task_name)
        if not task:
            return _json(404, {"detail": "Task not found"})
        if not task.owner or not task.repo_name or not task.branch:
            return _json(200, {"pr_url": None})
        try:
            url = find_pull_request_from_metadata(
                owner=task.owner,
                repo=task.repo_name,
                branch=task.branch,
                title=task.title,
                bots=self.store.get_bots(),
            )
        except CreatePRError as e:
            return _json(400, {"detail": str(e)})
        return _json(200, {"pr_url": url})

    def pull_pr_comments(self, event: dict, task_name: str) -> dict:
        task = self.store.get_task(task_name)
        if not task or not task.owner or not task.repo_name or not task.branch:
            return _json(400, {"detail": "Task missing repo metadata"})
        bodies = {
            f: self.store.get_comms(task_name, f) or ""
            for f in self.store.list_comms_keys(task_name)
        }
        known = collect_pr_comment_keys(bodies)
        try:
            pr_url, count, _items = pull_pr_comments_from_metadata(
                owner=task.owner,
                repo=task.repo_name,
                branch=task.branch,
                title=task.title,
                bots=self.store.get_bots(),
                known_keys=known,
            )
        except CreatePRError as e:
            return _json(400, {"detail": str(e)})
        if count == 0:
            return _json(200, {"pr_url": pr_url, "new_comments_count": 0, "comms_filename": None})
        content = self._format_pr_comments(pr_url, _items)
        existing = self.store.list_comms_keys(task_name)
        filename = next_comms_filename(existing, "agent", kind="pr-comments")
        self.store.put_comms(task_name, filename, content, origin="cloud")
        self._append_comms_index(task_name, filename)
        ts = time.time()
        self.store.put_feed_item(
            task_name,
            FeedItem(type="comms", id=filename, created_at=ts, deletable=False, origin="cloud"),
        )
        self._notify_cloud_comms_changed(task_name)
        return _json(
            200,
            {"pr_url": pr_url, "new_comments_count": count, "comms_filename": filename},
        )

    def _format_pr_comments(self, pr_url: str, items: list[dict]) -> str:
        lines = [f"# Pulled PR comments ({len(items)} new)", "", f"- PR: {pr_url}", ""]
        for item in items:
            kind = item["kind"]
            key = item["key"]
            payload = item["payload"]
            user = payload.get("user") if isinstance(payload.get("user"), dict) else {}
            author = user.get("login") or "unknown"
            body = str(payload.get("body") or "").strip()
            lines.append(f"## {kind.title()} comment `{key}`")
            lines.append(f"- Author: {author}")
            lines.append("")
            lines.append(body if body else "_(no body)_")
            lines.append("")
            lines.append(f"[//]: # (pr_comment_key: {key})")
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"

    # --- worker API ---

    def _worker_dispatch(self, method: str, path: str, event: dict) -> dict:
        if path == "/worker/poll" and method == "POST":
            return self.worker_poll(event)
        if path == "/worker/heartbeat" and method == "POST":
            return self.worker_heartbeat(event)
        if path == "/worker/git-token" and method == "POST":
            return self.worker_git_token(event)
        m = re.match(r"^/worker/tasks/([^/]+)/logs$", path)
        if m and method == "POST":
            return self.worker_upload_log(event, unquote(m.group(1)))
        m = re.match(r"^/worker/tasks/([^/]+)/sync$", path)
        if m and method == "POST":
            return self.worker_sync(event, unquote(m.group(1)))
        m = re.match(r"^/worker/tasks/([^/]+)/command/start$", path)
        if m and method == "POST":
            return self.worker_command_start(event, unquote(m.group(1)))
        m = re.match(r"^/worker/tasks/([^/]+)/command/complete$", path)
        if m and method == "POST":
            return self.worker_command_complete(event, unquote(m.group(1)))
        m = re.match(r"^/worker/tasks/([^/]+)/command/progress$", path)
        if m and method == "POST":
            return self.worker_command_progress(event, unquote(m.group(1)))
        m = re.match(r"^/worker/deletions/ack$", path)
        if m and method == "POST":
            return self.worker_deletion_ack(event)
        return _json(404, {"detail": f"Worker route not found: {path}"})

    def worker_poll(self, event: dict) -> dict:
        body = _parse_body(event) or {}
        env_id = (body.get("environment_id") or "").strip()
        if not env_id:
            env_id = str(uuid.uuid4())
        requested_name = body.get("display_name")
        env = self.store.get_environment(env_id)
        if not env:
            self.store.register_environment(
                env_id,
                requested_name if isinstance(requested_name, str) else None,
            )
            env = self.store.get_environment(env_id)
            display_name = env.display_name if env else env_id[:8]
        else:
            self.store.heartbeat(env_id)
            display_name = env.display_name
            if isinstance(requested_name, str) and requested_name.strip():
                new_name = self.store.allocate_display_name(requested_name.strip(), env_id)
                if new_name != display_name:
                    display_name = self.store.update_environment_display_name(env_id, new_name)
        self.store.prune_stale_duplicates(env_id)
        claim_work = body.get("claim_work", True)
        if isinstance(claim_work, str):
            claim_work = claim_work.lower() not in ("0", "false", "no")

        work: list[dict] = []
        active_commands: list[dict] = []
        deletions: list[dict] = []
        sync_tasks: list[str] = []
        for task_name in self.store.list_tasks():
            task = self.store.get_task(task_name)
            if not task or task.environment_id != env_id:
                continue
            sync_tasks.append(task_name)
            for fi in self.store.list_feed_items(task_name):
                if fi.delete_status == "delete_pending":
                    deletions.append({"task_name": task_name, "filename": fi.id})
            cmd = None
            if claim_work and task.queued_command and not task.active_command:
                if _environment_online(self.store, env_id) and _task_comms_synced(task):
                    cmd = task.queued_command
                    active = dict(cmd)
                    active["claimed_at"] = time.time()
                    active["started"] = False
                    self.store.update_task(
                        task_name,
                        active_command=active,
                        queued_command=None,
                        create_progress=[],
                        last_command_error=None,
                    )
            elif (
                claim_work
                and task.active_command
                and not task.active_command.get("started")
            ):
                if _environment_online(self.store, env_id) and _task_comms_synced(task):
                    cmd = dict(task.active_command)
            elif task.active_command and task.active_command.get("cancel_requested"):
                cmd = {"command": "cancel", "payload": {}}
            if cmd:
                work.append({"task_name": task_name, "command": cmd})
            if task.active_command and task.active_command.get("started"):
                active_commands.append(
                    {"task_name": task_name, "command": dict(task.active_command)}
                )
        return _json(
            200,
            {
                "environment_id": env_id,
                "display_name": display_name,
                "work": work,
                "active_commands": active_commands,
                "deletions": deletions,
                "sync_tasks": sync_tasks,
                "repos": self.store.get_repos(),
                "bots": self.store.get_bots(),
            },
        )

    def worker_heartbeat(self, event: dict) -> dict:
        body = _parse_body(event) or {}
        env_id = (body.get("environment_id") or "").strip()
        if not env_id:
            return _json(400, {"detail": "environment_id required"})
        if not self.store.get_environment(env_id):
            self.store.register_environment(env_id)
        else:
            self.store.heartbeat(env_id)
        return _no_content()

    def worker_git_token(self, event: dict) -> dict:
        body = _parse_body(event) or {}
        owner = (body.get("owner") or "").strip()
        if not owner:
            return _json(400, {"detail": "owner required"})
        from dev_sdk.bots_config import secret_name_for_owner
        from dev_sdk.create_pr import _get_github_token_boto

        try:
            secret = secret_name_for_owner(self.store.get_bots(), owner)
            token = _get_github_token_boto(secret)
        except Exception as e:
            return _json(400, {"detail": str(e)})
        return _json(200, {"token": token, "expires_in": 3600})

    def worker_upload_log(self, event: dict, task_name: str) -> dict:
        data = _parse_body(event)
        filename = ""
        chunk = b""
        kind = "log"
        if isinstance(data, dict):
            filename = str(data.get("filename") or "")
            kind = str(data.get("kind") or "log")
            chunk_b64 = data.get("chunk_b64")
            if chunk_b64:
                chunk = base64.b64decode(chunk_b64)
        else:
            body = event.get("body") or ""
            if event.get("isBase64Encoded"):
                chunk = base64.b64decode(body)
            elif isinstance(body, str):
                chunk = body.encode("utf-8")
            else:
                chunk = body or b""
        if not filename:
            return _json(400, {"detail": "filename required"})
        if kind not in ("log", "bash"):
            return _json(400, {"detail": "kind must be log or bash"})
        if kind == "log":
            self.store.append_log(task_name, filename, chunk)
            field = "active_log_filename"
            feed_type = "log"
        else:
            self.store.append_stream(task_name, "bash", filename, chunk)
            field = "active_bash_comms_filename"
            feed_type = None
        task = self.store.get_task(task_name)
        if task and task.active_command:
            active = dict(task.active_command)
            active[field] = filename
            self.store.update_task(task_name, active_command=active)
        if feed_type == "log" and not self._feed_has_log(task_name, filename):
            self.store.put_feed_item(
                task_name,
                FeedItem(type="log", id=filename, created_at=time.time(), origin="worker"),
            )
        return _no_content()

    def _feed_has_log(self, task_name: str, filename: str) -> bool:
        return any(
            i.type == "log" and i.id == filename for i in self.store.list_feed_items(task_name)
        )

    def worker_sync(self, event: dict, task_name: str) -> dict:
        body = _parse_body(event) or {}
        push = body.get("push") or []
        for item in push:
            if not isinstance(item, dict):
                continue
            filename = item.get("filename")
            content = item.get("content")
            origin = item.get("origin", "worker")
            if not filename or content is None:
                continue
            if origin == "worker":
                self.store.put_comms(task_name, filename, content, origin=origin)
                self._append_comms_index(task_name, filename)
                if not any(
                    fi.id == filename
                    for fi in self.store.list_feed_items(task_name)
                    if fi.type == "comms"
                ):
                    self.store.put_feed_item(
                        task_name,
                        FeedItem(
                            type="comms",
                            id=filename,
                            created_at=item.get("created_at", time.time()),
                            deletable=item.get("deletable"),
                            origin="worker",
                        ),
                    )
        pull: list[dict] = []
        for fi in self.store.list_feed_items(task_name):
            if fi.origin == "cloud" and fi.type == "comms":
                content = self.store.get_comms(task_name, fi.id)
                if content is not None:
                    pull.append({"filename": fi.id, "content": content, "origin": "cloud"})
        index_raw = self.store.get_comms(task_name, "index.txt")
        if index_raw is not None:
            pull.append({"filename": "index.txt", "content": index_raw, "origin": "cloud"})
        self.store.mark_worker_comms_synced(task_name)
        return _json(200, {"pull": pull})

    def worker_command_start(self, event: dict, task_name: str) -> dict:
        task = self.store.get_task(task_name)
        if not task or not task.active_command:
            return _json(404, {"detail": "No active command"})
        active = dict(task.active_command)
        active["started"] = True
        active["started_at"] = time.time()
        self.store.update_task(task_name, active_command=active)
        return _no_content()

    def worker_command_complete(self, event: dict, task_name: str) -> dict:
        body = _parse_body(event) or {}
        task = self.store.get_task(task_name)
        if not task:
            return _json(404, {"detail": "Task not found"})
        error = body.get("error")
        result = body.get("result") or {}
        updates: dict[str, Any] = {"active_command": None}
        if task.active_command and task.active_command.get("command") == "create-task":
            updates["status"] = "active"
            updates["create_progress"] = []
        if task.active_command and task.active_command.get("command") == "archive":
            updates["status"] = "archived"
            updates["queued_command"] = None
        if task.active_command and task.active_command.get("command") == "unarchive":
            updates["status"] = "active"
        if error:
            updates["active_command"] = None
            updates["queued_command"] = None
            updates["last_command_error"] = str(error)
        else:
            updates["last_command_error"] = None
        if result.get("owner"):
            updates["owner"] = result["owner"]
        if result.get("repo_name"):
            updates["repo_name"] = result["repo_name"]
        if result.get("branch"):
            updates["branch"] = result["branch"]
        self.store.update_task(task_name, **updates)
        return _no_content()

    def worker_command_progress(self, event: dict, task_name: str) -> dict:
        body = _parse_body(event) or {}
        message = body.get("message")
        if message:
            task = self.store.get_task(task_name)
            if task:
                progress = list(task.create_progress or [])
                progress.append(str(message))
                self.store.update_task(task_name, create_progress=progress)
        return _no_content()

    def worker_deletion_ack(self, event: dict) -> dict:
        body = _parse_body(event) or {}
        task_name = body.get("task_name")
        filename = body.get("filename")
        if not task_name or not filename:
            return _json(400, {"detail": "task_name and filename required"})
        self.store.delete_comms(task_name, filename)
        index = [f for f in self._comms_index(task_name) if f != filename]
        self.store.put_comms(task_name, "index.txt", "\n".join(index) + ("\n" if index else ""), origin="cloud")
        self.store.update_feed_item(task_name, filename, delete_status="deleted")
        return _no_content()


_router: Router | None = None


def _http_path(event: dict) -> str:
    return event.get("rawPath") or event.get("requestContext", {}).get("http", {}).get("path", "")


def _http_method(event: dict) -> str:
    return (event.get("requestContext", {}).get("http", {}) or {}).get("method", "GET")


def is_stream_request(event: dict) -> bool:
    return _http_method(event) == "GET" and _http_path(event).endswith("/stream")


def handle_stream_request(event: dict, response_stream: Any, context: Any = None) -> None:
    global _router
    if _router is None:
        _router = Router()
    m = re.match(r"^/tasks/([^/]+)/stream$", _http_path(event))
    if not m:
        metadata = {"statusCode": 404, "headers": {"Content-Type": "text/plain"}}
        try:
            import awslambda

            awslambda.http.set_response_stream(response_stream, metadata)
        except ImportError:
            pass
        response_stream.write(b"Not found")
        return
    task_name = unquote(m.group(1))
    log_offset, bash_offset = _router._stream_offsets(event)
    max_duration = _router._stream_max_duration(event)

    try:
        import awslambda

        awslambda.http.set_response_stream(response_stream, {"statusCode": 200, "headers": SSE_HEADERS})
    except ImportError:
        pass

    def write(chunk: str) -> None:
        response_stream.write(chunk.encode("utf-8"))

    _router.run_task_stream_sse(
        task_name, log_offset, bash_offset, write, max_duration_sec=max_duration
    )


def handle_request(event: dict, context: Any = None) -> dict:
    global _router
    if _router is None:
        _router = Router()
    return _router.dispatch(event, context)
