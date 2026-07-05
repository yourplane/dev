"""SSE task stream helpers shared by cloud control plane and dev-server."""

from __future__ import annotations

import json
import time
from typing import Any, Callable

STREAM_MAX_DURATION_SEC = 165  # 2:45 proactive reconnect (CloudFront 180s cap)
HEARTBEAT_INTERVAL_SEC = 1.0

SSE_HEADERS = {
    "Content-Type": "text/event-stream",
    "Cache-Control": "no-cache",
    "Access-Control-Allow-Origin": "*",
    "X-Accel-Buffering": "no",
}


def sse_event(event_type: str, data: Any) -> str:
    payload = data if isinstance(data, str) else json.dumps(data, separators=(",", ":"))
    lines: list[str] = []
    if event_type:
        lines.append(f"event: {event_type}")
    for line in str(payload).splitlines():
        lines.append(f"data: {line}")
    lines.append("")
    return "\n".join(lines) + "\n"


def run_task_stream(
    *,
    log_offset: int,
    bash_offset: int,
    read_log: Callable[[int], tuple[str, int] | None],
    read_bash: Callable[[int], tuple[str, int] | None],
    is_active: Callable[[], bool],
    write: Callable[[str], None],
    max_duration_sec: float = STREAM_MAX_DURATION_SEC,
    heartbeat_interval_sec: float = HEARTBEAT_INTERVAL_SEC,
) -> tuple[int, int]:
    """Poll log/bash sources and emit SSE until reconnect deadline or command ends."""
    deadline = time.monotonic() + max_duration_sec
    last_heartbeat = 0.0
    while time.monotonic() < deadline:
        now = time.monotonic()
        if now - last_heartbeat >= heartbeat_interval_sec:
            write(sse_event("heartbeat", {}))
            last_heartbeat = now
        if not is_active():
            break
        log_result = read_log(log_offset)
        if log_result is not None:
            chunk, log_offset = log_result
            if chunk:
                write(sse_event("log", {"chunk": chunk, "offset": log_offset}))
        bash_result = read_bash(bash_offset)
        if bash_result is not None:
            chunk, bash_offset = bash_result
            if chunk:
                write(sse_event("bash", {"chunk": chunk, "offset": bash_offset}))
        time.sleep(0.25)
    write(sse_event("reconnect", {"log_offset": log_offset, "bash_offset": bash_offset}))
    return log_offset, bash_offset
