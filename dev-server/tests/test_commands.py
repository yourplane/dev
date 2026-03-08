"""Tests for async task commands API."""

import os
import subprocess
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from dev_server.main import app


@pytest.fixture
def task_dir(tmp_path: Path) -> Path:
    """Create a minimal task dir with agent-chat-id so start_agent_process can be called."""
    t = tmp_path / "mytask"
    t.mkdir()
    (t / "agent-chat-id").write_text("fake-chat-id")
    return t


@pytest.fixture
def client_with_tasks(task_dir: Path) -> TestClient:
    """TestClient with DEV_TASKS_DIR set so the task exists."""
    root = task_dir.parent
    with patch.dict(os.environ, {"DEV_TASKS_DIR": str(root)}, clear=False):
        yield TestClient(app)


def test_start_command_returns_201_and_status_active(client_with_tasks: TestClient, task_dir: Path) -> None:
    """Starting a command returns 201 and GET status shows active."""
    with patch("dev_server.main.start_agent_process") as mock_start:
        proc = subprocess.Popen(["sleep", "300"])
        mock_start.return_value = (proc, task_dir / ".logs" / "x.log")
        resp = client_with_tasks.post(
            "/tasks/mytask/commands",
            json={"command": "plan-implement"},
        )
    assert resp.status_code == 201
    data = resp.json()
    assert data["command"] == "plan-implement"
    assert data["status"] == "running"

    resp2 = client_with_tasks.get("/tasks/mytask/commands")
    assert resp2.status_code == 200
    assert resp2.json()["active"] is True
    assert resp2.json()["command"] == "plan-implement"

    proc.kill()
    proc.wait()


def test_start_command_again_returns_409(client_with_tasks: TestClient, task_dir: Path) -> None:
    """Starting a second command while one is running returns 409."""
    with patch("dev_server.main.start_agent_process") as mock_start:
        proc = subprocess.Popen(["sleep", "300"])
        mock_start.return_value = (proc, task_dir / ".logs" / "x.log")
        client_with_tasks.post("/tasks/mytask/commands", json={"command": "implement"})
        resp = client_with_tasks.post("/tasks/mytask/commands", json={"command": "plan-implement"})
    assert resp.status_code == 409
    assert "already running" in resp.json()["detail"]
    proc.kill()
    proc.wait()


def test_status_inactive_after_process_exits(client_with_tasks: TestClient, task_dir: Path) -> None:
    """After the started process exits, status becomes inactive."""
    with patch("dev_server.main.start_agent_process") as mock_start:
        proc = subprocess.Popen(["true"])
        proc.wait()
        mock_start.return_value = (proc, task_dir / ".logs" / "x.log")
        client_with_tasks.post("/tasks/mytask/commands", json={"command": "implement"})
    time.sleep(0.3)
    resp = client_with_tasks.get("/tasks/mytask/commands")
    assert resp.status_code == 200
    assert resp.json()["active"] is False
    assert resp.json()["command"] is None


def test_start_unsupported_command_returns_400(client_with_tasks: TestClient) -> None:
    """Unsupported command returns 400."""
    resp = client_with_tasks.post("/tasks/mytask/commands", json={"command": "plan-test"})
    assert resp.status_code == 400
    assert "Unsupported" in resp.json()["detail"]


def test_get_commands_404_for_nonexistent_task(client_with_tasks: TestClient) -> None:
    """GET commands for nonexistent task returns 404."""
    resp = client_with_tasks.get("/tasks/nonexistent/commands")
    assert resp.status_code == 404
