"""Tests for draft API (new-task and task comment drafts)."""

import os
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from dev_server.main import app


@pytest.fixture
def tasks_root(tmp_path: Path) -> Path:
    """Tasks root (no tasks created)."""
    return tmp_path


@pytest.fixture
def client(tasks_root: Path) -> TestClient:
    """TestClient with DEV_TASKS_DIR set."""
    with patch.dict(os.environ, {"DEV_TASKS_DIR": str(tasks_root)}, clear=False):
        yield TestClient(app)


@pytest.fixture
def task_dir(tasks_root: Path) -> Path:
    """Create a minimal task dir."""
    t = tasks_root / "mytask"
    t.mkdir()
    return t


def test_new_task_draft_get_empty(client: TestClient) -> None:
    """GET /drafts/new-task returns empty when no draft."""
    resp = client.get("/drafts/new-task")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("title") is None
    assert data.get("repo") is None
    assert data.get("comment") is None


def test_new_task_draft_put_and_get(client: TestClient, tasks_root: Path) -> None:
    """PUT /drafts/new-task saves and GET returns it."""
    resp = client.put(
        "/drafts/new-task",
        json={"title": "My task", "repo": "myrepo", "comment": "Do the thing."},
    )
    assert resp.status_code == 204

    resp2 = client.get("/drafts/new-task")
    assert resp2.status_code == 200
    data = resp2.json()
    assert data["title"] == "My task"
    assert data["repo"] == "myrepo"
    assert data["comment"] == "Do the thing."

    draft_file = tasks_root / ".drafts" / "new-task.json"
    assert draft_file.is_file()


def test_new_task_draft_put_empty_clears(client: TestClient, tasks_root: Path) -> None:
    """PUT with empty body clears the draft."""
    client.put("/drafts/new-task", json={"title": "X", "repo": "r", "comment": "c"})
    client.put("/drafts/new-task", json={})
    resp = client.get("/drafts/new-task")
    assert resp.status_code == 200
    assert resp.json().get("title") is None
    assert not (tasks_root / ".drafts" / "new-task.json").exists()


def test_task_comment_draft_get_empty(client: TestClient, task_dir: Path) -> None:
    """GET task comment draft returns empty when none."""
    resp = client.get("/tasks/mytask/drafts/comment")
    assert resp.status_code == 200
    assert resp.text == ""


def test_task_comment_draft_put_and_get(client: TestClient, task_dir: Path, tasks_root: Path) -> None:
    """PUT task comment draft saves and GET returns it. Draft lives in server .drafts, not task dir."""
    resp = client.put(
        "/tasks/mytask/drafts/comment",
        json={"content": "My comment draft."},
    )
    assert resp.status_code == 204

    resp2 = client.get("/tasks/mytask/drafts/comment")
    assert resp2.status_code == 200
    assert resp2.text == "My comment draft."

    draft_file = tasks_root / ".drafts" / "comment-mytask"
    assert draft_file.is_file()
    assert draft_file.read_text() == "My comment draft."
    assert not (task_dir / ".drafts").exists()


def test_task_comment_draft_put_empty_clears(client: TestClient, task_dir: Path, tasks_root: Path) -> None:
    """PUT with empty content clears the comment draft."""
    client.put("/tasks/mytask/drafts/comment", json={"content": "something"})
    client.put("/tasks/mytask/drafts/comment", json={"content": ""})
    resp = client.get("/tasks/mytask/drafts/comment")
    assert resp.status_code == 200
    assert resp.text == ""
    assert not (tasks_root / ".drafts" / "comment-mytask").exists()


def test_task_comment_draft_404_for_nonexistent_task(client: TestClient) -> None:
    """GET/PUT comment draft for nonexistent task returns 404."""
    resp = client.get("/tasks/nonexistent/drafts/comment")
    assert resp.status_code == 404
    resp2 = client.put("/tasks/nonexistent/drafts/comment", json={"content": "x"})
    assert resp2.status_code == 404
