"""FastAPI app: create, list, archive tasks."""

import asyncio
import io
import json
import logging
import os
import queue
import re
import signal
import subprocess
import threading
import time
import zipfile
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

from dev_sdk.agent_run import (
    AgentRunError,
    run_implement,
    run_do,
    run_plan_implement,
)
from dev_sdk.comms import (
    add_comms,
    bash_comms_input_header,
    begin_streaming_bash_comms,
    comms_dir,
    index_path,
    read_index,
    remove_comms,
)
from dev_sdk.drafts import (
    delete_new_task_draft,
    get_new_task_draft,
    get_task_bash_draft,
    get_task_comment_draft,
    set_new_task_draft,
    set_task_bash_draft,
    set_task_comment_draft,
)
from dev_sdk.feed import LOGS_DIR, read_feed
from dev_sdk.create_pr import (
    CreatePRError,
    create_pull_request,
    find_existing_pull_request,
    pull_pr_comments,
)
from dev_sdk.repo_config import load_repos, remove_repo, resolve_repo, save_repos
from dev_sdk.task_manager import TaskManager

SUPPORTED_COMMANDS = ("plan-implement", "implement", "do", "bash")
logger = logging.getLogger("dev_server")

_DEFAULT_BASH_MAX_OUTPUT_BYTES = 2_000_000
_DEFAULT_BASH_TIMEOUT_SEC = 3600.0

_bash_comms_append_lock = threading.Lock()


def _append_bytes_to_bash_comms(path: Path, data: bytes) -> None:
    with _bash_comms_append_lock:
        with open(path, "ab") as f:
            f.write(data)


def _append_bash_comms_footer(
    path: Path,
    *,
    truncated: bool,
    cancelled: bool,
    timed_out: bool,
    exit_code: int | None,
    timeout_sec: float,
    interrupted: bool = False,
) -> None:
    with _bash_comms_append_lock:
        with open(path, "a", encoding="utf-8") as f:
            if truncated:
                f.write("\n[… output truncated (DEV_BASH_MAX_OUTPUT_BYTES) …]")
            f.write("\n---\n")
            if interrupted:
                f.write("Interrupted.\n")
            elif cancelled:
                f.write("Cancelled by user.\n")
            elif timed_out:
                f.write(f"Timed out after {timeout_sec:g}s (DEV_BASH_TIMEOUT_SEC).\n")
            else:
                f.write(f"Exit code: {exit_code if exit_code is not None else 'unknown'}\n")


def _terminate_process_group(proc: subprocess.Popen, *, use_kill: bool = False) -> None:
    """Send SIGTERM (or SIGKILL) to the child's process group."""
    try:
        sig = signal.SIGKILL if use_kill else signal.SIGTERM
        os.killpg(proc.pid, sig)
    except (ProcessLookupError, PermissionError):
        pass


def _popen_bash_for_streaming(shell_command: str, *, cwd: str) -> subprocess.Popen[str]:
    """
    Spawn `bash -c` with stdout/stderr merged to a PIPE.

    Uses ``bufsize=0`` so Python does not wrap the pipe in a large BufferedReader
    (default ``bufsize`` blocks ``read()`` until ~8KiB accumulates or the pipe closes).

    Without a TTY, libc stdio defaults to fully buffered stdout on the child; prefer
    coreutils ``stdbuf`` line buffering when available so programs flush often enough.
    Set DEV_BASH_NO_STDBUF=1 to skip ``stdbuf`` (e.g. minimal images without coreutils).
    """
    use_stdbuf = os.environ.get("DEV_BASH_NO_STDBUF", "").strip().lower() not in ("1", "true", "yes")
    argv_candidates: list[list[str]] = []
    if use_stdbuf:
        argv_candidates.append(["stdbuf", "-oL", "-eL", "bash", "-c", shell_command])
    argv_candidates.append(["bash", "-c", shell_command])
    last_fe: FileNotFoundError | None = None
    for argv in argv_candidates:
        try:
            return subprocess.Popen(
                argv,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
                bufsize=0,
            )
        except FileNotFoundError as e:
            last_fe = e
            continue
    assert last_fe is not None
    raise last_fe


