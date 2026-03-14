"""Tests for feed module."""

from pathlib import Path

import pytest

from dev_sdk.comms import add_comms, comms_dir, index_path
from dev_sdk.feed import read_feed


@pytest.fixture
def task_dir(tmp_path: Path) -> Path:
    return tmp_path / "task"


def test_read_feed_empty(task_dir: Path) -> None:
    task_dir.mkdir()
    assert read_feed(task_dir) == []


def test_read_feed_comms_only(task_dir: Path) -> None:
    (task_dir / "comms").mkdir(parents=True)
    (task_dir / "comms" / "index.txt").write_text("001-user.md\n")
    (task_dir / "comms" / "001-user.md").write_text("Hello")
    entries = read_feed(task_dir)
    assert len(entries) == 1
    assert entries[0].type == "comms"
    assert entries[0].id == "001-user.md"


def test_read_feed_logs_only(task_dir: Path) -> None:
    logs_dir = task_dir / ".logs"
    logs_dir.mkdir(parents=True)
    (logs_dir / "dev-plan-stream-20260314-120000.log").write_text('{"type":"system"}\n')
    entries = read_feed(task_dir)
    assert len(entries) == 1
    assert entries[0].type == "log"
    assert entries[0].id == "dev-plan-stream-20260314-120000.log"


def test_read_feed_comms_and_logs_sorted_by_created_at(task_dir: Path) -> None:
    (task_dir / "comms").mkdir(parents=True)
    index_path(task_dir).write_text("001-user.md\n")
    (task_dir / "comms" / "001-user.md").write_text("First")
    logs_dir = task_dir / ".logs"
    logs_dir.mkdir(parents=True)
    (logs_dir / "dev-plan-stream-20260314-120000.log").write_text("log1")
    (logs_dir / "dev-implement-stream-20260314-130000.log").write_text("log2")
    add_comms(task_dir, "agent", "Plan", kind="plan")
    entries = read_feed(task_dir)
    assert len(entries) >= 3
    types = [e.type for e in entries]
    ids = [e.id for e in entries]
    assert "comms" in types and "log" in types
    # Should be sorted by created_at
    for i in range(len(entries) - 1):
        assert entries[i].created_at <= entries[i + 1].created_at
