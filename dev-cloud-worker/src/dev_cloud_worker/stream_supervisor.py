"""Supervised per-stream log/bash upload threads."""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Callable

from dev_sdk.worker_sync import (
    read_streams,
    read_tail_state,
    tail_bash_file,
    tail_log_file,
)

logger = logging.getLogger("dev_cloud_worker.stream_supervisor")

STREAM_UPLOAD_INTERVAL_SEC = 0.25


class StreamUploadSupervisor:
    """Ensure one tail+upload thread per active log/bash stream."""

    def __init__(self, client, tasks_root: Path) -> None:
        self.client = client
        self.tasks_root = tasks_root
        self._threads: dict[tuple[str, str, str], threading.Thread] = {}
        self._guard = threading.Lock()

    def supervise(self) -> None:
        active: set[tuple[str, str, str]] = set()
        if not self.tasks_root.is_dir():
            return
        for task_dir in self.tasks_root.iterdir():
            if not task_dir.is_dir():
                continue
            task_name = task_dir.name
            streams = read_streams(task_dir)
            if streams.active_log:
                key = (task_name, "log", streams.active_log)
                active.add(key)
                self._ensure_thread(task_name, "log", streams.active_log, task_dir)
            if streams.active_bash:
                key = (task_name, "bash", streams.active_bash)
                active.add(key)
                self._ensure_thread(task_name, "bash", streams.active_bash, task_dir)
        with self._guard:
            stale = [k for k, t in self._threads.items() if k not in active and not t.is_alive()]
            for key in stale:
                del self._threads[key]

    def _ensure_thread(
        self,
        task_name: str,
        kind: str,
        filename: str,
        task_dir: Path,
    ) -> None:
        key = (task_name, kind, filename)
        with self._guard:
            thread = self._threads.get(key)
            if thread is not None and thread.is_alive():
                return
            thread = threading.Thread(
                target=self._upload_loop,
                args=(task_name, kind, filename, task_dir),
                daemon=True,
                name=f"stream-{task_name}-{kind}-{filename}",
            )
            self._threads[key] = thread
            thread.start()

    def _upload_loop(self, task_name: str, kind: str, filename: str, task_dir: Path) -> None:
        while True:
            streams = read_streams(task_dir)
            if kind == "log":
                if streams.active_log != filename:
                    return
            elif streams.active_bash != filename:
                return
            try:
                state = read_tail_state(task_dir)
                if kind == "log":
                    tail_log_file(self.client, task_dir, task_name, filename, state)
                else:
                    tail_bash_file(self.client, task_dir, task_name, filename, state)
            except Exception:
                logger.exception("Stream upload failed for %s %s", task_name, filename)
            time.sleep(STREAM_UPLOAD_INTERVAL_SEC)


class BackgroundSyncWorker:
    """Runs heavy comms/outbox sync off the foreground poll loop."""

    def __init__(
        self,
        poller,
        *,
        task_lock: Callable[[str], threading.Lock],
    ) -> None:
        self._poller = poller
        self._task_lock = task_lock
        self._pending: set[str] = set()
        self._wake = threading.Event()
        self._guard = threading.Lock()
        self._thread = threading.Thread(target=self._run, daemon=True, name="bg-sync")
        self._thread.start()

    def enqueue(self, sync_tasks: list[str]) -> None:
        with self._guard:
            self._pending.update(sync_tasks)
        self._wake.set()

    def _run(self) -> None:
        while True:
            self._wake.wait(timeout=1.0)
            self._wake.clear()
            with self._guard:
                tasks = list(self._pending)
                self._pending.clear()
            if not tasks:
                continue
            try:
                self._poller.run_sync_pass(tasks, task_lock=self._task_lock)
            except Exception:
                logger.exception("Background sync pass failed")
