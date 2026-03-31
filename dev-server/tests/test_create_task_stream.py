"""POST /tasks streams NDJSON progress lines (same as CLI on_progress), then complete or error."""

import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DEV_TASKS_DIR", str(tmp_path))
    from dev_server.main import app

    return TestClient(app)


def test_create_task_streams_progress_then_complete(client):
    manager = MagicMock()

    def start_task(**kwargs):
        on = kwargs.get("on_progress")
        if on:
            on("Created task directory.")
            on("Comms directory ready.")

    manager.start_task.side_effect = start_task

    with patch("dev_server.main._get_manager", return_value=manager):
        resp = client.post(
            "/tasks",
            json={"title": "My Task", "repo": "https://github.com/u/r.git"},
        )

    assert resp.status_code == 200
    lines = [json.loads(line) for line in resp.text.strip().split("\n") if line.strip()]
    assert [x["type"] for x in lines] == ["progress", "progress", "complete"]
    assert lines[0]["message"] == "Created task directory."
    assert lines[1]["message"] == "Comms directory ready."
    assert lines[2]["type"] == "complete"
    assert lines[2]["task_name"] == "my-task"
    assert "task_dir" in lines[2]


def test_create_task_streams_error(client):
    manager = MagicMock()
    manager.start_task.side_effect = FileExistsError()

    with patch("dev_server.main._get_manager", return_value=manager):
        resp = client.post(
            "/tasks",
            json={"title": "My Task", "repo": "https://github.com/u/r.git"},
        )

    assert resp.status_code == 200
    lines = [json.loads(line) for line in resp.text.strip().split("\n") if line.strip()]
    assert len(lines) == 1
    assert lines[0]["type"] == "error"
    assert lines[0]["status"] == 409
    assert "already exists" in lines[0]["detail"]
