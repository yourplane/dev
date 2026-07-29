"""Worker telemetry collection and periodic upload."""

from __future__ import annotations

import json
import logging
import os
import shutil
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dev_sdk.comms import LOGS_DIR
from dev_sdk.worker_sync import has_outbox, read_outbox, read_streams, read_tail_state

from dev_cloud_worker.task_dirs import iter_task_dirs

logger = logging.getLogger("dev_cloud_worker.telemetry")

TELEMETRY_INTERVAL_SEC = float(os.environ.get("DEV_CLOUD_TELEMETRY_INTERVAL", "30"))
MAX_ERRORS = 50


@dataclass
class PollLoopStats:
    last_duration_ms: float = 0.0
    available_ms: float = 1000.0


class ErrorBuffer:
    """Ring buffer of recent worker errors for telemetry upload."""

    def __init__(self, max_size: int = MAX_ERRORS) -> None:
        self._items: deque[dict[str, Any]] = deque(maxlen=max_size)
        self._lock = threading.Lock()

    def add(
        self,
        message: str,
        *,
        level: str = "error",
        category: str = "worker",
        task_name: str | None = None,
        detail: str | None = None,
    ) -> None:
        entry = {
            "ts": time.time(),
            "level": level,
            "category": category,
            "message": message,
        }
        if task_name:
            entry["task_name"] = task_name
        if detail:
            entry["detail"] = detail[:4000]
        with self._lock:
            self._items.append(entry)

    def drain(self) -> list[dict[str, Any]]:
        with self._lock:
            items = list(self._items)
            self._items.clear()
        return items


def _read_cpu_percent() -> float:
    try:
        with open("/proc/stat", encoding="utf-8") as f:
            line = f.readline()
        parts = line.split()
        if parts[0] != "cpu":
            return 0.0
        values = [int(x) for x in parts[1:]]
        idle = values[3] + (values[4] if len(values) > 4 else 0)
        total = sum(values)
        path = Path("/tmp/dev-cloud-cpu-tick.json")
        prev = None
        if path.is_file():
            try:
                prev = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                prev = None
        path.write_text(json.dumps({"idle": idle, "total": total}), encoding="utf-8")
        if not prev:
            return 0.0
        idle_delta = idle - int(prev.get("idle", 0))
        total_delta = total - int(prev.get("total", 0))
        if total_delta <= 0:
            return 0.0
        return round(100.0 * (1.0 - idle_delta / total_delta), 1)
    except OSError:
        return 0.0


def _read_memory() -> dict[str, float]:
    used = 0.0
    total = 0.0
    try:
        with open("/proc/meminfo", encoding="utf-8") as f:
            info = {}
            for line in f:
                key, val = line.split(":", 1)
                info[key.strip()] = int(val.strip().split()[0]) * 1024
        total = float(info.get("MemTotal", 0))
        available = float(info.get("MemAvailable", info.get("MemFree", 0)))
        used = max(0.0, total - available)
    except (OSError, ValueError):
        pass
    pct = round(100.0 * used / total, 1) if total else 0.0
    return {
        "memory_percent": pct,
        "memory_used_bytes": used,
        "memory_total_bytes": total,
    }


def _read_storage(tasks_root: Path) -> dict[str, float]:
    try:
        usage = shutil.disk_usage(tasks_root)
        pct = round(100.0 * usage.used / usage.total, 1) if usage.total else 0.0
        return {
            "storage_used_percent": pct,
            "storage_used_bytes": float(usage.used),
            "storage_total_bytes": float(usage.total),
        }
    except OSError:
        return {
            "storage_used_percent": 0.0,
            "storage_used_bytes": 0.0,
            "storage_total_bytes": 0.0,
        }


def _stream_backlog_bytes(task_dir: Path) -> int:
    tail = read_tail_state(task_dir)
    streams = read_streams(task_dir)
    backlog = 0
    if streams.active_log and tail.log_filename == streams.active_log:
        log_path = task_dir / LOGS_DIR / streams.active_log
        if log_path.is_file():
            backlog += max(0, log_path.stat().st_size - tail.log_offset)
    if streams.active_bash and tail.bash_filename == streams.active_bash:
        bash_path = task_dir / "comms" / streams.active_bash
        if bash_path.is_file():
            backlog += max(0, bash_path.stat().st_size - tail.bash_offset)
    return backlog


