"""Task metadata store abstraction."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from dev_sdk.task_manager import ArchivedTaskEntry, TaskManager


@dataclass
class TaskRecord:
    task_name: str
    environment_id: str | None = None
    title: str = ""
    repo: str | None = None
    owner: str | None = None
    repo_name: str | None = None
    branch: str | None = None
    status: str = "active"
    active_command: dict | None = None
    queued_command: dict | None = None


class TaskStore(Protocol):
    def list_tasks(self) -> list[str]: ...

    def get_task(self, task_name: str) -> TaskRecord | None: ...

    def create_task_record(self, record: TaskRecord) -> None: ...

    def update_task(self, task_name: str, **fields: object) -> None: ...

    def delete_task(self, task_name: str) -> None: ...


class LocalFilesystemTaskStore:
    """Task list derived from tasks root directory names."""

    def __init__(self, tasks_root: Path) -> None:
        self._tasks_root = Path(tasks_root)
        self._manager = TaskManager(self._tasks_root)

    def list_tasks(self) -> list[str]:
        if not self._tasks_root.is_dir():
            return []
        return sorted(
            p.name
            for p in self._tasks_root.iterdir()
            if p.is_dir() and not p.name.startswith(".")
        )

    def get_task(self, task_name: str) -> TaskRecord | None:
        task_dir = self._tasks_root / task_name
        if not task_dir.is_dir():
            return None
        return TaskRecord(task_name=task_name, title=task_name)

    def create_task_record(self, record: TaskRecord) -> None:
        pass  # directory created by TaskManager.start_task

    def update_task(self, task_name: str, **fields: object) -> None:
        pass

    def delete_task(self, task_name: str) -> None:
        pass

    def list_archive(self, *, limit: int, offset: int) -> tuple[list[ArchivedTaskEntry], int]:
        all_entries = self._manager.list_archived_tasks()
        total = len(all_entries)
        return all_entries[offset : offset + limit], total
