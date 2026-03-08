"""Tests for comms module."""

from pathlib import Path

import pytest

from dev_sdk.comms import (
    add_comms,
    comms_dir,
    next_sequence,
    read_index,
    read_comms_content,
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


@pytest.fixture
def task_dir(tmp_path: Path) -> Path:
    return tmp_path / "task"
