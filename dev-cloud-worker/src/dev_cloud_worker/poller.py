"""Poll-loop cloud egress: comms sync, outbox completion (streams via supervisor)."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from pathlib import Path

from dev_sdk.worker_sync import (
    OutboxEntry,
    clear_outbox,
    clear_streams,
    flush_streams,
    forward_progress,
    has_outbox,
    read_outbox,
    read_tail_state,
    sync_task_comms_origin,
    write_outbox,
)

logger = logging.getLogger("dev_cloud_worker.poller")

COMMS_SYNC_RETRIES = 3
COMMS_SYNC_RETRY_DELAY_SEC = 0.5


class CloudPoller:
    """Owns comms sync and outbox completion; stream uploads are supervised separately."""

    def __init__(
        self,
        client,
        tasks_root: Path,
        *,
        completion_tracker=None,
    ) -> None:
        self.client = client
        self.tasks_root = tasks_root
        self._completion_tracker = completion_tracker

    def task_dir(self, task_name: str) -> Path:
        return self.tasks_root / task_name

    def sync_task(self, task_name: str, *, task_lock: Callable[[str], threading.Lock] | None = None) -> None:
        lock = task_lock(task_name) if task_lock else None
        if lock:
            with lock:
                self._sync_task_unlocked(task_name)
        else:
            self._sync_task_unlocked(task_name)

    def _sync_task_unlocked(self, task_name: str) -> None:
        task_dir = self.task_dir(task_name)
        if not task_dir.is_dir():
            return
        state = read_tail_state(task_dir)
        state = forward_progress(self.client, task_dir, task_name, state)
        sync_task_comms_origin(self.client, task_dir, task_name)

    def process_outbox(self, task_name: str, *, task_lock: Callable[[str], threading.Lock] | None = None) -> None:
        task_dir = self.task_dir(task_name)
        entry = read_outbox(task_dir)
        if entry is None:
            return

        try:
            self._sync_with_burst_retries(task_name, entry, task_lock=task_lock)
            flush_streams(self.client, task_dir, task_name)
            self.client.complete_command(
                task_name,
                error=entry.error,
                result=entry.result or {},
            )
            if self._completion_tracker is not None:
                self._completion_tracker.mark_reported(task_name)
            clear_outbox(task_dir)
            clear_streams(task_dir)
            tail_path = task_dir / ".cloud" / "tail_state.json"
            progress_path = task_dir / ".cloud" / "progress.jsonl"
            if tail_path.is_file():
                tail_path.unlink()
            if progress_path.is_file():
                progress_path.unlink()
            self.report_sync_health(task_name, healthy=True)
            logger.info("Outbox completed for %s", task_name)
        except Exception as exc:
            if not entry.unhealthy:
                entry.unhealthy = True
                self.report_sync_health(task_name, healthy=False)
                logger.warning(
                    "Outbox sync unhealthy for %s after burst retries: %s",
                    task_name,
                    exc,
                )
            entry.sync_failures += 1
            write_outbox(task_dir, entry)
            logger.warning(
                "Outbox sync attempt %d failed for %s: %s",
                entry.sync_failures,
                task_name,
                exc,
            )

    def _sync_with_burst_retries(
        self,
        task_name: str,
        entry: OutboxEntry,
        *,
        task_lock: Callable[[str], threading.Lock] | None = None,
    ) -> None:
        last_error: Exception | None = None
        if entry.unhealthy:
            self.sync_task(task_name, task_lock=task_lock)
            return
        for attempt in range(COMMS_SYNC_RETRIES):
            try:
                self.sync_task(task_name, task_lock=task_lock)
                return
            except Exception as exc:
                last_error = exc
                if attempt < COMMS_SYNC_RETRIES - 1:
                    time.sleep(COMMS_SYNC_RETRY_DELAY_SEC * (2**attempt))
        assert last_error is not None
        raise last_error

    def report_sync_health(self, task_name: str, *, healthy: bool) -> None:
        self.client.report_sync_health(
            task_name,
            sync_health="healthy" if healthy else "unhealthy",
        )

    def run_sync_pass(
        self,
        sync_tasks: list[str],
        *,
        task_lock: Callable[[str], threading.Lock] | None = None,
    ) -> None:
        seen: set[str] = set()
        for task_name in sync_tasks:
            if task_name in seen:
                continue
            seen.add(task_name)
            try:
                self.sync_task(task_name, task_lock=task_lock)
            except Exception:
                logger.exception("Background comms sync failed for %s", task_name)

        if not self.tasks_root.is_dir():
            return
        for task_dir in self.tasks_root.iterdir():
            if not task_dir.is_dir():
                continue
            task_name = task_dir.name
            if has_outbox(task_dir):
                try:
                    self.process_outbox(task_name, task_lock=task_lock)
                except Exception:
                    logger.exception("Outbox processing failed for %s", task_name)