def _run_bash_in_thread(
    task_name: str,
    task_dir: Path,
    cancel_requested: threading.Event,
    shell_command: str,
) -> None:
    """Run bash -c in task_dir; stream stdout into comms file; append footer; clear registry when done."""
    try:
        max_bytes = int(os.environ.get("DEV_BASH_MAX_OUTPUT_BYTES", str(_DEFAULT_BASH_MAX_OUTPUT_BYTES)))
    except ValueError:
        max_bytes = _DEFAULT_BASH_MAX_OUTPUT_BYTES
    try:
        timeout_sec = float(os.environ.get("DEV_BASH_TIMEOUT_SEC", str(_DEFAULT_BASH_TIMEOUT_SEC)))
    except ValueError:
        timeout_sec = _DEFAULT_BASH_TIMEOUT_SEC

    try:
        proc = _popen_bash_for_streaming(shell_command, cwd=str(task_dir))
    except OSError as exc:
        logger.warning("bash spawn failed for task %s: %s", task_name, exc)
        try:
            add_comms(
                task_dir,
                "user",
                f"{bash_comms_input_header(shell_command)}\n---\nFailed to start process: {exc}\n",
                kind="bash",
            )
        except OSError:
            logger.exception("failed to write bash error comms for task %s", task_name)
        finally:
            with _command_registry_lock:
                _command_registry.pop(task_name, None)
        return

    path: Path | None = None
    footer_written = False
    truncated = False
    cancelled = False
    timed_out = False
    start = time.monotonic()
    trunc_cell: list[bool] = [False]
    stdout = proc.stdout
    assert stdout is not None

    try:
        path = begin_streaming_bash_comms(task_dir, shell_command)
        with _command_registry_lock:
            if task_name in _command_registry:
                _command_registry[task_name]["active_bash_comms_filename"] = path.name

        collected = bytearray()

        def read_stdout() -> None:
            while True:
                chunk = stdout.read(4096)
                if not chunk:
                    break
                room = max_bytes - len(collected)
                if room <= 0:
                    trunc_cell[0] = True
                    break
                take = min(len(chunk), room)
                portion = chunk[:take]
                collected.extend(portion)
                _append_bytes_to_bash_comms(path, portion)
                if take < len(chunk):
                    trunc_cell[0] = True
                    break

        reader = threading.Thread(target=read_stdout, daemon=True)
        reader.start()

        try:
            while proc.poll() is None:
                if cancel_requested.is_set():
                    cancelled = True
                    _terminate_process_group(proc, use_kill=False)
                    break
                if timeout_sec > 0 and (time.monotonic() - start) > timeout_sec:
                    timed_out = True
                    _terminate_process_group(proc, use_kill=True)
                    break
                if trunc_cell[0] or len(collected) >= max_bytes:
                    truncated = True
                    _terminate_process_group(proc, use_kill=True)
                    break
                time.sleep(0.1)
            reader.join(timeout=30.0)
            if proc.poll() is None:
                _terminate_process_group(proc, use_kill=True)
                proc.wait(timeout=15)
            else:
                proc.wait(timeout=15)
        finally:
            try:
                stdout.close()
            except OSError:
                pass

        truncated = truncated or trunc_cell[0]
        exit_code = proc.returncode
        _append_bash_comms_footer(
            path,
            truncated=truncated,
            cancelled=cancelled,
            timed_out=timed_out,
            exit_code=exit_code,
            timeout_sec=timeout_sec,
        )
        footer_written = True
    except Exception:
        logger.exception("bash run failed for task %s", task_name)
        if path is not None and not footer_written:
            try:
                _append_bash_comms_footer(
                    path,
                    truncated=False,
                    cancelled=False,
                    timed_out=False,
                    exit_code=None,
                    timeout_sec=timeout_sec,
                    interrupted=True,
                )
                footer_written = True
            except OSError:
                logger.exception("failed to write bash interrupted footer for task %s", task_name)
    finally:
        if path is not None and not footer_written:
            try:
                _append_bash_comms_footer(
                    path,
                    truncated=False,
                    cancelled=False,
                    timed_out=False,
                    exit_code=None,
                    timeout_sec=timeout_sec,
                    interrupted=True,
                )
            except OSError:
                logger.exception("failed to finalize bash comms for task %s", task_name)
        with _command_registry_lock:
            _command_registry.pop(task_name, None)

