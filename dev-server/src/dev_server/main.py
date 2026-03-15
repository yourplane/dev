"""FastAPI app: create, list, archive tasks."""

import asyncio
import os
import re
import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field

from dev_sdk.agent_run import (
    AgentRunError,
    run_implement,
    run_plan_implement,
)
from dev_sdk.comms import add_comms, comms_dir, read_index
from dev_sdk.drafts import (
    get_new_task_draft,
    get_task_comment_draft,
    set_new_task_draft,
    set_task_comment_draft,
)
from dev_sdk.feed import LOGS_DIR, read_feed
from dev_sdk.create_pr import CreatePRError, create_pull_request
from dev_sdk.repo_config import load_repos, remove_repo, resolve_repo, save_repos
from dev_sdk.task_manager import ArchivedTaskEntry, TaskManager

SUPPORTED_COMMANDS = ("plan-implement", "implement")

# In-memory registry: task_name -> { "command_id", "thread" }
_command_registry: dict[str, dict] = {}
_command_registry_lock = threading.Lock()


def _run_command_in_thread(
    task_name: str,
    command_id: str,
    task_dir: Path,
    cancel_requested: threading.Event,
) -> None:
    """Run run_plan_implement or run_implement in this thread; clear registry when done."""

    def on_start(stream_log_path: Path) -> None:
        with _command_registry_lock:
            if task_name in _command_registry:
                _command_registry[task_name]["active_log_filename"] = stream_log_path.name

    try:
        if command_id == "plan-implement":
            run_plan_implement(task_dir, on_start=on_start, cancel_event=cancel_requested)
        else:
            run_implement(task_dir, on_start=on_start, cancel_event=cancel_requested)
    except AgentRunError:
        pass
    finally:
        with _command_registry_lock:
            _command_registry.pop(task_name, None)

