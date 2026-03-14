"""Tests for TaskManager."""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from dev_sdk.comms import read_index
from dev_sdk.task_manager import TaskManager


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


def test_ensure_comms_dir_creates_comms_and_rule(manager: TaskManager, tmp_tasks_root: Path) -> None:
    task_dir = tmp_tasks_root / "my-task"
    task_dir.mkdir(parents=True)
    manager._ensure_comms_dir(task_dir)
    assert (task_dir / "comms").is_dir()
    rule_path = task_dir / ".cursor" / "rules" / "task-comms.mdc"
    assert rule_path.exists()
    assert "comms" in rule_path.read_text() and "index.txt" in rule_path.read_text()


def test_write_chat_id_file(manager: TaskManager, tmp_tasks_root: Path) -> None:
    task_dir = tmp_tasks_root / "my-task"
    task_dir.mkdir(parents=True)
    manager._write_chat_id_file(task_dir, "chat-uuid-123")
    path = task_dir / "agent-chat-id"
    assert path.read_text().strip() == "chat-uuid-123"


@patch("dev_sdk.task_manager.subprocess.run")
def test_start_task(
    mock_run: MagicMock,
    manager: TaskManager,
    tmp_tasks_root: Path,
) -> None:
    def run_side_effect(cmd, **kwargs):
        if cmd[0] == "cursor" and "create-chat" in cmd:
            return MagicMock(stdout="Chat created.\nmy-chat-id-456\n", stderr="", returncode=0)
        if cmd[0] == "git" and cmd[1] == "clone":
            (tmp_tasks_root / "my-task" / "repo").mkdir(parents=True)
            return MagicMock(returncode=0)
        if cmd[0] == "git" and cmd[1] == "checkout" and cmd[2] == "-b":
            return MagicMock(returncode=0)
        raise NotImplementedError(cmd)

    mock_run.side_effect = run_side_effect

    manager.start_task(
        title="My Task",
        task_name="my-task",
        comment="Build the feature.",
        repo_url="https://github.com/user/repo.git",
        agent_cmd="cursor",
        agent_create_chat_args=["agent", "create-chat"],
    )

    task_dir = tmp_tasks_root / "my-task"
    assert (task_dir / "comms").is_dir()
    assert (task_dir / ".cursor" / "rules" / "task-comms.mdc").exists()
    order = read_index(task_dir)
    assert len(order) == 1
    first = task_dir / "comms" / order[0]
    assert "My Task" in first.read_text() and "Build the feature" in first.read_text()
    assert (task_dir / "agent-chat-id").exists()
    assert (task_dir / "agent-chat-id").read_text().strip() == "my-chat-id-456"
    rules_file = task_dir / ".cursor" / "rules" / "git-workspace.mdc"
    assert rules_file.exists()
    assert "workspace root is not a git project" in rules_file.read_text()
    assert "one level deeper" in rules_file.read_text()

    create_chat_calls = [c for c in mock_run.call_args_list if c[0][0][0] == "cursor"]
    assert len(create_chat_calls) == 1
    clone_calls = [c for c in mock_run.call_args_list if c[0][0][0] == "git" and c[0][0][1] == "clone"]
    assert len(clone_calls) == 1
    checkout_calls = [c for c in mock_run.call_args_list if c[0][0][0] == "git" and c[0][0][1] == "checkout"]
    assert len(checkout_calls) == 1


@patch("dev_sdk.task_manager.subprocess.run")
def test_start_task_calls_on_progress(
    mock_run: MagicMock,
    manager: TaskManager,
    tmp_tasks_root: Path,
) -> None:
    messages: list[str] = []

    def run_side_effect(cmd, **kwargs):
        if cmd[0] == "cursor" and "create-chat" in cmd:
            return MagicMock(stdout="chat-id\n", stderr="", returncode=0)
        if cmd[0] == "git" and cmd[1] == "clone":
            (tmp_tasks_root / "my-task" / "repo").mkdir(parents=True)
            return MagicMock(returncode=0)
        if cmd[0] == "git" and cmd[1] == "checkout" and cmd[2] == "-b":
            return MagicMock(returncode=0)
        raise NotImplementedError(cmd)

    mock_run.side_effect = run_side_effect

    manager.start_task(
        title="My Task",
        task_name="my-task",
        comment="Build the feature.",
        repo_url="https://github.com/user/repo.git",
        agent_cmd="cursor",
        agent_create_chat_args=["agent", "create-chat"],
        on_progress=messages.append,
    )

    assert "Created task directory." in messages
    assert "Comms directory ready." in messages
    assert "Cloning repository…" in messages
    assert "Feature branch created." in messages


