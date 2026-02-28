"""Tests for CLI entry point."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from dev.cli import main


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def test_main_help() -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "Dev CLI" in result.output
    assert "create" in result.output
    assert "agent" in result.output


def test_create_help() -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["create", "--help"])
    assert result.exit_code == 0
    assert "TITLE" in result.output
    assert "--repo" in result.output
    assert "--description" in result.output


def test_list_help() -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["list", "--help"])
    assert result.exit_code == 0
    assert "List" in result.output


def test_list_empty(runner: CliRunner, tmp_path: Path) -> None:
    (tmp_path / "tasks").mkdir()
    result = runner.invoke(main, ["list", "--tasks-dir", str(tmp_path / "tasks")])
    assert result.exit_code == 0
    assert "No tasks" in result.output


def test_list_shows_tasks(runner: CliRunner, tmp_path: Path) -> None:
    root = tmp_path / "tasks"
    root.mkdir()
    (root / "task-a").mkdir()
    (root / "task-b").mkdir()
    result = runner.invoke(main, ["list", "--tasks-dir", str(root)])
    assert result.exit_code == 0
    assert "task-a" in result.output
    assert "task-b" in result.output
    assert result.output.strip().split() == ["task-a", "task-b"]


def test_archive_moves_to_archive(runner: CliRunner, tmp_path: Path) -> None:
    root = tmp_path / "tasks"
    root.mkdir()
    (root / "foo").mkdir()
    (root / "foo" / "task.md").write_text("x")
    result = runner.invoke(main, ["archive", "foo", "--tasks-dir", str(root)])
    assert result.exit_code == 0
    assert "Archived to" in result.output
    assert ".archive" in result.output
    assert not (root / "foo").exists()
    archive_dir = root / ".archive"
    assert archive_dir.exists()
    archived = list(archive_dir.iterdir())
    assert len(archived) == 1
    assert archived[0].name.startswith("foo-")
    assert (archived[0] / "task.md").read_text() == "x"


def test_archive_not_found_exits_nonzero(runner: CliRunner, tmp_path: Path) -> None:
    root = tmp_path / "tasks"
    root.mkdir()
    result = runner.invoke(main, ["archive", "nonexistent", "--tasks-dir", str(root)])
    assert result.exit_code != 0
    assert "not found" in result.output


def test_agent_help() -> None:
    result = CliRunner().invoke(main, ["agent", "--help"])
    assert result.exit_code == 0
    assert "Launch" in result.output or "agent" in result.output
    assert "--task" in result.output


def test_agent_missing_chat_id_file_exits_nonzero(runner: CliRunner, tmp_path: Path) -> None:
    with runner.isolated_filesystem(tmp_path):
        result = runner.invoke(main, ["agent"])
    assert result.exit_code != 0
    assert "Chat ID file not found" in result.output or "not found" in result.output


def test_agent_launches_with_chat_id(runner: CliRunner, tmp_path: Path) -> None:
    with runner.isolated_filesystem(tmp_path):
        # Create agent-chat-id in cwd (isolated fs) so "dev agent" finds it
        (Path.cwd() / "agent-chat-id").write_text("my-chat-uuid-123")
        with patch("dev.commands.task.os.execvp") as mock_execvp:
            mock_execvp.side_effect = SystemExit(0)
            result = runner.invoke(main, ["agent"], catch_exceptions=True)
    assert mock_execvp.called
    call_args = mock_execvp.call_args[0]
    assert call_args[0] == "cursor"
    assert call_args[1] == [
        "cursor",
        "agent",
        "--force",
        "--resume",
        "my-chat-uuid-123",
        "Read the task.md file and do it.",
    ]


def test_create_with_unknown_shorthand_exits_nonzero(
    runner: CliRunner, tmp_path: Path
) -> None:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    config_file = tmp_path / "repos.json"
    config_file.write_text("{}")
    with patch("dev.repo_config.CONFIG_FILE", config_file):
        result = runner.invoke(
            main,
            [
                "create",
                "Some task",
                "--repo",
                "unknown",
                "--description",
                "Do it.",
                "--tasks-dir",
                str(tasks_dir),
            ],
        )
    assert result.exit_code != 0
    assert "Unknown repo shorthand" in result.output


def test_create_without_description_prompts_for_input(
    runner: CliRunner, tmp_path: Path
) -> None:
    """When -d is omitted, create prompts for description and uses the input."""
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    config_file = tmp_path / "repos.json"
    config_file.write_text(
        '{"desk": "https://github.com/maxrademacher/desk.git"}'
    )
    with patch("dev.repo_config.CONFIG_FILE", config_file):
        with patch("dev.commands.task.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="chat-id\n")
            result = runner.invoke(
                main,
                [
                    "create",
                    "My task",
                    "--repo",
                    "desk",
                    "--tasks-dir",
                    str(tasks_dir),
                ],
                input="Typed description\n",
            )
    assert result.exit_code == 0
    assert (tasks_dir / "my-task" / "task.md").exists()
    assert "Typed description" in (tasks_dir / "my-task" / "task.md").read_text()


def test_create_with_shorthand_uses_resolved_url(
    runner: CliRunner, tmp_path: Path
) -> None:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    config_file = tmp_path / "repos.json"
    config_file.write_text(
        '{"desk": "https://github.com/maxrademacher/desk.git"}'
    )
    with patch("dev.repo_config.CONFIG_FILE", config_file):
        with patch("dev.commands.task.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="chat-id\n")
            result = runner.invoke(
                main,
                [
                    "create",
                    "My task",
                    "--repo",
                    "desk",
                    "--description",
                    "Do it.",
                    "--tasks-dir",
                    str(tasks_dir),
                ],
            )
    assert result.exit_code == 0
    clone_calls = [
        c for c in mock_run.call_args_list if c[0][0][:2] == ["git", "clone"]
    ]
    assert len(clone_calls) == 1
    assert clone_calls[0][0][0][2] == "https://github.com/maxrademacher/desk.git"


def test_repos_help() -> None:
    result = CliRunner().invoke(main, ["repos", "--help"])
    assert result.exit_code == 0
    assert "add" in result.output
    assert "list" in result.output


def test_repos_list_empty(runner: CliRunner, tmp_path: Path) -> None:
    config_file = tmp_path / "repos.json"
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text("{}")
    with patch("dev.repo_config.CONFIG_FILE", config_file):
        result = runner.invoke(main, ["repos", "list"])
    assert result.exit_code == 0
    assert "No repo shorthands" in result.output


def test_repos_add_and_list(runner: CliRunner, tmp_path: Path) -> None:
    config_file = tmp_path / "repos.json"
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text("{}")
    with patch("dev.repo_config.CONFIG_FILE", config_file):
        result = runner.invoke(
            main,
            ["repos", "add", "desk", "https://github.com/maxrademacher/desk.git"],
        )
    assert result.exit_code == 0
    assert "Added desk" in result.output
    with patch("dev.repo_config.CONFIG_FILE", config_file):
        result2 = runner.invoke(main, ["repos", "list"])
    assert result2.exit_code == 0
    assert "desk" in result2.output
    assert "maxrademacher/desk" in result2.output