# In-memory registry: task_name -> { "command_id", "thread" }
_command_registry: dict[str, dict] = {}
_command_registry_lock = threading.Lock()
_last_command_error: dict[str, str] = {}


def _run_command_in_thread(
    task_name: str,
    command_id: str,
    task_dir: Path,
    cancel_requested: threading.Event,
    prompt: str | None,
) -> None:
    """Run run_plan_implement or run_implement in this thread; clear registry when done."""

    def on_start(stream_log_path: Path) -> None:
        with _command_registry_lock:
            if task_name in _command_registry:
                _command_registry[task_name]["active_log_filename"] = stream_log_path.name

    try:
        if command_id == "plan-implement":
            run_plan_implement(task_dir, on_start=on_start, cancel_event=cancel_requested)
        elif command_id == "implement":
            run_implement(task_dir, on_start=on_start, cancel_event=cancel_requested)
        else:
            # "do" command
            if prompt is None or not prompt.strip():
                # Defensive: request validation should prevent this.
                raise AgentRunError("Missing prompt for do command.")
            run_do(task_dir, prompt=prompt, on_start=on_start, cancel_event=cancel_requested)
    except AgentRunError as e:
        with _command_registry_lock:
            _last_command_error[task_name] = str(e)
    else:
        with _command_registry_lock:
            _last_command_error.pop(task_name, None)
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
    repo: str | None = Field(
        None,
        description="Repo URL or shorthand from ~/.config/dev/repos.json; omit, null, or blank for no clone",
    )
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
    archived_at: str
    last_modified_at: str


class ListArchiveResponse(BaseModel):
    entries: list[ArchivedTaskEntryModel]
    total: int
    next_offset: int | None = None


class UnarchiveTaskResponse(BaseModel):
    restored_task_name: str


class CopyFromArchiveRequest(BaseModel):
    task_name: str | None = Field(None, description="Override task name (default: base name from archive)")


class CopyFromArchiveResponse(BaseModel):
    task_name: str
    task_dir: str


class ListCommsResponse(BaseModel):
    files: list[str]


class PostCommsRequest(BaseModel):
    content: str = Field(..., min_length=1, description="Comment content")


class PostCommsResponse(BaseModel):
    filename: str


class StartCommandRequest(BaseModel):
    command: str = Field(..., description="Command id: plan-implement, implement, do, or bash")
    prompt: str | None = Field(
        None,
        description="For `do`: agent prompt. For `bash`: shell command string passed to `bash -c`.",
    )


class StartCommandResponse(BaseModel):
    command: str
    status: str = "running"


class CommandStatusResponse(BaseModel):
    active: bool
    command: str | None = None
    active_log_filename: str | None = None
    active_bash_comms_filename: str | None = None
    command_error: str | None = None


class CreatePRResponse(BaseModel):
    pr_url: str


class GetTaskPrResponse(BaseModel):
    pr_url: str | None = None


class PullPrCommentsResponse(BaseModel):
    pr_url: str
    new_comments_count: int
    comms_filename: str | None = None


class FeedEntryModel(BaseModel):
    type: str  # "comms" | "log"
    id: str
    created_at: float
    deletable: bool | None = None  # comms: DELETE allowed; logs: null


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


class TaskWorkspaceResponse(BaseModel):
    repo_label: str | None = None


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
    repo_val = draft["repo"] if "repo" in draft else None
    return NewTaskDraftResponse(
        title=draft.get("title") or None,
        repo=repo_val,
        comment=draft.get("comment") or None,
    )


