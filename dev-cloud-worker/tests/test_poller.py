"""Tests for poller outbox completion."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from dev_cloud_worker.main import CommandCompletionTracker, CommandExecutor
from dev_cloud_worker.poller import COMMS_SYNC_RETRIES, CloudPoller
from dev_sdk.comms import LOGS_DIR, add_comms
from dev_sdk.worker_sync import OutboxEntry, StreamsState, has_outbox, write_outbox, write_streams


@pytest.fixture
def task_dir(tmp_path: Path) -> Path:
    root = tmp_path / "tasks"
    task = root / "my-task"
    task.mkdir(parents=True)
    add_comms(task, "001-user.md", "# hello")
    return task


class FakeClient:
    def __init__(self, *, fail_times: int = 0) -> None:
        self.fail_times = fail_times
        self.complete_calls: list[tuple] = []
        self.health_calls: list[str] = []
        self.uploads: list[tuple[str, str, bytes, str]] = []

    def sync_push(self, task_name: str, items: list[dict]) -> list[dict]:
        if self.fail_times:
            self.fail_times -= 1
            raise RuntimeError("sync failed")
        return []

    def upload_log_chunk(
        self, task_name: str, filename: str, chunk: bytes, *, kind: str = "log"
    ) -> None:
        self.uploads.append((task_name, filename, chunk, kind))

    def progress(self, task_name: str, message: str) -> None:
        pass

    def complete_command(
        self,
        task_name: str,
        *,
        error: str | None = None,
        result: dict | None = None,
    ) -> None:
        self.complete_calls.append((task_name, error, result))

    def report_sync_health(self, task_name: str, *, sync_health: str) -> None:
        self.health_calls.append(sync_health)


def test_poller_completes_outbox_after_sync(task_dir: Path) -> None:
    client = FakeClient()
    poller = CloudPoller(client, task_dir.parent)
    write_outbox(task_dir, OutboxEntry(error=None, result={"branch": "main"}))

    poller.process_outbox(task_dir.name)

    assert not has_outbox(task_dir)
    assert len(client.complete_calls) == 1
    assert client.complete_calls[0][2] == {"branch": "main"}
    assert client.health_calls[-1] == "healthy"


def test_poller_flushes_remaining_log_before_complete(task_dir: Path) -> None:
    client = FakeClient()
    poller = CloudPoller(client, task_dir.parent)
    logs = task_dir / LOGS_DIR
    logs.mkdir(parents=True)
    log_name = "dev-implement.log"
    (logs / log_name).write_bytes(b"tail-me\n")
    write_streams(task_dir, StreamsState(active_log=log_name))
    write_outbox(task_dir, OutboxEntry(error=None, result={"branch": "main"}))

    poller.process_outbox(task_dir.name)

    uploaded = b"".join(
        chunk for _, _, chunk, kind in client.uploads if kind == "log" and chunk
    )
    assert uploaded == b"tail-me\n"
    assert not has_outbox(task_dir)
    assert len(client.complete_calls) == 1


def test_poller_marks_unhealthy_after_burst_retries(
    task_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeClient(fail_times=COMMS_SYNC_RETRIES)
    poller = CloudPoller(client, task_dir.parent)
    write_outbox(task_dir, OutboxEntry(error=None, result={}))
    monkeypatch.setattr(
        "dev_cloud_worker.poller.COMMS_SYNC_RETRY_DELAY_SEC",
        0,
    )

    poller.process_outbox(task_dir.name)

    assert has_outbox(task_dir)
    assert client.complete_calls == []
    assert client.health_calls == ["unhealthy"]


def test_process_outbox_then_reconcile_does_not_queue_reboot(task_dir: Path) -> None:
    """Regression: outbox clear + stale active_commands must not create orphan outbox."""
    client = FakeClient()
    tracker = CommandCompletionTracker()
    poller = CloudPoller(client, task_dir.parent, completion_tracker=tracker)
    executor = CommandExecutor(task_dir.parent, completion_tracker=tracker)
    task_name = task_dir.name
    write_outbox(task_dir, OutboxEntry(error=None, result={"branch": "main"}))

    poller.process_outbox(task_name)
    executor.reconcile_orphans([{"task_name": task_name, "command": {}}])

    assert not has_outbox(task_dir)
    assert client.complete_calls == [(task_name, None, {"branch": "main"})]
