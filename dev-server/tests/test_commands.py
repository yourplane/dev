"""Tests for async task commands API."""

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
    """Create a minimal task dir with agent-chat-id so run_plan_implement/run_implement can be called."""
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
    """Starting a command returns 201 and GET status shows active until the run finishes."""
    block = threading.Event()

    def blocking_run_plan(*args: object, **kwargs: object) -> None:
        block.wait()

    with patch("dev_server.main.run_plan_implement", side_effect=blocking_run_plan):
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
    # active_log_filename is set only after on_start is called by the real run; with mock it stays None
    assert "active_log_filename" in resp2.json()

    block.set()
    time.sleep(0.3)
    resp3 = client_with_tasks.get("/tasks/mytask/commands")
    assert resp3.status_code == 200
    assert resp3.json()["active"] is False


def test_start_command_again_returns_409(client_with_tasks: TestClient, task_dir: Path) -> None:
    """Starting a second command while one is running returns 409."""
    block = threading.Event()

    def blocking_run_implement(*args: object, **kwargs: object) -> None:
        block.wait()

    with patch("dev_server.main.run_implement", side_effect=blocking_run_implement):
        client_with_tasks.post("/tasks/mytask/commands", json={"command": "implement"})
        resp = client_with_tasks.post("/tasks/mytask/commands", json={"command": "plan-implement"})
    assert resp.status_code == 409
    assert "already running" in resp.json()["detail"]
    block.set()


def test_status_inactive_after_process_exits(client_with_tasks: TestClient, task_dir: Path) -> None:
    """After the run finishes, status becomes inactive."""
    with patch("dev_server.main.run_implement") as mock_run:
        mock_run.return_value = None
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


def test_start_do_requires_prompt_returns_400(client_with_tasks: TestClient) -> None:
    """Starting do without prompt returns 400."""
    resp = client_with_tasks.post("/tasks/mytask/commands", json={"command": "do"})
    assert resp.status_code == 400
    assert "prompt" in resp.json()["detail"].lower()


def test_start_do_empty_prompt_returns_400(client_with_tasks: TestClient) -> None:
    """Starting do with empty prompt returns 400."""
    resp = client_with_tasks.post("/tasks/mytask/commands", json={"command": "do", "prompt": "   "})
    assert resp.status_code == 400
    assert "prompt" in resp.json()["detail"].lower()


def test_start_do_returns_201_and_status_active(
    client_with_tasks: TestClient, task_dir: Path
) -> None:
    """Starting do returns 201 and GET status shows active while the run is blocking."""
    block = threading.Event()
    received: dict[str, object] = {}

    def blocking_run_do(*args: object, **kwargs: object) -> None:
        received["prompt"] = kwargs.get("prompt")
        # The real runner would call on_start; this mock intentionally blocks.
        block.wait()
        block.set()

    with patch("dev_server.main.run_do", side_effect=blocking_run_do):
        resp = client_with_tasks.post(
            "/tasks/mytask/commands",
            json={"command": "do", "prompt": "DO-PROMPT"},
        )

    assert resp.status_code == 201
    data = resp.json()
    assert data["command"] == "do"
    assert data["status"] == "running"
    assert received["prompt"] == "DO-PROMPT"

    resp2 = client_with_tasks.get("/tasks/mytask/commands")
    assert resp2.status_code == 200
    assert resp2.json()["active"] is True
    assert resp2.json()["command"] == "do"
    assert "active_log_filename" in resp2.json()

    # Release the blocking runner and wait for command completion.
    block.set()
    time.sleep(0.3)
    resp3 = client_with_tasks.get("/tasks/mytask/commands")
    assert resp3.status_code == 200
    assert resp3.json()["active"] is False


def test_start_do_clears_comment_draft(client_with_tasks: TestClient, task_dir: Path) -> None:
    """Starting a do command clears the persisted comment draft for the task."""
    root = task_dir.parent
    drafts_dir = root / ".drafts"
    drafts_dir.mkdir(exist_ok=True)
    (drafts_dir / "comment-mytask").write_text("my draft comment")

    with patch("dev_server.main.run_do"):
        resp = client_with_tasks.post(
            "/tasks/mytask/commands",
            json={"command": "do", "prompt": "DO-PROMPT"},
        )
    assert resp.status_code == 201

    resp2 = client_with_tasks.get("/tasks/mytask/drafts/comment")
    assert resp2.status_code == 200
    assert resp2.text == ""


