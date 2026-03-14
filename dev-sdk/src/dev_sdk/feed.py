"""Unified task feed: comms and agent logs sorted by file creation date."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dev_sdk.comms import comms_dir, read_index

LOGS_DIR = ".logs"


def _file_created_at(path: Path) -> float:
    """Return sort key for path: mtime (creation not always available)."""
    try:
        st = path.stat()
        # Prefer birthtime when available (Python 3.10+), else mtime
        if hasattr(st, "st_birthtime") and st.st_birthtime:
            return st.st_birthtime
        return st.st_mtime
    except OSError:
        return 0.0


@dataclass(frozen=True)
class FeedEntry:
    """Single feed item: comms file or agent log file."""

    type: str  # "comms" | "log"
    id: str  # filename for comms, filename for log (e.g. "dev-plan-stream-20260314-195628.log")
    created_at: float  # Unix timestamp for sorting


def read_feed(task_dir: Path) -> list[FeedEntry]:
    """
    Return unified feed entries (comms + agent logs) sorted by file creation date ascending.
    """
    entries: list[FeedEntry] = []
    cdir = comms_dir(task_dir)
    if cdir.exists():
        for filename in read_index(task_dir):
            path = cdir / filename
            if path.is_file():
                entries.append(
                    FeedEntry(type="comms", id=filename, created_at=_file_created_at(path))
                )
    logs_dir = task_dir / LOGS_DIR
    if logs_dir.is_dir():
        for p in sorted(logs_dir.iterdir()):
            if p.is_file() and p.suffix == ".log":
                entries.append(
                    FeedEntry(type="log", id=p.name, created_at=_file_created_at(p))
                )
    entries.sort(key=lambda e: (e.created_at, e.id))
    return entries
