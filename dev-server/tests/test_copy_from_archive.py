"""Tests for copy-from-archive API."""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from dev_server.main import app


@pytest.fixture
def tasks_root(tmp_path: Path) -> Path:
    root = tmp_path / "tasks"
    root.mkdir()
    return root


@pytest.fixture
def archived_task(tasks_root: Path) -> Path:
    """Create an archived task with comms, .logs, agent-chat-id."""
    archive_root = tasks_root / ".archive"
    archive_root.mkdir()
    archived = archive_root / "my-task-mar-14-a1b2c3"
    archived.mkdir()
    (archived / "comms").mkdir()
    (archived / "comms" / "index.txt").write_text("001-user.md\n")
    (archived / "comms" / "001-user.md").write_text("# Task\n")
    (archived / ".cursor" / "rules").mkdir(parents=True)
    (archived / ".cursor" / "rules" / "task-comms.mdc").write_text("rule")
    (archived / ".cursor" / "rules" / "git-workspace.mdc").write_text("git rule")
    (archived / ".logs").mkdir()
    (archived / ".logs" / "dev-plan-20260314.log").write_text("log content")
    (archived / "agent-chat-id").write_text("old-chat-id")
    return archived


@pytest.fixture
def client_with_archive(tasks_root: Path, archived_task: Path) -> TestClient:
    with patch.dict(os.environ, {"DEV_TASKS_DIR": str(tasks_root)}, clear=False):
        yield TestClient(app)


@patch("dev_sdk.task_manager.subprocess.run")
def test_copy_from_archive_creates_task(
    mock_run: MagicMock,
    client_with_archive: TestClient,
    tasks_root: Path,
    archived_task: Path,
) -> None:
    mock_run.return_value = MagicMock(stdout="new-chat-id-789\n", stderr="", returncode=0)

    resp = client_with_archive.post("/archive/my-task-mar-14-a1b2c3/copy")

    assert resp.status_code == 201
    data = resp.json()
    assert data["task_name"] == "my-task"
    assert "my-task" in data["task_dir"]
    dest = tasks_root / "my-task"
    assert dest.is_dir()
    assert (dest / "comms" / "index.txt").read_text() == "001-user.md\n"
    assert (dest / "comms" / "001-user.md").read_text() == "# Task\n"
    assert (dest / "agent-chat-id").read_text().strip() == "new-chat-id-789"
    assert not (dest / ".logs").exists()
    assert archived_task.is_dir()


@patch("dev_sdk.task_manager.subprocess.run")
def test_copy_from_archive_conflict_when_task_exists(
    mock_run: MagicMock,
    client_with_archive: TestClient,
    tasks_root: Path,
) -> None:
    (tasks_root / "my-task").mkdir()
    mock_run.return_value = MagicMock(stdout="chat-id\n", stderr="", returncode=0)

    resp = client_with_archive.post("/archive/my-task-mar-14-a1b2c3/copy")

    assert resp.status_code == 409
    assert "already exists" in resp.json().get("detail", "").lower()


def test_copy_from_archive_not_found(client_with_archive: TestClient) -> None:
    resp = client_with_archive.post("/archive/nonexistent-mar-14-abcdef/copy")
    assert resp.status_code == 404