@app.put("/drafts/new-task", status_code=204)
def put_new_task_draft_endpoint(body: NewTaskDraftRequest) -> None:
    """Save or clear the new-task draft. Empty JSON object ``{}`` clears the draft."""
    root = _tasks_root()
    submitted = body.model_dump(exclude_unset=True)
    if not submitted:
        delete_new_task_draft(root)
        return
    title = body.title or ""
    comment = body.comment or ""
    repo = body.repo if "repo" in submitted else ""
    set_new_task_draft(root, title=title, repo=repo, comment=comment)


@app.get("/tasks/{task_name}/drafts/comment", response_class=PlainTextResponse)
def get_task_comment_draft_endpoint(task_name: str) -> str:
    """Return the comment draft for the task. Empty string if none. Draft stored in server .drafts, not task dir."""
    _task_dir(task_name)  # validate task exists
    return get_task_comment_draft(_tasks_root(), task_name)


@app.put("/tasks/{task_name}/drafts/comment", status_code=204)
def put_task_comment_draft_endpoint(task_name: str, body: TaskCommentDraftRequest) -> None:
    """Save or clear the comment draft for the task. Empty content clears it. Draft stored in server .drafts."""
    _task_dir(task_name)  # validate task exists
    set_task_comment_draft(_tasks_root(), task_name, body.content or "")


@app.get("/tasks/{task_name}/drafts/bash", response_class=PlainTextResponse)
def get_task_bash_draft_endpoint(task_name: str) -> str:
    """Return the bash-input draft for the task (separate from comment draft). Stored in server .drafts."""
    _task_dir(task_name)
    return get_task_bash_draft(_tasks_root(), task_name)


@app.put("/tasks/{task_name}/drafts/bash", status_code=204)
def put_task_bash_draft_endpoint(task_name: str, body: TaskCommentDraftRequest) -> None:
    """Save or clear the bash-input draft. Empty content clears it."""
    _task_dir(task_name)
    set_task_bash_draft(_tasks_root(), task_name, body.content or "")


@app.get("/tasks", response_model=ListTasksResponse)
def list_tasks() -> ListTasksResponse:
    manager = _get_manager()
    return ListTasksResponse(tasks=manager.list_tasks())


@app.get("/tasks/{task_name}/workspace", response_model=TaskWorkspaceResponse)
def get_task_workspace(task_name: str) -> TaskWorkspaceResponse:
    """Return a label for the nested clone (e.g. origin URL), or null if there is none."""
    task_dir = _task_dir(task_name)
    label = TaskManager.describe_clone_layout(task_dir)
    return TaskWorkspaceResponse(repo_label=label)


@app.post("/tasks")
def create_task(body: CreateTaskRequest) -> StreamingResponse:
    """Create a task; streams NDJSON lines as work progresses (same messages as CLI `on_progress`)."""
    manager = _get_manager()
    task_name = body.task_name if body.task_name is not None else _slugify(body.title)
    will_clone = body.repo is not None and bool(str(body.repo).strip())
    repo_url: str | None = None
    if will_clone:
        try:
            repo_url = resolve_repo(str(body.repo).strip())
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    tasks_root = _tasks_root()

    def ndjson_events():
        q: queue.Queue = queue.Queue()

        def worker() -> None:
            try:
                manager.start_task(
                    title=body.title,
                    task_name=task_name,
                    comment=body.comment,
                    repo_url=repo_url,
                    on_progress=lambda msg: q.put(("progress", msg)),
                )
                delete_new_task_draft(tasks_root)
                task_dir = tasks_root / task_name
                q.put(("complete", str(task_dir)))
            except FileExistsError:
                q.put(("error", 409, f"Task already exists: {task_name}"))
            except ValueError as e:
                q.put(("error", 400, str(e)))
            except Exception as e:
                q.put(("error", 500, str(e)))

        threading.Thread(target=worker, daemon=True).start()

        while True:
            item = q.get()
            if item[0] == "progress":
                yield json.dumps({"type": "progress", "message": item[1]}) + "\n"
            elif item[0] == "complete":
                task_dir = item[1]
                yield json.dumps(
                    {
                        "type": "complete",
                        "task_name": task_name,
                        "task_dir": task_dir,
                    }
                ) + "\n"
                break
            elif item[0] == "error":
                _, status_code, detail = item
                yield json.dumps({"type": "error", "detail": detail, "status": status_code}) + "\n"
                break

    return StreamingResponse(
        ndjson_events(),
        media_type="application/x-ndjson",
        status_code=200,
    )


