"""Tests for GET /tasks with per-task status."""

import os
import threading
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from dev_sdk.comms import add_comms
from dev_server.main import app


@pytest.fixture
def task_dir(tmp_path: Path) -> Path:
    t = tmp_path / "mytask"
    t.mkdir()
    (t / "agent-chat-id").write_text("fake-chat-id")
    repo = t / "myrepo"
    repo.mkdir()
    (repo / ".git").mkdir()
    return t


@pytest.fixture
def client_with_tasks(task_dir: Path) -> TestClient:
    root = task_dir.parent
    with patch.dict(os.environ, {"DEV_TASKS_DIR": str(root)}, clear=False):
        yield TestClient(app)


def test_list_tasks_returns_name_and_status(client_with_tasks: TestClient, task_dir: Path) -> None:
    resp = client_with_tasks.get("/tasks")
    assert resp.status_code == 200
    data = resp.json()
    assert data["tasks"] == [{"name": "mytask", "status": "idle"}]


def test_list_tasks_waiting_for_answers(client_with_tasks: TestClient, task_dir: Path) -> None:
    add_comms(task_dir, "user", "hello")
    add_comms(task_dir, "agent", "questions?", kind="question")

    resp = client_with_tasks.get("/tasks")
    assert resp.json()["tasks"][0]["status"] == "waiting_for_answers"


def test_list_tasks_plan_complete(client_with_tasks: TestClient, task_dir: Path) -> None:
    add_comms(task_dir, "agent", "plan done", kind="plan")

    resp = client_with_tasks.get("/tasks")
    assert resp.json()["tasks"][0]["status"] == "plan_complete"


def test_list_tasks_running_command(client_with_tasks: TestClient, task_dir: Path) -> None:
    block = threading.Event()

    def blocking_run_plan(*args: object, **kwargs: object) -> None:
        block.wait()

    with patch("dev_server.main.run_plan_implement", side_effect=blocking_run_plan):
        client_with_tasks.post("/tasks/mytask/commands", json={"command": "plan-implement"})

    resp = client_with_tasks.get("/tasks")
    assert resp.json()["tasks"][0]["status"] == "running"
    block.set()


def test_list_tasks_failed_command(client_with_tasks: TestClient, task_dir: Path) -> None:
    from dev_sdk.agent_run import AgentRunError

    with patch("dev_server.main.run_implement", side_effect=AgentRunError("agent boom")):
        client_with_tasks.post("/tasks/mytask/commands", json={"command": "implement"})

    import time

    time.sleep(0.3)
    resp = client_with_tasks.get("/tasks")
    assert resp.json()["tasks"][0]["status"] == "failed"


def test_list_tasks_cancelled_is_idle(client_with_tasks: TestClient, task_dir: Path) -> None:
    block = threading.Event()

    def blocking_run(*args: object, **kwargs: object) -> None:
        block.wait()

    with patch("dev_server.main.run_implement", side_effect=blocking_run):
        client_with_tasks.post("/tasks/mytask/commands", json={"command": "implement"})
    client_with_tasks.post("/tasks/mytask/commands/cancel")
    block.set()

    import time

    time.sleep(0.3)
    resp = client_with_tasks.get("/tasks")
    assert resp.json()["tasks"][0]["status"] == "idle"
