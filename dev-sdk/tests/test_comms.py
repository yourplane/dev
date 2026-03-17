"""Tests for comms module."""

from pathlib import Path

import pytest

from dev_sdk.comms import (
    add_comms,
    comms_dir,
    has_agent_logs,
    next_sequence,
    read_index,
    read_comms_content,
    remove_comms,
)


def test_comms_dir(task_dir: Path) -> None:
    assert comms_dir(task_dir) == task_dir / "comms"


def test_add_comms_and_read_index(task_dir: Path) -> None:
    (task_dir / "comms").mkdir(parents=True)
    p1 = add_comms(task_dir, "user", "Hello")
    assert p1.name == "001-user.md"
    assert p1.read_text().strip() == "Hello"
    assert read_index(task_dir) == ["001-user.md"]
    p2 = add_comms(task_dir, "agent", "Plan:", kind="plan")
    assert p2.name == "002-agent-plan.md"
    assert read_index(task_dir) == ["001-user.md", "002-agent-plan.md"]


def test_next_sequence(task_dir: Path) -> None:
    (task_dir / "comms").mkdir(parents=True)
    assert next_sequence(task_dir) == 1
    add_comms(task_dir, "user", "x")
    assert next_sequence(task_dir) == 2


def test_read_comms_content(task_dir: Path) -> None:
    (task_dir / "comms").mkdir(parents=True)
    add_comms(task_dir, "user", "First")
    add_comms(task_dir, "agent", "Second")
    content = read_comms_content(task_dir)
    assert "First" in content and "Second" in content
    assert "---" in content


def test_has_agent_logs_false_when_no_logs_dir(task_dir: Path) -> None:
    assert has_agent_logs(task_dir) is False


def test_has_agent_logs_false_when_logs_dir_empty(task_dir: Path) -> None:
    (task_dir / ".logs").mkdir(parents=True)
    assert has_agent_logs(task_dir) is False


def test_has_agent_logs_true_when_log_file_exists(task_dir: Path) -> None:
    (task_dir / ".logs").mkdir(parents=True)
    (task_dir / ".logs" / "dev-plan-20260314.log").write_text("log")
    assert has_agent_logs(task_dir) is True


def test_remove_comms_when_no_agent_logs(task_dir: Path) -> None:
    (task_dir / "comms").mkdir(parents=True)
    add_comms(task_dir, "user", "Hello")
    add_comms(task_dir, "agent", "Plan", kind="plan")
    assert read_index(task_dir) == ["001-user.md", "002-agent-plan.md"]
    remove_comms(task_dir, "001-user.md")
    assert (task_dir / "comms" / "001-user.md").exists() is False
    assert read_index(task_dir) == ["002-agent-plan.md"]


def test_remove_comms_when_agent_logs_raises(task_dir: Path) -> None:
    (task_dir / "comms").mkdir(parents=True)
    add_comms(task_dir, "user", "Hello")
    (task_dir / ".logs").mkdir()
    (task_dir / ".logs" / "dev.log").write_text("x")
    with pytest.raises(ValueError, match="Cannot remove comms when the task has agent logs"):
        remove_comms(task_dir, "001-user.md")


def test_remove_comms_invalid_filename_raises(task_dir: Path) -> None:
    (task_dir / "comms").mkdir(parents=True)
    with pytest.raises(ValueError, match="Invalid filename"):
        remove_comms(task_dir, "../other/file.md")
    with pytest.raises(ValueError, match="Invalid filename"):
        remove_comms(task_dir, "")


def test_remove_comms_idempotent_when_file_missing_but_in_index(task_dir: Path) -> None:
    (task_dir / "comms").mkdir(parents=True)
    index_path = task_dir / "comms" / "index.txt"
    index_path.write_text("001-user.md\n002-agent-plan.md\n")
    (task_dir / "comms" / "002-agent-plan.md").write_text("Plan")
    remove_comms(task_dir, "001-user.md")
    assert read_index(task_dir) == ["002-agent-plan.md"]


@pytest.fixture
def task_dir(tmp_path: Path) -> Path:
    return tmp_path / "task"
