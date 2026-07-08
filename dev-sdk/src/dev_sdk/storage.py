"""Storage backend abstraction for task filesystem operations."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from dev_sdk import comms as comms_mod
from dev_sdk import drafts as drafts_mod


class StorageBackend(Protocol):
    """Task-local storage: comms, logs, drafts on the worker filesystem."""

    @property
    def tasks_root(self) -> Path: ...

    def task_dir(self, task_name: str) -> Path: ...

    def comms_dir(self, task_name: str) -> Path: ...

    def read_comms_index(self, task_name: str) -> list[str]: ...

    def read_comms_file(self, task_name: str, filename: str) -> str: ...

    def write_comms_file(self, task_name: str, filename: str, content: str) -> None: ...

    def append_comms_index(self, task_name: str, filename: str) -> None: ...

    def remove_comms_file(self, task_name: str, filename: str) -> None: ...

    def list_log_files(self, task_name: str) -> list[str]: ...

    def read_log_file(self, task_name: str, filename: str) -> str: ...

    def log_path(self, task_name: str, filename: str) -> Path: ...


class LocalFilesystemStorage:
    """Wraps existing comms/drafts helpers for local task directories."""

    def __init__(self, tasks_root: Path) -> None:
        self._tasks_root = Path(tasks_root)

    @property
    def tasks_root(self) -> Path:
        return self._tasks_root

    def task_dir(self, task_name: str) -> Path:
        return self._tasks_root / task_name

    def comms_dir(self, task_name: str) -> Path:
        return comms_mod.comms_dir(self.task_dir(task_name))

    def read_comms_index(self, task_name: str) -> list[str]:
        return comms_mod.read_index(self.task_dir(task_name))

    def read_comms_file(self, task_name: str, filename: str) -> str:
        path = self.comms_dir(task_name) / filename
        return path.read_text(encoding="utf-8")

    def write_comms_file(self, task_name: str, filename: str, content: str) -> None:
        cdir = self.comms_dir(task_name)
        cdir.mkdir(parents=True, exist_ok=True)
        (cdir / filename).write_text(content, encoding="utf-8")

    def append_comms_index(self, task_name: str, filename: str) -> None:
        idx = comms_mod.index_path(self.task_dir(task_name))
        with open(idx, "a", encoding="utf-8") as f:
            f.write(filename + "\n")

    def remove_comms_file(self, task_name: str, filename: str) -> None:
        comms_mod.remove_comms(self.task_dir(task_name), filename)

    def list_log_files(self, task_name: str) -> list[str]:
        logs_dir = self.task_dir(task_name) / comms_mod.LOGS_DIR
        if not logs_dir.is_dir():
            return []
        return sorted(p.name for p in logs_dir.iterdir() if p.is_file() and p.suffix == ".log")

    def read_log_file(self, task_name: str, filename: str) -> str:
        path = self.log_path(task_name, filename)
        return path.read_text(encoding="utf-8", errors="replace")

    def log_path(self, task_name: str, filename: str) -> Path:
        return self.task_dir(task_name) / comms_mod.LOGS_DIR / filename


class DraftsStore:
    """Draft persistence on local tasks root (.drafts)."""

    def __init__(self, tasks_root: Path) -> None:
        self._tasks_root = Path(tasks_root)

    def get_new_task_draft(self) -> dict | None:
        return drafts_mod.get_new_task_draft(self._tasks_root)

    def set_new_task_draft(self, *, title: str = "", repo: str | None = None, comment: str = "") -> None:
        drafts_mod.set_new_task_draft(self._tasks_root, title=title, repo=repo, comment=comment)

    def delete_new_task_draft(self) -> None:
        drafts_mod.delete_new_task_draft(self._tasks_root)

    def get_task_comment_draft(self, task_name: str) -> str:
        return drafts_mod.get_task_comment_draft(self._tasks_root, task_name)

    def set_task_comment_draft(self, task_name: str, content: str) -> None:
        drafts_mod.set_task_comment_draft(self._tasks_root, task_name, content)

    def get_task_bash_draft(self, task_name: str) -> str:
        return drafts_mod.get_task_bash_draft(self._tasks_root, task_name)

    def set_task_bash_draft(self, task_name: str, content: str) -> None:
        drafts_mod.set_task_bash_draft(self._tasks_root, task_name, content)

    def get_task_question_answers_draft(self, task_name: str, comms_filename: str) -> dict | None:
        return drafts_mod.get_task_question_answers_draft(
            self._tasks_root, task_name, comms_filename
        )

    def set_task_question_answers_draft(
        self, task_name: str, comms_filename: str, data: dict
    ) -> None:
        drafts_mod.set_task_question_answers_draft(
            self._tasks_root, task_name, comms_filename, data
        )

    def delete_task_question_answers_draft(self, task_name: str, comms_filename: str) -> None:
        drafts_mod.delete_task_question_answers_draft(
            self._tasks_root, task_name, comms_filename
        )
