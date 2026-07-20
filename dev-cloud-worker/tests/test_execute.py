"""Tests for command execution (local work + outbox, no direct cloud writes)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from dev_cloud_worker.main import WORKER_REBOOT_MESSAGE, CommandCompletionTracker, CommandExecutor
from dev_sdk.comms import add_comms
from dev_sdk.worker_sync import has_outbox, read_outbox, write_outbox


@pytest.fixture
def task_dir(tmp_path: Path) -> Path:
    task_name = "my-task"
    root = tmp_path / "tasks"
    task = root / task_name
    task.mkdir(parents=True)
    add_comms(task, "001-user.md", "# hello")
    return task


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    def command_start(self, task_name: str) -> None:
        self.calls.append(("command_start", task_name))

    def complete_command(
        self,
        task_name: str,
        *,
        error: str | None = None,
        result: dict | None = None,
    ) -> None:
        self.calls.append(("complete_command", task_name, error, result))

    def sync_push(self, task_name: str, items: list[dict]) -> list[dict]:
        self.calls.append(("sync_push", task_name))
        return []


def test_execute_writes_outbox_without_cloud_complete(
    task_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeClient()
    executor = CommandExecutor(task_dir.parent)
    monkeypatch.setattr(executor, "_archive", MagicMock())

    executor.execute(task_dir.name, {"command": "archive", "payload": {}})

    assert has_outbox(task_dir)
    entry = read_outbox(task_dir)
    assert entry is not None
    assert entry.error is None
    assert client.calls == []


def test_execute_outbox_records_error(
    task_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executor = CommandExecutor(task_dir.parent)
    monkeypatch.setattr(
        executor,
        "_archive",
        MagicMock(side_effect=RuntimeError("boom")),
    )

    executor.execute(task_dir.name, {"command": "archive", "payload": {}})

    entry = read_outbox(task_dir)
    assert entry is not None
    assert entry.error == "boom"


def test_cancel_command_does_not_write_outbox(task_dir: Path) -> None:
    executor = CommandExecutor(task_dir.parent)
    executor.execute(task_dir.name, {"command": "cancel", "payload": {}})
    assert not has_outbox(task_dir)


def test_finish_keeps_running_until_outbox_written(
    task_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: orphan reconciliation must not run between finish and outbox."""
    executor = CommandExecutor(task_dir.parent)
    task_name = task_dir.name
    monkeypatch.setattr(executor, "_archive", MagicMock())

    real_write_outbox = write_outbox

    def write_outbox_while_still_running(td, entry):
        assert executor.is_running(task_name)
        executor.reconcile_orphans([{"task_name": task_name, "command": {}}])
        assert not has_outbox(td)
        real_write_outbox(td, entry)

    monkeypatch.setattr("dev_cloud_worker.main.write_outbox", write_outbox_while_still_running)

    assert executor.try_start(task_name)
    executor.execute(task_name, {"command": "archive", "payload": {}})

    assert not executor.is_running(task_name)
    entry = read_outbox(task_dir)
    assert entry is not None
    assert entry.error is None
    assert entry.error != WORKER_REBOOT_MESSAGE


def test_reconcile_orphans_skips_after_outbox_reported(task_dir: Path) -> None:
    """Regression: stale active_commands after outbox processing must not re-queue reboot."""
    tracker = CommandCompletionTracker()
    executor = CommandExecutor(task_dir.parent, completion_tracker=tracker)
    task_name = task_dir.name

    tracker.mark_reported(task_name)
    executor.reconcile_orphans([{"task_name": task_name, "command": {}}])

    assert not has_outbox(task_dir)


def test_reconcile_orphans_clears_reported_when_command_inactive(task_dir: Path) -> None:
    tracker = CommandCompletionTracker()
    executor = CommandExecutor(task_dir.parent, completion_tracker=tracker)
    task_name = task_dir.name

    tracker.mark_reported(task_name)
    executor.reconcile_orphans([])
    executor.reconcile_orphans([{"task_name": task_name, "command": {}}])

    assert has_outbox(task_dir)
    entry = read_outbox(task_dir)
    assert entry is not None
    assert entry.error == WORKER_REBOOT_MESSAGE
