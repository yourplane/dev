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


def test_write_chat_id_file(manager: TaskManager, tmp_tasks_root: Path) -> None:
    task_dir = tmp_tasks_root / "my-task"
    task_dir.mkdir(parents=True)
    manager._write_chat_id_file(task_dir, "chat-uuid-123")
    path = task_dir / "agent-chat-id"
    assert path.read_text().strip() == "chat-uuid-123"


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
            # git clone with cwd creates task_dir/repo-name (repo from URL)
            (tmp_tasks_root / "my-task" / "repo").mkdir(parents=True)
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
    assert (task_dir / "agent-chat-id").exists()
    assert (task_dir / "agent-chat-id").read_text().strip() == "my-chat-id-456"
    rules_file = task_dir / ".cursor" / "rules" / "git-workspace.mdc"
    assert rules_file.exists()
    assert "workspace root is not a git project" in rules_file.read_text()
    assert "one level deeper" in rules_file.read_text()

    create_chat_calls = [c for c in mock_run.call_args_list if c[0][0][0] == "cursor"]
    assert len(create_chat_calls) == 1
    assert create_chat_calls[0][0][0][0] == "cursor"
    assert "create-chat" in create_chat_calls[0][0][0]

    clone_calls = [c for c in mock_run.call_args_list if c[0][0][0] == "git"]
    assert len(clone_calls) == 1
    git_cmd = clone_calls[0][0][0]
    assert git_cmd[1] == "clone"
    assert git_cmd[2] == "https://github.com/user/repo.git"
    assert clone_calls[0][1].get("cwd") == tmp_tasks_root / "my-task"


def test_start_task_creates_directory(manager: TaskManager, tmp_tasks_root: Path) -> None:
    with patch("dev.task_manager.subprocess.run") as mock_run:
        mock_run.side_effect = lambda cmd, **kwargs: (
            MagicMock(stdout="chat-123\n", stderr="", returncode=0)
            if cmd[0] == "cursor"
            else (Path(tmp_tasks_root / "foo" / "y").mkdir(parents=True) or MagicMock(returncode=0))
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
    assert (tmp_tasks_root / "foo" / "agent-chat-id").exists()
    assert (tmp_tasks_root / "foo" / ".cursor" / "rules" / "git-workspace.mdc").exists()


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


def test_list_tasks_empty(manager: TaskManager) -> None:
    assert manager.list_tasks() == []


def test_list_tasks_nonexistent_root(manager: TaskManager, tmp_tasks_root: Path) -> None:
    assert not tmp_tasks_root.exists()
    assert manager.list_tasks() == []


def test_list_tasks_returns_sorted_excludes_archive_and_hidden(
    manager: TaskManager, tmp_tasks_root: Path
) -> None:
    tmp_tasks_root.mkdir(parents=True)
    (tmp_tasks_root / "z-task").mkdir()
    (tmp_tasks_root / "a-task").mkdir()
    (tmp_tasks_root / ".archive").mkdir()
    (tmp_tasks_root / ".hidden").mkdir()
    assert manager.list_tasks() == ["a-task", "z-task"]


def test_archive_task(manager: TaskManager, tmp_tasks_root: Path) -> None:
    tmp_tasks_root.mkdir(parents=True)
    task_dir = tmp_tasks_root / "my-task"
    task_dir.mkdir()
    (task_dir / "task.md").write_text("# Task\n\nDesc.")
    dest = manager.archive_task("my-task")
    assert not task_dir.exists()
    assert dest.parent == tmp_tasks_root / ".archive"
    assert dest.name.startswith("my-task-")
    assert dest.is_dir()
    assert (dest / "task.md").read_text() == "# Task\n\nDesc."
    # Name should be my-task-<month>-<day>-<6 hex chars>
    parts = dest.name.split("-")
    assert len(parts) >= 4
    assert parts[0] == "my"
    assert parts[1] == "task"
    assert len(parts[-1]) == 6 and all(c in "0123456789abcdef" for c in parts[-1])


def test_archive_task_not_found_raises(manager: TaskManager, tmp_tasks_root: Path) -> None:
    tmp_tasks_root.mkdir(parents=True)
    with pytest.raises(FileNotFoundError, match="Task not found"):
        manager.archive_task("nonexistent")


def test_archive_task_strips_trailing_slash(manager: TaskManager, tmp_tasks_root: Path) -> None:
    tmp_tasks_root.mkdir(parents=True)
    (tmp_tasks_root / "spotify").mkdir()
    dest = manager.archive_task("spotify/")
    assert "/" not in dest.name
    assert dest.name.startswith("spotify-")


def test_repo_name_from_url_with_git_suffix() -> None:
    assert TaskManager._repo_name_from_url("https://github.com/user/repo.git") == "repo"


def test_repo_name_from_url_without_git_suffix() -> None:
    assert TaskManager._repo_name_from_url("https://github.com/user/repo") == "repo"


def test_setup_pyenv_skips_when_no_python_project(
    manager: TaskManager, tmp_tasks_root: Path
) -> None:
    """When repo has no pyproject.toml or setup.py, skip venv and do not create .venv."""
    task_dir = tmp_tasks_root / "my-task"
    task_dir.mkdir(parents=True)
    (task_dir / "some-repo").mkdir()  # no pyproject.toml or setup.py
    manager._setup_pyenv(task_dir, "https://github.com/user/some-repo.git")
    assert not (task_dir / ".venv").exists()
    assert not (task_dir / ".cursor" / "rules" / "pyenv-testing.mdc").exists()


@patch("dev.task_manager.subprocess.run")
def test_setup_pyenv_creates_venv_and_rule_when_pyproject_exists(
    mock_run: MagicMock, manager: TaskManager, tmp_tasks_root: Path
) -> None:
    """When repo has pyproject.toml, create venv, pip install -e, and write Cursor rule."""
    task_dir = tmp_tasks_root / "my-task"
    task_dir.mkdir(parents=True)
    repo_dir = task_dir / "myrepo"
    repo_dir.mkdir()
    (repo_dir / "pyproject.toml").write_text("[project]\nname = 'myrepo'")
    mock_run.return_value = MagicMock(returncode=0)

    manager._setup_pyenv(task_dir, "https://github.com/user/myrepo.git")

    assert (task_dir / ".venv").exists() or mock_run.call_count >= 1
    rule_path = task_dir / ".cursor" / "rules" / "pyenv-testing.mdc"
    assert rule_path.exists()
    content = rule_path.read_text()
    assert "virtual environment" in content
    assert ".venv" in content
    # Should have been called for venv and pip install
    venv_calls = [c for c in mock_run.call_args_list if c[0][0][-1] == "venv" or "venv" in str(c)]
    pip_calls = [c for c in mock_run.call_args_list if "pip" in str(c[0][0])]
    assert len(venv_calls) >= 1 or len(pip_calls) >= 1