app = FastAPI(
    title="dev-server",
    description="Task management API: create, list, archive.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _tasks_root() -> Path:
    raw = os.environ.get("DEV_TASKS_DIR")
    if raw:
        return Path(raw).expanduser().resolve()
    return (Path.home() / "tasks").resolve()


def _get_manager() -> TaskManager:
    return TaskManager(tasks_root=_tasks_root())


def _slugify(title: str) -> str:
    """Convert task title to a safe directory name."""
    s = title.lower().strip()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[-\s]+", "-", s)
    return s or "task"


# --- Request/response models ---


class CreateTaskRequest(BaseModel):
    title: str = Field(..., min_length=1, description="Task title")
    repo: str = Field(..., min_length=1, description="Repo URL or shorthand from ~/.config/dev/repos.json")
    comment: str | None = Field(None, description="Optional initial user comment")
    task_name: str | None = Field(None, description="Override task directory name (default: slug of title)")


class CreateTaskResponse(BaseModel):
    task_name: str
    task_dir: str


class ListTasksResponse(BaseModel):
    tasks: list[str]


class ArchiveTaskResponse(BaseModel):
    archived_to: str


class ArchivedTaskEntryModel(BaseModel):
    archived_name: str
    task_name: str
    archived_date: str


class ListArchiveResponse(BaseModel):
    entries: list[ArchivedTaskEntryModel]


class UnarchiveTaskResponse(BaseModel):
    restored_task_name: str


class ListCommsResponse(BaseModel):
    files: list[str]


class PostCommsRequest(BaseModel):
    content: str = Field(..., min_length=1, description="Comment content")


class PostCommsResponse(BaseModel):
    filename: str


class StartCommandRequest(BaseModel):
    command: str = Field(..., description="Command id: plan-implement or implement")


class StartCommandResponse(BaseModel):
    command: str
    status: str = "running"


class CommandStatusResponse(BaseModel):
    active: bool
    command: str | None = None
    active_log_filename: str | None = None


class CreatePRResponse(BaseModel):
    pr_url: str


class FeedEntryModel(BaseModel):
    type: str  # "comms" | "log"
    id: str
    created_at: float


class ListFeedResponse(BaseModel):
    entries: list[FeedEntryModel]


class NewTaskDraftResponse(BaseModel):
    title: str | None = None
    repo: str | None = None
    comment: str | None = None


class NewTaskDraftRequest(BaseModel):
    title: str | None = None
    repo: str | None = None
    comment: str | None = None


class TaskCommentDraftRequest(BaseModel):
    content: str = ""


def _task_dir(task_name: str) -> Path:
    """Return task directory path. Raises HTTPException 404 if task does not exist or path is invalid."""
    if not task_name or "/" in task_name or "\\" in task_name or task_name in (".", ".."):
        raise HTTPException(status_code=404, detail="Invalid task name")
    root = _tasks_root()
    task_dir = (root / task_name).resolve()
    if not task_dir.is_dir() or (root not in task_dir.parents and task_dir != root):
        raise HTTPException(status_code=404, detail=f"Task not found: {task_name}")
    return task_dir


# --- Endpoints ---


@app.get("/")
def root() -> dict:
    return {"service": "dev-server", "docs": "/docs"}


def _shorthand_safe(name: str) -> bool:
    """Shorthand must be non-empty and not look like a URL or path."""
    if not name or not name.strip():
        return False
    s = name.strip()
    if "://" in s or s.startswith("git@") or "/" in s or "\\" in s:
        return False
    return True


def _url_like(value: str) -> bool:
    """True if value looks like a git URL."""
    v = value.strip()
    return "://" in v or v.startswith("git@")


class AddRepoRequest(BaseModel):
    name: str = Field(..., description="Repo shorthand name")
    url: str = Field(..., description="Repo URL (https or git@)")


@app.get("/repos")
def list_repos() -> dict[str, str]:
    """Return repo shorthand -> URL mapping from ~/.config/dev/repos.json."""
    return load_repos()


@app.post("/repos", response_model=dict[str, str])
def add_repo(body: AddRepoRequest) -> dict[str, str]:
    """Add or update a repo shorthand. Returns updated mapping."""
    name = body.name.strip()
    url = body.url.strip()
    if not _shorthand_safe(body.name):
        raise HTTPException(status_code=400, detail="Name must be non-empty and not contain / or look like a URL.")
    if not url:
        raise HTTPException(status_code=400, detail="URL is required.")
    if not _url_like(url):
        raise HTTPException(status_code=400, detail="URL must look like a git URL (e.g. https://... or git@...).")
    repos = load_repos()
    repos[name] = url
    save_repos(repos)
    return load_repos()


@app.delete("/repos/{shorthand}", status_code=204)
def delete_repo(shorthand: str) -> None:
    """Remove a repo shorthand. 404 if not found."""
    if not remove_repo(shorthand):
        raise HTTPException(status_code=404, detail=f"Repo shorthand {shorthand!r} not found.")


@app.get("/drafts/new-task", response_model=NewTaskDraftResponse)
def get_new_task_draft_endpoint() -> NewTaskDraftResponse:
    """Return the new-task draft (title, repo, comment). Empty values if no draft."""
    root = _tasks_root()
    draft = get_new_task_draft(root)
    if draft is None:
        return NewTaskDraftResponse()
    return NewTaskDraftResponse(
        title=draft.get("title") or None,
        repo=draft.get("repo") or None,
        comment=draft.get("comment") or None,
    )


@app.put("/drafts/new-task", status_code=204)
def put_new_task_draft_endpoint(body: NewTaskDraftRequest) -> None:
    """Save or clear the new-task draft. Empty body clears the draft."""
    root = _tasks_root()
    set_new_task_draft(
        root,
        title=body.title or "",
        repo=body.repo or "",
        comment=body.comment or "",
    )


@app.get("/tasks/{task_name}/drafts/comment", response_class=PlainTextResponse)
def get_task_comment_draft_endpoint(task_name: str) -> str:
    """Return the comment draft for the task. Empty string if none."""
    task_dir = _task_dir(task_name)
    return get_task_comment_draft(task_dir)


@app.put("/tasks/{task_name}/drafts/comment", status_code=204)
def put_task_comment_draft_endpoint(task_name: str, body: TaskCommentDraftRequest) -> None:
    """Save or clear the comment draft for the task. Empty content clears it."""
    task_dir = _task_dir(task_name)
    set_task_comment_draft(task_dir, body.content or "")


@app.get("/tasks", response_model=ListTasksResponse)
def list_tasks() -> ListTasksResponse:
    manager = _get_manager()
    return ListTasksResponse(tasks=manager.list_tasks())


@app.post("/tasks", response_model=CreateTaskResponse, status_code=201)
def create_task(body: CreateTaskRequest) -> CreateTaskResponse:
    manager = _get_manager()
    task_name = body.task_name if body.task_name is not None else _slugify(body.title)
    try:
        repo_url = resolve_repo(body.repo)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    progress: list[str] = []

    def on_progress(msg: str) -> None:
        progress.append(msg)

    try:
        manager.start_task(
            title=body.title,
            task_name=task_name,
            comment=body.comment,
            repo_url=repo_url,
            on_progress=on_progress,
        )
    except FileExistsError as e:
        raise HTTPException(status_code=409, detail=f"Task already exists: {task_name}")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    task_dir = _tasks_root() / task_name
    return CreateTaskResponse(task_name=task_name, task_dir=str(task_dir))


@app.post("/tasks/{task_name}/archive", response_model=ArchiveTaskResponse)
def archive_task(task_name: str) -> ArchiveTaskResponse:
    manager = _get_manager()
    try:
        dest = manager.archive_task(task_name)
        return ArchiveTaskResponse(archived_to=str(dest))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/archive", response_model=ListArchiveResponse)
def list_archive() -> ListArchiveResponse:
    """List archived tasks (grouped by date on the client)."""
    manager = _get_manager()
    entries = manager.list_archived_tasks()
    return ListArchiveResponse(
        entries=[
            ArchivedTaskEntryModel(
                archived_name=e.archived_name,
                task_name=e.task_name,
                archived_date=e.archived_date,
            )
            for e in entries
        ]
    )


@app.post("/archive/{archived_name}/unarchive", response_model=UnarchiveTaskResponse)
def unarchive_task(archived_name: str) -> UnarchiveTaskResponse:
    """Move archived task back to task dir and strip -date-random suffix."""
    if not archived_name or ".." in archived_name or "/" in archived_name or "\\" in archived_name:
        raise HTTPException(status_code=404, detail="Invalid archive name")
    manager = _get_manager()
    try:
        dest = manager.unarchive_task(archived_name)
        return UnarchiveTaskResponse(restored_task_name=dest.name)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except FileExistsError as e:
        raise HTTPException(status_code=409, detail=str(e))


@app.get("/tasks/{task_name}/comms", response_model=ListCommsResponse)
def list_task_comms(task_name: str) -> ListCommsResponse:
    """List comms filenames for a task in index order."""
    task_dir = _task_dir(task_name)
    files = read_index(task_dir)
    return ListCommsResponse(files=files)


@app.post("/tasks/{task_name}/comms", response_model=PostCommsResponse, status_code=201)
def post_task_comms(task_name: str, body: PostCommsRequest) -> PostCommsResponse:
    """Append a user comment to the task comms. Returns the new filename."""
    task_dir = _task_dir(task_name)
    path = add_comms(task_dir, "user", body.content.strip())
    return PostCommsResponse(filename=path.name)


@app.get("/tasks/{task_name}/comms/{filename}", response_class=PlainTextResponse)
def get_task_comms_file(task_name: str, filename: str) -> str:
    """Return raw content of a single comms file. Plain text."""
    if not filename or "/" in filename or "\\" in filename or filename in (".", ".."):
        raise HTTPException(status_code=404, detail="Invalid filename")
    task_dir = _task_dir(task_name)
    cdir = comms_dir(task_dir)
    path = cdir / filename
    if not path.is_file() or path.resolve().parent != cdir.resolve():
        raise HTTPException(status_code=404, detail="File not found")
    return path.read_text(encoding="utf-8")


@app.get("/tasks/{task_name}/feed", response_model=ListFeedResponse)
def list_task_feed(task_name: str, after: float | None = None) -> ListFeedResponse:
    """List feed entries (comms + agent logs) sorted by file creation date.
    If `after` is provided, return only entries with created_at > after (for incremental updates).
    """
    task_dir = _task_dir(task_name)
    entries = read_feed(task_dir)
    if after is not None:
        entries = [e for e in entries if e.created_at > after]
    return ListFeedResponse(
        entries=[FeedEntryModel(type=e.type, id=e.id, created_at=e.created_at) for e in entries]
    )


def _sse_format(data: str) -> str:
    """Format a string as SSE data (each line prefixed with 'data: '), ending with blank line."""
    if not data:
        return ""
    return "".join(f"data: {line}\n" for line in data.splitlines()) + "\n\n"


async def _stream_active_log_gen(task_name: str, task_dir: Path, logs_path: Path, filename: str):
    """Async generator that tails the active log file and yields SSE chunks until command ends."""
    path = logs_path / filename
    if not path.is_file() or path.resolve().parent != logs_path.resolve():
        return
    position = 0
    while True:
        with _command_registry_lock:
            entry = _command_registry.get(task_name)
            if not entry or entry.get("active_log_filename") != filename:
                yield _sse_format("[stream ended]\n")
                return
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                f.seek(position)
                chunk = f.read()
                position = f.tell()
        except OSError:
            await asyncio.sleep(0.3)
            continue
        if chunk:
            yield _sse_format(chunk)
        await asyncio.sleep(0.3)


@app.get("/tasks/{task_name}/logs/stream")
def stream_task_log(task_name: str):
    """Stream the active log file for the task via Server-Sent Events. 404 if no command is running."""
    task_dir = _task_dir(task_name)
    logs_path = task_dir / LOGS_DIR
    with _command_registry_lock:
        entry = _command_registry.get(task_name)
        if not entry:
            raise HTTPException(status_code=404, detail="No command is running for this task.")
        filename = entry.get("active_log_filename")
        if not filename or "/" in filename or "\\" in filename or filename in (".", ".."):
            raise HTTPException(status_code=404, detail="No active log file for this task.")
    path = logs_path / filename
    if not path.is_file() or path.resolve().parent != logs_path.resolve():
        raise HTTPException(status_code=404, detail="Active log file not found.")
    return StreamingResponse(
        _stream_active_log_gen(task_name, task_dir, logs_path, filename),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/tasks/{task_name}/logs/{filename}", response_class=PlainTextResponse)
def get_task_log_file(task_name: str, filename: str) -> str:
    """Return raw content of a single agent log file under task .logs directory."""
    if not filename or "/" in filename or "\\" in filename or filename in (".", ".."):
        raise HTTPException(status_code=404, detail="Invalid filename")
    task_dir = _task_dir(task_name)
    logs_path = task_dir / LOGS_DIR
    path = logs_path / filename
    if not path.is_file() or path.resolve().parent != logs_path.resolve():
        raise HTTPException(status_code=404, detail="File not found")
    return path.read_text(encoding="utf-8", errors="replace")


@app.post("/tasks/{task_name}/commands", response_model=StartCommandResponse, status_code=201)
def start_task_command(task_name: str, body: StartCommandRequest) -> StartCommandResponse:
    """Start an async command (plan-implement or implement) for the task. 409 if one is already running."""
    if body.command not in SUPPORTED_COMMANDS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported command: {body.command!r}. Supported: {list(SUPPORTED_COMMANDS)}",
        )
    task_dir = _task_dir(task_name)
    if "DEV_TASKS_DIR" not in os.environ:
        os.environ["DEV_TASKS_DIR"] = str(_tasks_root())
    with _command_registry_lock:
        if task_name in _command_registry:
            raise HTTPException(
                status_code=409,
                detail="A command is already running for this task.",
            )
        cancel_requested = threading.Event()
        thread = threading.Thread(
            target=_run_command_in_thread,
            args=(task_name, body.command, task_dir, cancel_requested),
            daemon=True,
        )
        _command_registry[task_name] = {
            "command_id": body.command,
            "thread": thread,
            "cancel_requested": cancel_requested,
        }
        thread.start()
    return StartCommandResponse(command=body.command)


@app.get("/tasks/{task_name}/commands", response_model=CommandStatusResponse)
def get_task_command_status(task_name: str) -> CommandStatusResponse:
    """Return whether a command is currently running for the task."""
    _task_dir(task_name)
    with _command_registry_lock:
        entry = _command_registry.get(task_name)
    if entry is None:
        return CommandStatusResponse(active=False, command=None, active_log_filename=None)
    return CommandStatusResponse(
        active=True,
        command=entry["command_id"],
        active_log_filename=entry.get("active_log_filename"),
    )


@app.post("/tasks/{task_name}/commands/cancel", status_code=204)
def cancel_task_command(task_name: str) -> None:
    """Request cancellation of the running command for the task. No-op if no command is running."""
    _task_dir(task_name)
    with _command_registry_lock:
        entry = _command_registry.get(task_name)
    if entry is None:
        raise HTTPException(
            status_code=404,
            detail="No command is running for this task.",
        )
    entry["cancel_requested"].set()


@app.post("/tasks/{task_name}/create-pr", response_model=CreatePRResponse)
def create_task_pr(task_name: str) -> CreatePRResponse:
    """Create a pull request for the task's repo (current branch to main). Returns PR URL."""
    task_dir = _task_dir(task_name)
    try:
        pr_url = create_pull_request(task_dir, allow_dirty=False)
        return CreatePRResponse(pr_url=pr_url)
    except CreatePRError as e:
        raise HTTPException(status_code=422, detail=str(e))