def test_get_commands_404_for_nonexistent_task(client_with_tasks: TestClient) -> None:
    """GET commands for nonexistent task returns 404."""
    resp = client_with_tasks.get("/tasks/nonexistent/commands")
    assert resp.status_code == 404


def test_cancel_command_sets_event_and_status_becomes_inactive(
    client_with_tasks: TestClient, task_dir: Path
) -> None:
    """POST cancel sets cancel event; blocking run receives it and exits, status becomes inactive."""
    run_finished = threading.Event()

    def blocking_until_cancel(*args: object, cancel_event: threading.Event | None = None, **kwargs: object) -> None:
        (cancel_event or threading.Event()).wait()
        run_finished.set()

    with patch("dev_server.main.run_plan_implement", side_effect=blocking_until_cancel):
        resp = client_with_tasks.post(
            "/tasks/mytask/commands",
            json={"command": "plan-implement"},
        )
    assert resp.status_code == 201

    resp2 = client_with_tasks.get("/tasks/mytask/commands")
    assert resp2.status_code == 200
    assert resp2.json()["active"] is True

    resp_cancel = client_with_tasks.post("/tasks/mytask/commands/cancel")
    assert resp_cancel.status_code == 204

    run_finished.wait(timeout=2.0)
    time.sleep(0.2)
    resp3 = client_with_tasks.get("/tasks/mytask/commands")
    assert resp3.status_code == 200
    assert resp3.json()["active"] is False


def test_cancel_command_404_when_no_command_running(client_with_tasks: TestClient, task_dir: Path) -> None:
    """POST cancel when no command is running returns 404."""
    resp = client_with_tasks.post("/tasks/mytask/commands/cancel")
    assert resp.status_code == 404
    assert "No command" in resp.json()["detail"]


def test_create_pr_returns_pr_url(client_with_tasks: TestClient, task_dir: Path) -> None:
    """POST create-pr returns 200 and pr_url when create_pull_request succeeds."""
    with patch("dev_server.main.create_pull_request", return_value="https://github.com/owner/repo/pull/1"):
        resp = client_with_tasks.post("/tasks/mytask/create-pr")
    assert resp.status_code == 200
    assert resp.json()["pr_url"] == "https://github.com/owner/repo/pull/1"


def test_create_pr_returns_422_on_error(client_with_tasks: TestClient, task_dir: Path) -> None:
    """POST create-pr returns 422 with detail when create_pull_request raises CreatePRError."""
    from dev_sdk.create_pr import CreatePRError

    with patch("dev_server.main.create_pull_request", side_effect=CreatePRError("Create PR from a feature branch, not main.")):
        resp = client_with_tasks.post("/tasks/mytask/create-pr")
    assert resp.status_code == 422
    assert "feature branch" in resp.json()["detail"]


def test_get_pr_returns_pr_url(client_with_tasks: TestClient, task_dir: Path) -> None:
    """GET pr returns 200 and pr_url when a PR already exists."""
    with patch(
        "dev_server.main.find_existing_pull_request",
        return_value="https://github.com/owner/repo/pull/1",
    ):
        resp = client_with_tasks.get("/tasks/mytask/pr")
    assert resp.status_code == 200
    assert resp.json()["pr_url"] == "https://github.com/owner/repo/pull/1"


def test_get_pr_returns_null_when_not_found(client_with_tasks: TestClient, task_dir: Path) -> None:
    """GET pr returns pr_url: null when no PR exists."""
    with patch("dev_server.main.find_existing_pull_request", return_value=None):
        resp = client_with_tasks.get("/tasks/mytask/pr")
    assert resp.status_code == 200
    assert resp.json()["pr_url"] is None


def test_get_pr_returns_422_on_error(client_with_tasks: TestClient, task_dir: Path) -> None:
    """GET pr returns 422 with detail when lookup raises CreatePRError."""
    from dev_sdk.create_pr import CreatePRError

    with patch("dev_server.main.find_existing_pull_request", side_effect=CreatePRError("GitHub API error: boom")):
        resp = client_with_tasks.get("/tasks/mytask/pr")
    assert resp.status_code == 422
    assert "boom" in resp.json()["detail"]