def test_start_task_creates_directory(manager: TaskManager, tmp_tasks_root: Path) -> None:
    with patch("dev_sdk.task_manager.subprocess.run") as mock_run:
        def run_side_effect(cmd, **kwargs):
            if cmd[0] == "cursor":
                return MagicMock(stdout="chat-123\n", stderr="", returncode=0)
            if cmd[0] == "git":
                (tmp_tasks_root / "foo" / "y").mkdir(parents=True, exist_ok=True)
                return MagicMock(returncode=0)
            return MagicMock(returncode=0)

        mock_run.side_effect = run_side_effect
        manager.start_task(
            title="Foo",
            task_name="foo",
            comment="Bar",
            repo_url="https://github.com/x/y.git",
        )
    assert (tmp_tasks_root / "foo").is_dir()
    assert (tmp_tasks_root / "foo" / "comms").is_dir()
    assert (tmp_tasks_root / "foo" / "agent-chat-id").exists()


def test_start_task_duplicate_name_raises(manager: TaskManager, tmp_tasks_root: Path) -> None:
    (tmp_tasks_root / "existing").mkdir(parents=True)
    with patch("dev_sdk.task_manager.subprocess.run"):
        with pytest.raises(FileExistsError):
            manager.start_task(
                title="Existing",
                task_name="existing",
                comment="Desc",
                repo_url="https://github.com/a/b.git",
            )


def test_list_tasks_empty(manager: TaskManager) -> None:
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
    (task_dir / "comms").mkdir()
    (task_dir / "comms" / "001-user.md").write_text("# Task\n\nDesc.")
    dest = manager.archive_task("my-task")
    assert not task_dir.exists()
    assert dest.parent == tmp_tasks_root / ".archive"
    assert dest.name.startswith("my-task-")


def test_archive_task_not_found_raises(manager: TaskManager, tmp_tasks_root: Path) -> None:
    tmp_tasks_root.mkdir(parents=True)
    with pytest.raises(FileNotFoundError, match="Task not found"):
        manager.archive_task("nonexistent")


def test_repo_name_from_url_with_git_suffix() -> None:
    assert TaskManager._repo_name_from_url("https://github.com/user/repo.git") == "repo"


def test_repo_name_from_url_without_git_suffix() -> None:
    assert TaskManager._repo_name_from_url("https://github.com/user/repo") == "repo"


def test_parse_archive_name() -> None:
    assert TaskManager.parse_archive_name("my-task-mar-14-a1b2c3") == ("my-task", "mar-14")
    assert TaskManager.parse_archive_name("foo-jan-1-abcdef") == ("foo", "jan-1")
    assert TaskManager.parse_archive_name("no-suffix") == ("no-suffix", "")
    assert TaskManager.parse_archive_name("multi-dash-task-dec-31-fedcba") == (
        "multi-dash-task",
        "dec-31",
    )


def test_list_archived_tasks_empty(manager: TaskManager) -> None:
    assert manager.list_archived_tasks() == []


def test_list_archived_tasks_no_archive_dir(manager: TaskManager, tmp_tasks_root: Path) -> None:
    tmp_tasks_root.mkdir(parents=True)
    assert manager.list_archived_tasks() == []


def test_list_archived_tasks_returns_sorted(manager: TaskManager, tmp_tasks_root: Path) -> None:
    archive_root = tmp_tasks_root / ".archive"
    archive_root.mkdir(parents=True)
    (archive_root / "z-task-mar-14-aaaaaa").mkdir()
    (archive_root / "a-task-mar-15-bbbbbb").mkdir()
    (archive_root / "m-task-mar-14-cccccc").mkdir()
    entries = manager.list_archived_tasks()
    assert len(entries) == 3
    assert entries[0].archived_date == "mar-15"
    assert entries[0].task_name == "a-task"
    assert entries[1].archived_date == "mar-14"
    assert entries[1].task_name == "m-task"
    assert entries[2].archived_date == "mar-14"
    assert entries[2].task_name == "z-task"


def test_unarchive_task(manager: TaskManager, tmp_tasks_root: Path) -> None:
    tmp_tasks_root.mkdir(parents=True)
    archive_root = tmp_tasks_root / ".archive"
    archive_root.mkdir()
    archived = archive_root / "my-task-mar-14-a1b2c3"
    archived.mkdir()
    (archived / "comms").mkdir()
    dest = manager.unarchive_task("my-task-mar-14-a1b2c3")
    assert dest == tmp_tasks_root / "my-task"
    assert dest.is_dir()
    assert not archived.exists()


def test_unarchive_task_target_exists_raises(manager: TaskManager, tmp_tasks_root: Path) -> None:
    tmp_tasks_root.mkdir(parents=True)
    (tmp_tasks_root / "my-task").mkdir()
    archive_root = tmp_tasks_root / ".archive"
    archive_root.mkdir()
    (archive_root / "my-task-mar-14-a1b2c3").mkdir()
    with pytest.raises(FileExistsError, match="Task already exists"):
        manager.unarchive_task("my-task-mar-14-a1b2c3")


def test_unarchive_task_not_found_raises(manager: TaskManager, tmp_tasks_root: Path) -> None:
    tmp_tasks_root.mkdir(parents=True)
    (tmp_tasks_root / ".archive").mkdir()
    with pytest.raises(FileNotFoundError, match="Archived task not found"):
        manager.unarchive_task("nonexistent-mar-14-abcdef")
