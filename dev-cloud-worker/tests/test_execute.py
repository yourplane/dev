"""Tests for command execution ordering (comms sync before complete)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, call

import pytest

from dev_cloud_worker.main import CommandExecutor
from dev_sdk.comms import add_comms


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
        self.sync_failures = 0

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
        if self.sync_failures:
            self.sync_failures -= 1
            raise RuntimeError("sync failed")
        return []


def test_execute_syncs_comms_before_complete(task_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeClient()
    executor = CommandExecutor(client)  # type: ignore[arg-type]
    executor.tasks_root = task_dir.parent
    monkeypatch.setattr(executor, "_archive", MagicMock())

    executor.execute(task_dir.name, {"command": "archive", "payload": {}})

    sync_idx = next(i for i, c in enumerate(client.calls) if c[0] == "sync_push")
    complete_idx = next(i for i, c in enumerate(client.calls) if c[0] == "complete_command")
    assert sync_idx < complete_idx
    assert client.calls[complete_idx] == ("complete_command", task_dir.name, None, {})


def test_execute_reports_sync_failure_after_retries(
    task_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeClient()
    client.sync_failures = 3
    executor = CommandExecutor(client)  # type: ignore[arg-type]
    executor.tasks_root = task_dir.parent
    monkeypatch.setattr(executor, "_archive", MagicMock())
    monkeypatch.setattr(
        "dev_cloud_worker.main.COMMS_SYNC_RETRY_DELAY_SEC",
        0,
    )

    executor.execute(task_dir.name, {"command": "archive", "payload": {}})

    sync_calls = [c for c in client.calls if c[0] == "sync_push"]
    assert len(sync_calls) == 3
    complete = next(c for c in client.calls if c[0] == "complete_command")
    assert complete[2] == "Failed to sync comms: sync failed"
    assert complete[3] is None


def test_execute_retries_sync_then_succeeds(
    task_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeClient()
    client.sync_failures = 1
    executor = CommandExecutor(client)  # type: ignore[arg-type]
    executor.tasks_root = task_dir.parent
    monkeypatch.setattr(executor, "_archive", MagicMock())
    monkeypatch.setattr(
        "dev_cloud_worker.main.COMMS_SYNC_RETRY_DELAY_SEC",
        0,
    )

    executor.execute(task_dir.name, {"command": "archive", "payload": {}})

    sync_calls = [c for c in client.calls if c[0] == "sync_push"]
    assert len(sync_calls) == 2
    complete = next(c for c in client.calls if c[0] == "complete_command")
    assert complete[2] is None


def test_cancel_command_does_not_sync_or_complete(task_dir: Path) -> None:
    client = FakeClient()
    executor = CommandExecutor(client)  # type: ignore[arg-type]
    executor.tasks_root = task_dir.parent

    executor.execute(task_dir.name, {"command": "cancel", "payload": {}})

    assert client.calls == []
