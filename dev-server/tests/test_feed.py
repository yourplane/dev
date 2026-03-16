"""Tests for task feed API."""

import os
import zipfile
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from dev_sdk.feed import LOGS_DIR
from dev_sdk.comms import add_comms, comms_dir, index_path

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


def test_list_task_feed_empty(client_with_tasks: TestClient) -> None:
    resp = client_with_tasks.get("/tasks/mytask/feed")
    assert resp.status_code == 200
    assert resp.json()["entries"] == []


def test_list_task_feed_with_after(client_with_tasks: TestClient, task_dir: Path) -> None:
    comms_dir(task_dir).mkdir(parents=True)
    index_path(task_dir).write_text("001-user.md\n")
    (task_dir / "comms" / "001-user.md").write_text("Hello")
    (task_dir / LOGS_DIR).mkdir(parents=True)
    (task_dir / LOGS_DIR / "dev-20260314-120000.log").write_text("log")

    resp = client_with_tasks.get("/tasks/mytask/feed")
    assert resp.status_code == 200
    data = resp.json()
    entries = data["entries"]
    assert len(entries) >= 2

    # after= with value greater than all created_at returns empty
    max_ts = max(e["created_at"] for e in entries)
    resp2 = client_with_tasks.get(f"/tasks/mytask/feed?after={max_ts}")
    assert resp2.status_code == 200
    assert resp2.json()["entries"] == []

    # after=0 returns all entries (same as no param)
    resp3 = client_with_tasks.get("/tasks/mytask/feed?after=0")
    assert resp3.status_code == 200
    assert len(resp3.json()["entries"]) == len(entries)


def test_comms_download_returns_only_comms_no_logs(client_with_tasks: TestClient, task_dir: Path) -> None:
    """GET /tasks/{task_name}/comms/download returns a zip with comms files only (no agent logs)."""
    comms_dir(task_dir).mkdir(parents=True)
    index_path(task_dir).write_text("001-user.md\n002-agent-plan.md\n")
    (task_dir / "comms" / "001-user.md").write_text("User message")
    (task_dir / "comms" / "002-agent-plan.md").write_text("Agent plan")
    (task_dir / LOGS_DIR).mkdir(parents=True)
    (task_dir / LOGS_DIR / "dev-plan-stream-20260314-120000.log").write_text("agent log content")

    resp = client_with_tasks.get("/tasks/mytask/comms/download")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/zip"
    assert "mytask-comms.zip" in resp.headers.get("content-disposition", "")

    with zipfile.ZipFile(BytesIO(resp.content), "r") as zf:
        names = set(zf.namelist())
    assert "index.txt" in names
    assert "001-user.md" in names
    assert "002-agent-plan.md" in names
    assert not any(n.endswith(".log") or LOGS_DIR in n for n in names)


def test_comms_download_empty_returns_404(client_with_tasks: TestClient, task_dir: Path) -> None:
    """GET /tasks/{task_name}/comms/download returns 404 when there are no comms."""
    resp = client_with_tasks.get("/tasks/mytask/comms/download")
    assert resp.status_code == 404
    assert "No comms" in resp.json()["detail"]