@app.post("/tasks/{task_name}/archive", response_model=ArchiveTaskResponse)
def archive_task(task_name: str) -> ArchiveTaskResponse:
    manager = _get_manager()
    try:
        dest = manager.archive_task(task_name)
        return ArchiveTaskResponse(archived_to=str(dest))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/archive", response_model=ListArchiveResponse)
def list_archive(limit: int = 50, offset: int = 0) -> ListArchiveResponse:
    """List archived tasks in newest-first order, with optional pagination."""
    started = time.perf_counter()
    if limit <= 0:
        raise HTTPException(status_code=400, detail="limit must be greater than 0")
    if offset < 0:
        raise HTTPException(status_code=400, detail="offset must be >= 0")
    manager = _get_manager()
    all_entries = manager.list_archived_tasks()
    total = len(all_entries)
    page_entries = all_entries[offset : offset + limit]
    next_offset = offset + limit if (offset + limit) < total else None
    response = ListArchiveResponse(
        entries=[
            ArchivedTaskEntryModel(
                archived_name=e.archived_name,
                task_name=e.task_name,
                archived_date=e.archived_date,
                archived_at=e.archived_at,
                last_modified_at=e.last_modified_at,
            )
            for e in page_entries
        ],
        total=total,
        next_offset=next_offset,
    )
    elapsed_ms = (time.perf_counter() - started) * 1000
    logger.info(
        "archive_list limit=%d offset=%d returned=%d total=%d elapsed_ms=%.2f",
        limit,
        offset,
        len(response.entries),
        total,
        elapsed_ms,
    )
    return response


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


@app.post("/archive/{archived_name}/copy", response_model=CopyFromArchiveResponse, status_code=201)
def copy_from_archive(
    archived_name: str, body: CopyFromArchiveRequest | None = Body(None)
) -> CopyFromArchiveResponse:
    """Create a new task from an archived task: same name and comms, new agent chat, no logs."""
    if not archived_name or ".." in archived_name or "/" in archived_name or "\\" in archived_name:
        raise HTTPException(status_code=404, detail="Invalid archive name")
    manager = _get_manager()
    task_name_override = body.task_name if body and body.task_name else None
    try:
        dest = manager.copy_task_from_archive(archived_name, task_name_override=task_name_override)
        return CopyFromArchiveResponse(task_name=dest.name, task_dir=str(dest))
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
    set_task_comment_draft(_tasks_root(), task_name, "")
    return PostCommsResponse(filename=path.name)


@app.get("/tasks/{task_name}/comms/download", response_class=Response)
def get_task_comms_download(task_name: str) -> Response:
    """Download all task comms (no agent logs) as a zip file. 404 if no comms."""
    task_dir = _task_dir(task_name)
    cdir = comms_dir(task_dir)
    files = read_index(task_dir)
    if not files:
        raise HTTPException(status_code=404, detail="No comms to download")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        idx = index_path(task_dir)
        if idx.exists():
            zf.writestr("index.txt", idx.read_text(encoding="utf-8"))
        for filename in files:
            path = cdir / filename
            if path.is_file() and path.resolve().parent == cdir.resolve():
                zf.writestr(filename, path.read_text(encoding="utf-8"))
    buf.seek(0)
    safe_name = re.sub(r"[^\w\-]", "-", task_name).strip("-") or "comms"
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{safe_name}-comms.zip"'
        },
    )


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


