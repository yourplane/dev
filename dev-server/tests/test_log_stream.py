"""Tests for active log filename in command status and log stream endpoint."""

import os
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from dev_server.main import app


@pytest.fixture
def task_dir(tmp_path: Path) -> Path:
    """Create a minimal task dir with agent-chat-id and .logs with a fake log file."""
    t = tmp_path / "mytask"
    t.mkdir()
    (t / "agent-chat-id").write_text("fake-chat-id")
    logs = t / ".logs"
    logs.mkdir()
    (logs / "dev-plan-stream-20260101-120000.log").write_text("line one\nline two\n")
    return t


@pytest.fixture
def client_with_tasks(task_dir: Path) -> TestClient:
    """TestClient with DEV_TASKS_DIR set so the task exists."""
    root = task_dir.parent
    with patch.dict(os.environ, {"DEV_TASKS_DIR": str(root)}, clear=False):
        yield TestClient(app)


def test_command_status_includes_active_log_filename_when_set(
    client_with_tasks: TestClient, task_dir: Path
) -> None:
    """When a running command calls on_start, GET commands returns active_log_filename."""
    block = threading.Event()
    log_path = task_dir / ".logs" / "dev-plan-stream-20260101-120000.log"

    def run_plan_with_on_start(task_dir_arg: Path, *, on_start=None, **kwargs: object) -> None:
        if on_start:
            on_start(log_path)
        block.wait()

    with patch("dev_server.main.run_plan_implement", side_effect=run_plan_with_on_start):
        client_with_tasks.post("/tasks/mytask/commands", json={"command": "plan-implement"})
    time.sleep(0.1)
    resp = client_with_tasks.get("/tasks/mytask/commands")
    assert resp.status_code == 200
    assert resp.json()["active"] is True
    assert resp.json()["active_log_filename"] == "dev-plan-stream-20260101-120000.log"
    block.set()


def test_log_stream_404_when_no_command(client_with_tasks: TestClient) -> None:
    """GET logs/stream returns 404 when no command is running."""
    resp = client_with_tasks.get("/tasks/mytask/logs/stream")
    assert resp.status_code == 404
    assert "No command" in resp.json()["detail"]


def test_log_stream_returns_sse_when_command_running(
    client_with_tasks: TestClient, task_dir: Path
) -> None:
    """When a command is running, GET logs/stream returns 200 with text/event-stream."""
    block = threading.Event()
    log_path = task_dir / ".logs" / "dev-plan-stream-20260101-120000.log"

    def run_plan_with_on_start(task_dir_arg: Path, *, on_start=None, **kwargs: object) -> None:
        if on_start:
            on_start(log_path)
        block.wait()

    with patch("dev_server.main.run_plan_implement", side_effect=run_plan_with_on_start):
        client_with_tasks.post("/tasks/mytask/commands", json={"command": "plan-implement"})
    time.sleep(0.1)

    # End the command quickly so the stream closes and the test doesn't hang
    def end_command_soon() -> None:
        time.sleep(0.2)
        block.set()

    end_thread = threading.Thread(target=end_command_soon)
    end_thread.start()
    resp = client_with_tasks.get("/tasks/mytask/logs/stream")
    end_thread.join(timeout=1.0)

    assert resp.status_code == 200
    assert resp.headers.get("content-type", "").startswith("text/event-stream")
    body = resp.text
    assert "line one" in body or "line two" in body or "[stream ended]" in body