def _log_silence_sec(task_dir: Path) -> float:
    streams = read_streams(task_dir)
    if not streams.active_log:
        return 0.0
    log_path = task_dir / LOGS_DIR / streams.active_log
    if not log_path.is_file():
        return 0.0
    tail = read_tail_state(task_dir)
    if log_path.stat().st_size > tail.log_offset:
        return 0.0
    return round(max(0.0, time.time() - log_path.stat().st_mtime), 1)


def _has_active_streams(task_dir: Path) -> bool:
    streams = read_streams(task_dir)
    return bool(streams.active_log or streams.active_bash)


def _managed_task_names(tasks_root: Path, sync_tasks: list[str]) -> set[str]:
    managed = set(sync_tasks)
    for task_dir in iter_task_dirs(tasks_root):
        if has_outbox(task_dir) or _has_active_streams(task_dir):
            managed.add(task_dir.name)
    return managed


def _activity_badges(
    task_name: str,
    *,
    sync_tasks: set[str],
    running_tasks: set[str],
    task_dir: Path,
    outbox,
    stream_backlog: int,
) -> list[str]:
    badges: list[str] = []
    if task_name in sync_tasks:
        badges.append("sync_tasks")
    if task_name in running_tasks:
        badges.append("command")
    if outbox is not None:
        badges.append("outbox")
    if _has_active_streams(task_dir):
        badges.append("uploading")
    if stream_backlog > 0:
        badges.append("backlog")
    if outbox and outbox.sync_failures > 0:
        badges.append("sync_failures")
    return badges


def collect_managed_task_metrics(
    tasks_root: Path,
    sync_tasks: list[str],
    running_tasks: set[str],
) -> list[dict[str, Any]]:
    sync_set = set(sync_tasks)
    metrics: list[dict[str, Any]] = []
    for task_name in sorted(_managed_task_names(tasks_root, sync_tasks)):
        task_dir = tasks_root / task_name
        if not task_dir.is_dir():
            continue
        outbox = read_outbox(task_dir)
        stream_backlog = _stream_backlog_bytes(task_dir)
        entry: dict[str, Any] = {
            "task_name": task_name,
            "in_sync_tasks": task_name in sync_set,
            "active_command": task_name in running_tasks,
            "stream_backlog_bytes": stream_backlog,
            "log_silence_sec": _log_silence_sec(task_dir),
            "sync_failures": outbox.sync_failures if outbox else 0,
            "activity_badges": _activity_badges(
                task_name,
                sync_tasks=sync_set,
                running_tasks=running_tasks,
                task_dir=task_dir,
                outbox=outbox,
                stream_backlog=stream_backlog,
            ),
        }
        if outbox and outbox.error:
            entry["outbox_error"] = outbox.error
        metrics.append(entry)
    return metrics


def collect_thread_inventory(
    *,
    executor,
    stream_supervisor,
    bg_sync,
    telemetry_thread: threading.Thread,
    telemetry_uploading: bool,
    running_commands: dict[str, str],
) -> list[dict[str, Any]]:
    inventory: list[dict[str, Any]] = [
        {
            "category": "infrastructure",
            "label": "Poll loop",
            "state": "active",
            "detail": "main thread",
        },
    ]
    bg_status = bg_sync.sync_status()
    inventory.append(
        {
            "category": "infrastructure",
            "label": "Background sync",
            "state": bg_status["state"],
            "detail": bg_status.get("detail") or "idle",
        }
    )
    tel_state = "active" if telemetry_uploading else "idle"
    inventory.append(
        {
            "category": "infrastructure",
            "label": "Telemetry",
            "state": tel_state,
            "detail": "uploading metrics" if telemetry_uploading else "waiting",
        }
    )
    if not telemetry_thread.is_alive():
        inventory[-1]["state"] = "idle"
        inventory[-1]["detail"] = "not running"

    for task_name, command in sorted(running_commands.items()):
        inventory.append(
            {
                "category": "commands",
                "label": f"{task_name} / {command}",
                "state": "active",
                "task_name": task_name,
                "command": command,
            }
        )

    for stream in stream_supervisor.active_streams():
        kind = stream["kind"]
        filename = stream["filename"]
        task_name = stream["task_name"]
        inventory.append(
            {
                "category": "stream_uploads",
                "label": f"{task_name} / {kind} / {filename}",
                "state": stream.get("state", "active"),
                "task_name": task_name,
                "kind": kind,
                "filename": filename,
            }
        )
    return inventory


