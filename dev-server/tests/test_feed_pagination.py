"""Tests for task feed API pagination."""

import os
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from dev_sdk.comms import index_path
from dev_server.main import app


@pytest.fixture
def task_dir(tmp_path: Path) -> Path:
    t = tmp_path / "mytask"
    t.mkdir()
    return t


@pytest.fixture
def client_with_tasks(task_dir: Path) -> TestClient:
    root = task_dir.parent
    with patch.dict("os.environ", {"DEV_TASKS_DIR": str(root)}, clear=False):
        yield TestClient(app)


def _seed_comms(task_dir: Path, count: int) -> None:
    (task_dir / "comms").mkdir(parents=True)
    names = [f"{i:03d}-user.md" for i in range(1, count + 1)]
    index_path(task_dir).write_text("\n".join(names) + "\n")
    for i, name in enumerate(names, start=1):
        path = task_dir / "comms" / name
        path.write_text(f"msg {i}")
        os.utime(path, (float(i), float(i)))


def test_feed_pagination_newest_page(client_with_tasks: TestClient, task_dir: Path) -> None:
    _seed_comms(task_dir, 75)
    resp = client_with_tasks.get("/tasks/mytask/feed", params={"limit": 50})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 75
    assert body["has_older"] is True
    assert len(body["entries"]) == 50
    assert body["entries"][0]["id"] == "026-user.md"
    assert body["entries"][-1]["id"] == "075-user.md"
    assert body["oldest_cursor"]["id"] == "026-user.md"


def test_feed_pagination_load_older(client_with_tasks: TestClient, task_dir: Path) -> None:
    _seed_comms(task_dir, 75)
    first = client_with_tasks.get("/tasks/mytask/feed", params={"limit": 50}).json()
    cursor = first["oldest_cursor"]
    second = client_with_tasks.get(
        "/tasks/mytask/feed",
        params={
            "limit": 50,
            "before_created_at": cursor["created_at"],
            "before_id": cursor["id"],
        },
    )
    assert second.status_code == 200
    body = second.json()
    assert body["has_older"] is False
    assert len(body["entries"]) == 25
    assert body["entries"][0]["id"] == "001-user.md"


def test_feed_without_limit_backward_compatible(client_with_tasks: TestClient, task_dir: Path) -> None:
    _seed_comms(task_dir, 3)
    resp = client_with_tasks.get("/tasks/mytask/feed")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["entries"]) == 3
    assert body.get("total") is None
    assert body.get("has_older") is None


def test_feed_deletable_endpoint(client_with_tasks: TestClient, task_dir: Path) -> None:
    import json

    from dev_sdk.feed import LOGS_DIR

    (task_dir / "comms").mkdir(parents=True)
    index_path(task_dir).write_text("001-user.md\n002-user.md\n")
    (task_dir / "comms" / "001-user.md").write_text("Old")
    (task_dir / "comms" / "002-user.md").write_text("New")
    (task_dir / LOGS_DIR).mkdir(parents=True)
    (task_dir / LOGS_DIR / "dev.log").write_text(
        json.dumps({"type": "thinking", "timestamp_ms": 5_000_000}) + "\n",
        encoding="utf-8",
    )
    os.utime(task_dir / "comms" / "001-user.md", (1, 1))
    os.utime(task_dir / "comms" / "002-user.md", (10_000, 10_000))

    resp = client_with_tasks.get("/tasks/mytask/feed/deletable")
    assert resp.status_code == 200
    assert resp.json() == {"001-user.md": False, "002-user.md": True}
