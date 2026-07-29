"""Shared task-directory filtering for worker filesystem scans."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path


def is_task_dir(path: Path) -> bool:
    return path.is_dir() and not path.name.startswith(".") and path.name != ".archive"


def iter_task_dirs(tasks_root: Path) -> Iterator[Path]:
    if not tasks_root.is_dir():
        return
    for path in tasks_root.iterdir():
        if is_task_dir(path):
            yield path
