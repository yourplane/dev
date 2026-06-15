"""Unified task feed: comms and agent logs sorted by file creation date."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from dev_sdk.comms import agent_logs_cutoff_epoch_secs, comms_dir, comms_file_removable, read_index

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
    deletable: bool | None = None  # comms: whether API DELETE is allowed; log entries: None


@dataclass(frozen=True)
class FeedCursor:
    created_at: float
    id: str


@dataclass(frozen=True)
class FeedPage:
    entries: list[FeedEntry]
    total: int
    has_older: bool
    oldest_cursor: FeedCursor | None


def _collect_feed_entries(task_dir: Path) -> list[FeedEntry]:
    """Build all feed entries, computing agent-log cutoff once per request."""
    logs_cutoff = agent_logs_cutoff_epoch_secs(task_dir)
    entries: list[FeedEntry] = []
    cdir = comms_dir(task_dir)
    if cdir.exists():
        for filename in read_index(task_dir):
            path = cdir / filename
            if path.is_file():
                entries.append(
                    FeedEntry(
                        type="comms",
                        id=filename,
                        created_at=_file_created_at(path),
                        deletable=comms_file_removable(task_dir, path, logs_cutoff=logs_cutoff),
                    )
                )
    logs_dir = task_dir / LOGS_DIR
    if logs_dir.is_dir():
        for p in sorted(logs_dir.iterdir()):
            if p.is_file() and p.suffix == ".log":
                entries.append(
                    FeedEntry(type="log", id=p.name, created_at=_file_created_at(p), deletable=None)
                )
    entries.sort(key=lambda e: (e.created_at, e.id))
    return entries


def read_feed(task_dir: Path) -> list[FeedEntry]:
    """
    Return unified feed entries (comms + agent logs) sorted by file creation date ascending.
    """
    return _collect_feed_entries(task_dir)


def read_comms_deletable_map(task_dir: Path) -> dict[str, bool]:
    """Return deletable flags for all comms files (agent-log cutoff computed once)."""
    logs_cutoff = agent_logs_cutoff_epoch_secs(task_dir)
    result: dict[str, bool] = {}
    cdir = comms_dir(task_dir)
    if not cdir.exists():
        return result
    for filename in read_index(task_dir):
        path = cdir / filename
        if path.is_file():
            result[filename] = comms_file_removable(task_dir, path, logs_cutoff=logs_cutoff)
    return result


def read_feed_page(
    task_dir: Path,
    *,
    limit: int | None = None,
    before: FeedCursor | None = None,
    after: float | None = None,
) -> FeedPage:
    """
    Return a page of feed entries.

    - No limit: all entries (same as read_feed).
    - after: entries with created_at > after (incremental poll); ignores limit/before.
    - limit without before: newest page (last N entries), ascending within the page.
    - limit with before: up to N entries strictly older than the cursor, ascending within the page.
    """
    all_entries = _collect_feed_entries(task_dir)
    total = len(all_entries)

    if after is not None:
        entries = [e for e in all_entries if e.created_at > after]
        return FeedPage(entries=entries, total=total, has_older=False, oldest_cursor=None)

    if limit is None:
        return FeedPage(entries=all_entries, total=total, has_older=False, oldest_cursor=None)

    pool = all_entries
    if before is not None:
        pool = [e for e in all_entries if (e.created_at, e.id) < (before.created_at, before.id)]

    page = pool[-limit:] if len(pool) > limit else pool
    has_older = len(pool) > limit
    oldest_cursor = FeedCursor(created_at=page[0].created_at, id=page[0].id) if page else None
    return FeedPage(entries=page, total=total, has_older=has_older, oldest_cursor=oldest_cursor)
