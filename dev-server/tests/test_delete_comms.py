"""Tests for DELETE task comms API."""

import os
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from dev_sdk.comms import add_comms, comms_dir, index_path, read_index
from dev_sdk.feed import LOGS_DIR

from dev_server.main import app


@pytest.fixture
def task_dir(tmp_path: Path) -> Path:
    t = tmp_path / "mytask"
    t.mkdir()
    return t


@pytest.fixture
def client_with_tasks(task_dir: Path) -> TestClient:
    root = task_dir.parent
    with patch.dict(os.environ, {"DEV_TASKS_DIR": str(root)}, clear=False):
        yield TestClient(app)


def test_delete_comms_when_no_agent_logs(client_with_tasks: TestClient, task_dir: Path) -> None:
    comms_dir(task_dir).mkdir(parents=True)
    add_comms(task_dir, "user", "Hello")
    add_comms(task_dir, "agent", "Plan", kind="plan")
    assert read_index(task_dir) == ["001-user.md", "002-agent-plan.md"]

    resp = client_with_tasks.delete("/tasks/mytask/comms/001-user.md")

    assert resp.status_code == 204
    assert not (task_dir / "comms" / "001-user.md").exists()
    assert read_index(task_dir) == ["002-agent-plan.md"]


def test_delete_comms_when_agent_logs_returns_400(client_with_tasks: TestClient, task_dir: Path) -> None:
    comms_dir(task_dir).mkdir(parents=True)
    add_comms(task_dir, "user", "Hello")
    (task_dir / LOGS_DIR).mkdir(parents=True)
    (task_dir / LOGS_DIR / "dev.log").write_text("log")

    resp = client_with_tasks.delete("/tasks/mytask/comms/001-user.md")

    assert resp.status_code == 400
    assert "agent logs" in resp.json()["detail"].lower()
    assert (task_dir / "comms" / "001-user.md").exists()


def test_delete_comms_invalid_filename_returns_404(client_with_tasks: TestClient, task_dir: Path) -> None:
    comms_dir(task_dir).mkdir(parents=True)
    resp = client_with_tasks.delete("/tasks/mytask/comms/../../../etc/passwd")
    assert resp.status_code == 404
