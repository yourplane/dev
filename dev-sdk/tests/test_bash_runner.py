"""Tests for shared bash streaming runner."""

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from dev_sdk.bash_runner import popen_bash_for_streaming, run_bash_stream
import threading


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
