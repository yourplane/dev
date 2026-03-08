"""FastAPI app: create, list, archive tasks."""

import os
import re
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from dev_sdk.repo_config import resolve_repo
from dev_sdk.task_manager import TaskManager

app = FastAPI(
    title="dev-server",
    description="Task management API: create, list, archive.",
    version="0.1.0",
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


# --- Endpoints ---


@app.get("/")
def root() -> dict:
    return {"service": "dev-server", "docs": "/docs"}


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