def collect_env_metrics(
    tasks_root: Path,
    poll_stats: PollLoopStats,
    *,
    total_threads: int,
    bg_sync_queue_depth: int,
    upload_backlog_bytes: int,
) -> dict[str, Any]:
    metrics: dict[str, Any] = {
        "cpu_percent": _read_cpu_percent(),
        **_read_memory(),
        **_read_storage(tasks_root),
        "poll_loop_duration_ms": round(poll_stats.last_duration_ms, 1),
        "poll_loop_available_ms": round(poll_stats.available_ms, 1),
        "total_threads": total_threads,
        "bg_sync_queue_depth": bg_sync_queue_depth,
        "upload_backlog_bytes": upload_backlog_bytes,
        "download_backlog_bytes": 0,
    }
    if poll_stats.available_ms > 0:
        metrics["poll_loop_utilization"] = round(
            100.0 * poll_stats.last_duration_ms / poll_stats.available_ms, 1
        )
    else:
        metrics["poll_loop_utilization"] = 0.0
    return metrics


def build_telemetry_payload(
    environment_id: str,
    tasks_root: Path,
    poll_stats: PollLoopStats,
    *,
    sync_tasks: list[str],
    running_tasks: set[str],
    running_commands: dict[str, str],
    thread_inventory: list[dict[str, Any]],
    bg_sync_queue_depth: int,
    errors: list[dict[str, Any]],
) -> dict[str, Any]:
    task_metrics = collect_managed_task_metrics(tasks_root, sync_tasks, running_tasks)
    upload_backlog = sum(int(t.get("stream_backlog_bytes") or 0) for t in task_metrics)
    for task in task_metrics:
        outbox_error = task.pop("outbox_error", None)
        if outbox_error:
            errors.append(
                {
                    "ts": time.time(),
                    "level": "error",
                    "category": "outbox",
                    "message": str(outbox_error),
                    "task_name": task["task_name"],
                }
            )
    total_threads = len(thread_inventory)
    return {
        "environment_id": environment_id,
        "ts": time.time(),
        "sync_tasks": sync_tasks,
        "env_metrics": collect_env_metrics(
            tasks_root,
            poll_stats,
            total_threads=total_threads,
            bg_sync_queue_depth=bg_sync_queue_depth,
            upload_backlog_bytes=upload_backlog,
        ),
        "task_metrics": task_metrics,
        "thread_inventory": thread_inventory,
        "errors": errors,
    }


class TelemetryReporter:
    """Posts telemetry to the control plane on a fixed interval."""

    def __init__(
        self,
        client,
        tasks_root: Path,
        poll_stats: PollLoopStats,
        error_buffer: ErrorBuffer,
        *,
        executor,
        stream_supervisor,
        bg_sync,
        sync_tasks_state,
    ) -> None:
        self._client = client
        self._tasks_root = tasks_root
        self._poll_stats = poll_stats
        self._error_buffer = error_buffer
        self._executor = executor
        self._stream_supervisor = stream_supervisor
        self._bg_sync = bg_sync
        self._sync_tasks_state = sync_tasks_state
        self._uploading = False
        self._upload_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name="telemetry")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _is_uploading(self) -> bool:
        with self._upload_lock:
            return self._uploading

    def _run(self) -> None:
        while not self._stop.wait(timeout=TELEMETRY_INTERVAL_SEC):
            try:
                errors = self._error_buffer.drain()
                inventory = collect_thread_inventory(
                    executor=self._executor,
                    stream_supervisor=self._stream_supervisor,
                    bg_sync=self._bg_sync,
                    telemetry_thread=self._thread,
                    telemetry_uploading=self._is_uploading(),
                    running_commands=self._executor.running_commands(),
                )
                payload = build_telemetry_payload(
                    self._client.env_id,
                    self._tasks_root,
                    self._poll_stats,
                    sync_tasks=self._sync_tasks_state.get(),
                    running_tasks=self._executor.running_tasks(),
                    running_commands=self._executor.running_commands(),
                    thread_inventory=inventory,
                    bg_sync_queue_depth=self._bg_sync.queue_depth(),
                    errors=errors,
                )
                with self._upload_lock:
                    self._uploading = True
                try:
                    self._client.post_telemetry(payload)
                finally:
                    with self._upload_lock:
                        self._uploading = False
            except Exception:
                logger.exception("Telemetry upload failed")
