"""Tests for command execution (local work + outbox, no direct cloud writes)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from dev_cloud_worker.main import CommandExecutor
from dev_sdk.comms import add_comms
from dev_sdk.worker_sync import has_outbox, read_outbox


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
