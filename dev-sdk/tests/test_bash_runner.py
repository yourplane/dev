"""Tests for shared bash streaming runner."""

import subprocess
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from dev_sdk.bash_runner import (
    _bash_comms_append_lock,
    append_bytes_to_bash_comms,
    popen_bash_for_streaming,
    run_bash_stream,
)


def test_popen_bash_for_streaming_uses_unbuffered_pipe(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default subprocess PIPE buffers ~8KiB in Python; bufsize=0 yields incremental reads."""
    kwargs_seen: dict[str, object] = {}
    orig_popen = subprocess.Popen

    def capture_popen(*args: object, **kwargs: object) -> subprocess.Popen:
        kwargs_seen.update(kwargs)
        return orig_popen(*args, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", capture_popen)
    proc = popen_bash_for_streaming("exit 0", cwd="/tmp")
    proc.wait(timeout=5)
    assert kwargs_seen.get("bufsize") == 0


def test_run_bash_stream_writes_comms_and_footer(tmp_path: Path) -> None:
    task = tmp_path / "task"
    task.mkdir()
    cancel = threading.Event()
    result = run_bash_stream(task, "echo hello", cwd=task, cancel_event=cancel)
    assert result.exit_code == 0
    assert result.comms_path is not None
    text = result.comms_path.read_text(encoding="utf-8")
    assert "echo hello" in text
    assert "hello" in text
    assert "Exit code: 0" in text


def test_bash_append_lock_is_per_path(tmp_path: Path) -> None:
    path_a = tmp_path / "a.md"
    path_b = tmp_path / "b.md"
    path_a.write_bytes(b"")
    path_b.write_bytes(b"")

    assert _bash_comms_append_lock(path_a) is not _bash_comms_append_lock(path_b)
    assert _bash_comms_append_lock(path_a) is _bash_comms_append_lock(path_a)

    a_held = threading.Event()
    b_done = threading.Event()

    def hold_a() -> None:
        with _bash_comms_append_lock(path_a):
            a_held.set()
            time.sleep(0.2)
            with open(path_a, "ab") as f:
                f.write(b"a")

    def write_b() -> None:
        a_held.wait(timeout=2)
        append_bytes_to_bash_comms(path_b, b"b")
        b_done.set()

    t1 = threading.Thread(target=hold_a)
    t2 = threading.Thread(target=write_b)
    t1.start()
    t2.start()
    assert b_done.wait(timeout=0.15)
    t1.join(timeout=2)
    t2.join(timeout=2)
    assert path_a.read_bytes() == b"a"
    assert path_b.read_bytes() == b"b"
