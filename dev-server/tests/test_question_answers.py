"""Tests for question-answers API."""

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from dev_server.main import app


@pytest.fixture
def tasks_root(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def client(tasks_root: Path) -> TestClient:
    with patch.dict(os.environ, {"DEV_TASKS_DIR": str(tasks_root)}, clear=False):
        yield TestClient(app)


@pytest.fixture
def task_with_question(task_dir: Path) -> Path:
    comms = task_dir / "comms"
    comms.mkdir()
    (comms / "index.txt").write_text("001-agent-question.md\n")
    payload = {
        "intro": "Pick one",
        "questions": [{"id": "q1", "text": "Which?", "options": ["A", "B"]}],
    }
    (comms / "001-agent-question.md").write_text(json.dumps(payload, indent=2))
    return task_dir


@pytest.fixture
def task_dir(tasks_root: Path) -> Path:
    t = tasks_root / "mytask"
    t.mkdir()
    return t


def test_post_question_answers_creates_comms(client: TestClient, task_with_question: Path) -> None:
    resp = client.post(
        "/tasks/mytask/comms/question-answers",
        json={
            "source": "001-agent-question.md",
            "answers": [{"id": "q1", "text": "Which?", "selected": "A", "free_text": ""}],
        },
    )
    assert resp.status_code == 201
    filename = resp.json()["filename"]
    assert filename.endswith("-user-answers.md")
    content = (task_with_question / "comms" / filename).read_text()
    assert "Source: `001-agent-question.md`" in content
    assert "**Selected:** A" in content
    index = (task_with_question / "comms" / "index.txt").read_text()
    assert filename in index


def test_question_answers_draft_roundtrip(client: TestClient, task_dir: Path, tasks_root: Path) -> None:
    resp = client.put(
        "/tasks/mytask/drafts/question-answers/002-agent-question.md",
        json={"selections": {"q1": "B"}, "freeText": {"q1": "notes"}, "expandedFreeText": {"q1": True}},
    )
    assert resp.status_code == 204
    draft_file = tasks_root / ".drafts" / "question-answers-mytask-002-agent-question.md"
    assert draft_file.is_file()

    resp2 = client.get("/tasks/mytask/drafts/question-answers/002-agent-question.md")
    assert resp2.status_code == 200
    data = resp2.json()
    assert data["selections"]["q1"] == "B"
    assert data["freeText"]["q1"] == "notes"


def test_question_answers_editing_flag_keeps_empty_draft(client: TestClient, task_dir: Path, tasks_root: Path) -> None:
    resp = client.put(
        "/tasks/mytask/drafts/question-answers/002-agent-question.md",
        json={"selections": {}, "freeText": {}, "expandedFreeText": {}, "editing": True},
    )
    assert resp.status_code == 204
    draft_file = tasks_root / ".drafts" / "question-answers-mytask-002-agent-question.md"
    assert draft_file.is_file()

    resp2 = client.get("/tasks/mytask/drafts/question-answers/002-agent-question.md")
    assert resp2.status_code == 200
    assert resp2.json()["editing"] is True


def test_post_question_answers_clears_draft(client: TestClient, task_with_question: Path, tasks_root: Path) -> None:
    client.put(
        "/tasks/mytask/drafts/question-answers/001-agent-question.md",
        json={"selections": {"q1": "A"}, "freeText": {}, "expandedFreeText": {}},
    )
    draft_file = tasks_root / ".drafts" / "question-answers-mytask-001-agent-question.md"
    assert draft_file.is_file()

    client.post(
        "/tasks/mytask/comms/question-answers",
        json={
            "source": "001-agent-question.md",
            "answers": [{"id": "q1", "text": "Which?", "selected": "A", "free_text": ""}],
        },
    )
    assert not draft_file.exists()