@app.delete("/tasks/{task_name}/comms/{filename}", status_code=204)
def delete_task_comms_file(task_name: str, filename: str) -> None:
    """Remove a comms file and its index entry. Blocked if agent logs exist and the comm is not after them."""
    if not filename or "/" in filename or "\\" in filename or filename.strip() in ("", ".", ".."):
        raise HTTPException(status_code=404, detail="Invalid filename")
    task_dir = _task_dir(task_name)
    try:
        remove_comms(task_dir, filename)
    except ValueError as e:
        if "cannot remove comms" in str(e).lower():
            raise HTTPException(status_code=400, detail=str(e)) from e
        raise HTTPException(status_code=404, detail=str(e)) from e


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
        entries=[
            FeedEntryModel(type=e.type, id=e.id, created_at=e.created_at, deletable=e.deletable)
            for e in entries
        ]
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
    if body.command == "do":
        if body.prompt is None or not body.prompt.strip():
            raise HTTPException(status_code=400, detail="prompt is required for do command")
    if body.command == "bash":
        if body.prompt is None or not body.prompt.strip():
            raise HTTPException(
                status_code=400,
                detail="prompt is required for bash command (shell command text)",
            )
    task_dir = _task_dir(task_name)
    if body.command == "implement" and TaskManager.describe_clone_layout(task_dir) is None:
        raise HTTPException(
            status_code=400,
            detail="This task has no cloned repository under the task root; the Implement command is not available.",
        )
    if body.command == "do":
        set_task_comment_draft(_tasks_root(), task_name, "")
    if "DEV_TASKS_DIR" not in os.environ:
        os.environ["DEV_TASKS_DIR"] = str(_tasks_root())
    with _command_registry_lock:
        if task_name in _command_registry:
            raise HTTPException(
                status_code=409,
                detail="A command is already running for this task.",
            )
        cancel_requested = threading.Event()
        if body.command == "bash":
            thread = threading.Thread(
                target=_run_bash_in_thread,
                args=(task_name, task_dir, cancel_requested, body.prompt.strip()),
                daemon=True,
            )
        else:
            thread = threading.Thread(
                target=_run_command_in_thread,
                args=(task_name, body.command, task_dir, cancel_requested, body.prompt),
                daemon=True,
            )
        _command_registry[task_name] = {
            "command_id": body.command,
            "thread": thread,
            "cancel_requested": cancel_requested,
        }
        _last_command_error.pop(task_name, None)
        thread.start()
    return StartCommandResponse(command=body.command)


@app.get("/tasks/{task_name}/commands", response_model=CommandStatusResponse)
def get_task_command_status(task_name: str) -> CommandStatusResponse:
    """Return whether a command is currently running for the task."""
    _task_dir(task_name)
    with _command_registry_lock:
        entry = _command_registry.get(task_name)
        last_error = _last_command_error.get(task_name)
    if entry is None:
        return CommandStatusResponse(
            active=False,
            command=None,
            active_log_filename=None,
            active_bash_comms_filename=None,
            command_error=last_error,
        )
    return CommandStatusResponse(
        active=True,
        command=entry["command_id"],
        active_log_filename=entry.get("active_log_filename"),
        active_bash_comms_filename=entry.get("active_bash_comms_filename"),
        command_error=None,
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


@app.get("/tasks/{task_name}/pr", response_model=GetTaskPrResponse)
def get_task_pr(task_name: str) -> GetTaskPrResponse:
    """Return the existing pull request URL for the task, if any."""
    task_dir = _task_dir(task_name)
    if TaskManager.describe_clone_layout(task_dir) is None:
        return GetTaskPrResponse(pr_url=None)
    try:
        pr_url = find_existing_pull_request(task_dir)
    except CreatePRError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return GetTaskPrResponse(pr_url=pr_url)


@app.post("/tasks/{task_name}/pull-pr-comments", response_model=PullPrCommentsResponse)
def pull_task_pr_comments(task_name: str) -> PullPrCommentsResponse:
    """Pull new PR comments into task comms. Returns count and new comms filename when written."""
    task_dir = _task_dir(task_name)
    try:
        pr_url, count, filename = pull_pr_comments(task_dir)
        return PullPrCommentsResponse(pr_url=pr_url, new_comments_count=count, comms_filename=filename)
    except CreatePRError as e:
        raise HTTPException(status_code=422, detail=str(e))
