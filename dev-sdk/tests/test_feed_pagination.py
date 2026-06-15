"""Tests for feed pagination."""

import json
import os
from pathlib import Path

import pytest

from dev_sdk.comms import index_path
from dev_sdk.feed import FeedCursor, read_feed_page

LOGS_DIR = ".logs"


@pytest.fixture
def task_dir(tmp_path: Path) -> Path:
    return tmp_path / "task"


def _seed_entries(task_dir: Path, count: int) -> None:
    (task_dir / "comms").mkdir(parents=True)
    names = [f"{i:03d}-user.md" for i in range(1, count + 1)]
    index_path(task_dir).write_text("\n".join(names) + "\n")
    for i, name in enumerate(names, start=1):
        path = task_dir / "comms" / name
        path.write_text(f"msg {i}")
        os.utime(path, (float(i), float(i)))


def test_read_feed_page_empty(task_dir: Path) -> None:
    task_dir.mkdir()
    page = read_feed_page(task_dir, limit=50)
    assert page.entries == []
    assert page.total == 0
    assert page.has_older is False
    assert page.oldest_cursor is None


def test_read_feed_page_newest_tail(task_dir: Path) -> None:
    _seed_entries(task_dir, 120)
    page = read_feed_page(task_dir, limit=50)
    assert len(page.entries) == 50
    assert page.total == 120
    assert page.has_older is True
    assert page.entries[0].id == "071-user.md"
    assert page.entries[-1].id == "120-user.md"
    assert page.oldest_cursor == FeedCursor(created_at=71.0, id="071-user.md")


def test_read_feed_page_load_older(task_dir: Path) -> None:
    _seed_entries(task_dir, 120)
    first = read_feed_page(task_dir, limit=50)
    assert first.oldest_cursor is not None
    second = read_feed_page(task_dir, limit=50, before=first.oldest_cursor)
    assert len(second.entries) == 50
    assert second.has_older is True
    assert second.entries[0].id == "021-user.md"
    assert second.entries[-1].id == "070-user.md"


def test_read_feed_page_after_incremental(task_dir: Path) -> None:
    _seed_entries(task_dir, 5)
    page = read_feed_page(task_dir, after=3.0)
    assert [e.id for e in page.entries] == ["004-user.md", "005-user.md"]
    assert page.total == 5


def test_read_feed_page_deletable_with_logs(task_dir: Path) -> None:
    (task_dir / "comms").mkdir(parents=True)
    index_path(task_dir).write_text("001-user.md\n002-user.md\n")
    (task_dir / "comms" / "001-user.md").write_text("Old")
    (task_dir / "comms" / "002-user.md").write_text("New")
    (task_dir / LOGS_DIR).mkdir(parents=True)
    (task_dir / LOGS_DIR / "dev.log").write_text(
        json.dumps({"type": "thinking", "timestamp_ms": 5_000_000}) + "\n",
        encoding="utf-8",
    )
    os.utime(task_dir / "comms" / "001-user.md", (1, 1))
    os.utime(task_dir / "comms" / "002-user.md", (10_000, 10_000))
    page = read_feed_page(task_dir, limit=10)
    by_id = {e.id: e for e in page.entries}
    assert by_id["001-user.md"].deletable is False
    assert by_id["002-user.md"].deletable is True
