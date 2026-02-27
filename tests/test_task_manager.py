"""Tests for TaskManager."""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from dev.task_manager import TaskManager


@pytest.fixture
def tmp_tasks_root(tmp_path: Path) -> Path:
    return tmp_path / "tasks"


@pytest.fixture
def manager(tmp_tasks_root: Path) -> TaskManager:
    return TaskManager(tasks_root=tmp_tasks_root)


def test_parse_chat_id_single_line(manager: TaskManager) -> None:
    assert manager._parse_chat_id("abc-123-uuid") == "abc-123-uuid"


def test_parse_chat_id_multiple_lines(manager: TaskManager) -> None:
    output = "Some header\nChat created.\nabc-123-uuid"
    assert manager._parse_chat_id(output) == "abc-123-uuid"


def test_parse_chat_id_empty_raises(manager: TaskManager) -> None:
    with pytest.raises(ValueError, match="No output"):
        manager._parse_chat_id("")


def test_write_task_file(manager: TaskManager, tmp_tasks_root: Path) -> None:
    task_dir = tmp_tasks_root / "my-task"
    task_dir.mkdir(parents=True)
    manager._write_task_file(task_dir, "My Title", "Do the thing.")
    path = task_dir / "task.md"
    assert path.read_text() == "# My Title\n\nDo the thing.\n"


def test_write_launch_script(manager: TaskManager, tmp_tasks_root: Path) -> None:
    task_dir = tmp_tasks_root / "my-task"
    task_dir.mkdir(parents=True)
    manager._write_launch_script(task_dir, "cursor", "chat-uuid-123")
    path = task_dir / "launch-agent.sh"
    content = path.read_text()
    assert "cursor agent chat chat-uuid-123" in content
    assert path.stat().st_mode & 0o111


@patch("dev.task_manager.subprocess.run")
def test_start_task(
    mock_run: MagicMock,
    manager: TaskManager,
    tmp_tasks_root: Path,
) -> None:
    def run_side_effect(cmd, **kwargs):
        if cmd[0] == "cursor" and "create-chat" in cmd:
            return MagicMock(stdout="Chat created.\nmy-chat-id-456\n", stderr="", returncode=0)
        if cmd[0] == "git" and cmd[1] == "clone":
            (tmp_tasks_root / "my-task" / "my-task").mkdir(parents=True)
            return MagicMock(returncode=0)
        raise NotImplementedError(cmd)

    mock_run.side_effect = run_side_effect

    manager.start_task(
        title="My Task",
        task_name="my-task",
        description="Build the feature.",
        repo_url="https://github.com/user/repo.git",
        agent_cmd="cursor",
        agent_create_chat_args=["agent", "create-chat"],
    )

    task_dir = tmp_tasks_root / "my-task"
    assert (task_dir / "task.md").read_text() == "# My Task\n\nBuild the feature.\n"
    assert (task_dir / "launch-agent.sh").exists()
    assert "my-chat-id-456" in (task_dir / "launch-agent.sh").read_text()

    create_chat_calls = [c for c in mock_run.call_args_list if c[0][0][0] == "cursor"]
    assert len(create_chat_calls) == 1
    assert create_chat_calls[0][0][0][0] == "cursor"
    assert "create-chat" in create_chat_calls[0][0][0]

    clone_calls = [c for c in mock_run.call_args_list if c[0][0][0] == "git"]
    assert len(clone_calls) == 1
    git_cmd = clone_calls[0][0][0]
    assert git_cmd[1] == "clone"
    assert git_cmd[2] == "https://github.com/user/repo.git"


def test_start_task_creates_directory(manager: TaskManager, tmp_tasks_root: Path) -> None:
    with patch("dev.task_manager.subprocess.run") as mock_run:
        mock_run.side_effect = lambda cmd, **kwargs: (
            MagicMock(stdout="chat-123\n", stderr="", returncode=0)
            if cmd[0] == "cursor"
            else (Path(tmp_tasks_root / "foo" / "foo").mkdir(parents=True) or MagicMock(returncode=0))
            if cmd[0] == "git"
            else MagicMock(returncode=0)
        )
        manager.start_task(
            title="Foo",
            task_name="foo",
            description="Bar",
            repo_url="https://github.com/x/y.git",
        )
    assert (tmp_tasks_root / "foo").is_dir()
    assert (tmp_tasks_root / "foo" / "task.md").exists()
    assert (tmp_tasks_root / "foo" / "launch-agent.sh").exists()


def test_start_task_duplicate_name_raises(manager: TaskManager, tmp_tasks_root: Path) -> None:
    (tmp_tasks_root / "existing").mkdir(parents=True)
    with patch("dev.task_manager.subprocess.run"):
        with pytest.raises(FileExistsError):
            manager.start_task(
                title="Existing",
                task_name="existing",
                description="Desc",
                repo_url="https://github.com/a/b.git",
            )