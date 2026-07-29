"""Thread-safe holder for the latest control-plane sync_tasks list."""

from __future__ import annotations

import threading


class SyncTasksState:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tasks: list[str] = []

    def update(self, tasks: list[str]) -> None:
        with self._lock:
            self._tasks = list(tasks)

    def get(self) -> list[str]:
        with self._lock:
            return list(self._tasks)
