"""FastAPI app: create, list, archive tasks."""

import os
import re
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from dev_sdk.comms import add_comms, comms_dir, read_index
from dev_sdk.repo_config import load_repos, resolve_repo
from dev_sdk.task_manager import TaskManager

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


class ListCommsResponse(BaseModel):
    files: list[str]


class PostCommsRequest(BaseModel):
    content: str = Field(..., min_length=1, description="Comment content")


class PostCommsResponse(BaseModel):
    filename: str


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


@app.get("/repos")
def list_repos() -> dict[str, str]:
    """Return repo shorthand -> URL mapping from ~/.config/dev/repos.json."""
    return load_repos()


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
