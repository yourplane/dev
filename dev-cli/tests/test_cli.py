"""Tests for CLI entry point."""

import subprocess
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
    assert "interact" in result.output
    assert "copy-from-archive" in result.output


def test_create_help() -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["create", "--help"])
    assert result.exit_code == 0
    assert "TITLE" in result.output
    assert "--repo" in result.output
    assert "--no-repo" in result.output
    assert "--comment" in result.output


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
    (root / "foo" / "comms").mkdir()
    (root / "foo" / "comms" / "001-user.md").write_text("x")
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
    assert (archived[0] / "comms" / "001-user.md").read_text() == "x"


def test_archive_not_found_exits_nonzero(runner: CliRunner, tmp_path: Path) -> None:
    root = tmp_path / "tasks"
    root.mkdir()
    result = runner.invoke(main, ["archive", "nonexistent", "--tasks-dir", str(root)])
    assert result.exit_code != 0
    assert "not found" in result.output


def test_copy_from_archive_success(runner: CliRunner, tmp_path: Path) -> None:
    root = tmp_path / "tasks"
    root.mkdir()
    archived_task = root / ".archive" / "foo-mar-14-a1b2c3"
    archived_task.mkdir(parents=True)
    (archived_task / "comms").mkdir()
    (archived_task / "comms" / "001-user.md").write_text("hello")
    repo_dir = archived_task / "repo"
    (repo_dir / ".git").mkdir(parents=True)
    with patch("dev_sdk.task_manager.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="chat-id\n")
        result = runner.invoke(
            main,
            ["copy-from-archive", "foo-mar-14-a1b2c3", "--tasks-dir", str(root)],
        )
    assert result.exit_code == 0
    assert "Task copied to" in result.output
    dest = root / "foo"
    assert dest.is_dir()
    assert (dest / "comms" / "001-user.md").read_text() == "hello"
    assert (dest / "repo" / ".git").is_dir()
    assert (dest / "agent-chat-id").read_text() == "chat-id"


def test_copy_from_archive_destination_exists(runner: CliRunner, tmp_path: Path) -> None:
    root = tmp_path / "tasks"
    root.mkdir()
    (root / ".archive" / "foo-mar-14-a1b2c3").mkdir(parents=True)
    (root / "foo").mkdir()
    result = runner.invoke(
        main,
        ["copy-from-archive", "foo-mar-14-a1b2c3", "--tasks-dir", str(root)],
    )
    assert result.exit_code != 0
    assert "already exists" in result.output


def test_copy_from_archive_missing_source(runner: CliRunner, tmp_path: Path) -> None:
    root = tmp_path / "tasks"
    root.mkdir()
    result = runner.invoke(
        main,
        ["copy-from-archive", "missing-mar-14-a1b2c3", "--tasks-dir", str(root)],
    )
    assert result.exit_code != 0
    assert "not found" in result.output


def test_copy_from_archive_with_override_name(
    runner: CliRunner, tmp_path: Path
) -> None:
    root = tmp_path / "tasks"
    root.mkdir()
    archived_task = root / ".archive" / "foo-mar-14-a1b2c3"
    archived_task.mkdir(parents=True)
    with patch("dev_sdk.task_manager.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="chat-id\n")
        result = runner.invoke(
            main,
            [
                "copy-from-archive",
                "foo-mar-14-a1b2c3",
                "--task-name",
                "foo-v2",
                "--tasks-dir",
                str(root),
            ],
        )
    assert result.exit_code == 0
    assert "foo-v2" in result.output
    assert (root / "foo-v2").is_dir()
    assert not (root / "foo").exists()


def test_interact_help() -> None:
    result = CliRunner().invoke(main, ["interact", "--help"])
    assert result.exit_code == 0
    assert "Interact" in result.output or "interact" in result.output
    assert "--task" in result.output


def test_interact_missing_chat_id_file_exits_nonzero(runner: CliRunner, tmp_path: Path) -> None:
    with runner.isolated_filesystem(tmp_path):
        result = runner.invoke(main, ["interact"])
    assert result.exit_code != 0
    assert "Chat ID file not found" in result.output or "not found" in result.output


def test_interact_launches_with_chat_id(runner: CliRunner, tmp_path: Path) -> None:
    with runner.isolated_filesystem(tmp_path):
        # Create agent-chat-id in cwd (isolated fs) so "dev interact" finds it
        (Path.cwd() / "agent-chat-id").write_text("my-chat-uuid-123")
        with patch("dev.commands.task.os.execvp") as mock_execvp:
            mock_execvp.side_effect = SystemExit(0)
            runner.invoke(main, ["interact"], catch_exceptions=True)
    assert mock_execvp.called
    call_args = mock_execvp.call_args[0]
    assert call_args[0] == "cursor"
    assert call_args[1] == [
        "cursor",
        "agent",
        "--force",
        "--resume",
        "my-chat-uuid-123",
    ]


def test_plan_runs_headless_and_writes_draft(runner: CliRunner, tmp_path: Path) -> None:
    with runner.isolated_filesystem(tmp_path):
        cwd = Path.cwd()
        (cwd / "comms").mkdir()
        (cwd / "comms" / "index.txt").write_text("")
        # Simulate stream-json output: one NDJSON line with content field
        streamed_line = '{"content": "# Detailed Plan\\n\\nStep 1.\\nStep 2."}\n'
        mock_proc = MagicMock()
        mock_proc.stdout = iter([streamed_line])
        mock_proc.stderr.read.return_value = ""
        mock_proc.returncode = 0
        mock_proc.wait.return_value = None
        with patch("dev_sdk.agent_run.subprocess.Popen") as mock_popen:
            mock_popen.return_value = mock_proc
            result = runner.invoke(main, ["plan-implement"])
    assert result.exit_code == 0
    assert mock_popen.called
    call_kw = mock_popen.call_args[1]
    assert call_kw["stdout"] == subprocess.PIPE
    argv = mock_popen.call_args[0][0]
    assert argv[0] == "cursor"
    assert "--output-format" in argv
    assert "stream-json" in argv
    assert "--stream-partial-output" in argv
    assert "--mode" in argv and "ask" in argv
    assert "--resume" not in argv
    assert "--workspace" in argv
    assert "--trust" in argv
    draft = cwd / "task-plan-draft.md"
    assert draft.exists()
    assert draft.read_text() == "# Detailed Plan\n\nStep 1.\nStep 2."
    assert (cwd / "comms" / "index.txt").exists()
    order = [n.strip() for n in (cwd / "comms" / "index.txt").read_text().splitlines() if n.strip()]
    assert len(order) == 1 and "agent-plan" in order[0]
    assert "Starting plan" in result.output
    assert "stream-json" in result.output
    assert "Plan written to" in result.output
    assert (cwd / ".logs").is_dir()
    assert list((cwd / ".logs").glob("dev-plan-stream-*.log"))


def test_question_runs_headless_and_writes_draft(runner: CliRunner, tmp_path: Path) -> None:
    with runner.isolated_filesystem(tmp_path):
        cwd = Path.cwd()
        (cwd / "comms").mkdir()
        (cwd / "comms" / "index.txt").write_text("")
        streamed_line = (
            '{"type": "assistant", "message": {"content": [{"type": "text", "text": "1. What scope?"}]}, '
            '"model_call_id": "call-1"}\n'
        )
        mock_proc = MagicMock()
        mock_proc.stdout = iter([streamed_line])
        mock_proc.stderr.read.return_value = ""
        mock_proc.returncode = 0
        mock_proc.wait.return_value = None
        with patch("dev_sdk.agent_run.subprocess.Popen") as mock_popen:
            mock_popen.return_value = mock_proc
            result = runner.invoke(main, ["question"])
    assert result.exit_code == 0
    argv = mock_popen.call_args[0][0]
    assert "--mode" in argv and "ask" in argv
    assert "--resume" not in argv
    draft = cwd / "task-question-draft.md"
    assert draft.exists()
    assert draft.read_text() == "1. What scope?"
    order = [n.strip() for n in (cwd / "comms" / "index.txt").read_text().splitlines() if n.strip()]
    assert len(order) == 1 and "agent-question" in order[0]
    assert "Starting question" in result.output
    assert "Questions written to" in result.output
    assert list((cwd / ".logs").glob("dev-question-stream-*.log"))


def test_create_with_unknown_shorthand_exits_nonzero(
    runner: CliRunner, tmp_path: Path
) -> None:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    config_file = tmp_path / "repos.json"
    config_file.write_text("{}")
    with patch("dev_sdk.repo_config.CONFIG_FILE", config_file):
        result = runner.invoke(
            main,
            [
                "create",
                "Some task",
                "--repo",
                "unknown",
                "--comment",
                "Do it.",
                "--tasks-dir",
                str(tasks_dir),
            ],
        )
    assert result.exit_code != 0
    assert "Unknown repo shorthand" in result.output


def test_create_without_comment_creates_task_with_no_initial_comms(
    runner: CliRunner, tmp_path: Path
) -> None:
    """When -c is omitted, create does not prompt; task has comms dir but no initial comment."""
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    config_file = tmp_path / "repos.json"
    config_file.write_text(
        '{"desk": "https://github.com/maxrademacher/desk.git"}'
    )
    with patch("dev_sdk.repo_config.CONFIG_FILE", config_file):
        with patch("dev_sdk.task_manager.subprocess.run") as mock_run:
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
            )
    assert result.exit_code == 0
    task_dir = tasks_dir / "my-task"
    assert (task_dir / "comms").is_dir()
    assert not (task_dir / "task.md").exists()
    index_file = task_dir / "comms" / "index.txt"
    assert not index_file.exists() or index_file.read_text().strip() == ""


def test_create_with_shorthand_uses_resolved_url(
    runner: CliRunner, tmp_path: Path
) -> None:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    config_file = tmp_path / "repos.json"
    config_file.write_text(
        '{"desk": "https://github.com/maxrademacher/desk.git"}'
    )
    with patch("dev_sdk.repo_config.CONFIG_FILE", config_file):
        with patch("dev_sdk.task_manager.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="chat-id\n")
            result = runner.invoke(
                main,
                [
                    "create",
                    "My task",
                    "--repo",
                    "desk",
                    "--comment",
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


def test_create_prints_progress_messages(
    runner: CliRunner, tmp_path: Path
) -> None:
    """Create prints progress so it does not look like it is hanging."""
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    config_file = tmp_path / "repos.json"
    config_file.write_text(
        '{"desk": "https://github.com/maxrademacher/desk.git"}'
    )
    with patch("dev_sdk.repo_config.CONFIG_FILE", config_file):
        with patch("dev_sdk.task_manager.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="chat-id\n")
            result = runner.invoke(
                main,
                [
                    "create",
                    "My task",
                    "--repo",
                    "desk",
                    "--comment",
                    "Do it.",
                    "--tasks-dir",
                    str(tasks_dir),
                ],
            )
    assert result.exit_code == 0
    output = result.output
    assert "Created task directory." in output
    assert "Comms directory ready." in output
    assert "Added initial comment to comms." in output
    assert "Creating agent chat…" in output
    assert "Agent chat created." in output
    assert "Cloning repository…" in output
    assert "Repository cloned." in output
    assert "Checking out feature branch…" in output
    assert "Feature branch created." in output
    assert "Task created:" in output


def test_create_no_repo_skips_clone_and_git_workspace_rule(
    runner: CliRunner, tmp_path: Path
) -> None:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    with patch("dev_sdk.task_manager.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="chat-id\n")
        result = runner.invoke(
            main,
            [
                "create",
                "Ops task",
                "--no-repo",
                "--tasks-dir",
                str(tasks_dir),
            ],
        )
    assert result.exit_code == 0
    task_dir = tasks_dir / "ops-task"
    assert (task_dir / "comms").is_dir()
    assert (task_dir / ".cursor" / "rules" / "task-comms.mdc").exists()
    assert not (task_dir / ".cursor" / "rules" / "git-workspace.mdc").exists()
    clone_calls = [c for c in mock_run.call_args_list if c[0][0][:2] == ["git", "clone"]]
    assert len(clone_calls) == 0
    assert "No repository cloned" in result.output


def test_create_requires_repo_without_no_repo_flag(runner: CliRunner, tmp_path: Path) -> None:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    result = runner.invoke(main, ["create", "T", "--tasks-dir", str(tasks_dir)])
    assert result.exit_code == 2
    assert "Either --repo or --no-repo" in result.output


def test_create_rejects_repo_with_no_repo(runner: CliRunner, tmp_path: Path) -> None:
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    result = runner.invoke(
        main,
        [
            "create",
            "T",
            "--no-repo",
            "--repo",
            "https://github.com/a/b.git",
            "--tasks-dir",
            str(tasks_dir),
        ],
    )
    assert result.exit_code == 2


def test_repos_help() -> None:
    result = CliRunner().invoke(main, ["repos", "--help"])
    assert result.exit_code == 0
    assert "add" in result.output
    assert "list" in result.output


def test_repos_list_empty(runner: CliRunner, tmp_path: Path) -> None:
    config_file = tmp_path / "repos.json"
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text("{}")
    with patch("dev_sdk.repo_config.CONFIG_FILE", config_file):
        result = runner.invoke(main, ["repos", "list"])
    assert result.exit_code == 0
    assert "No repo shorthands" in result.output


def test_repos_add_and_list(runner: CliRunner, tmp_path: Path) -> None:
    config_file = tmp_path / "repos.json"
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text("{}")
    with patch("dev_sdk.repo_config.CONFIG_FILE", config_file):
        result = runner.invoke(
            main,
            ["repos", "add", "desk", "https://github.com/maxrademacher/desk.git"],
        )
    assert result.exit_code == 0
    assert "Added desk" in result.output
    with patch("dev_sdk.repo_config.CONFIG_FILE", config_file):
        result2 = runner.invoke(main, ["repos", "list"])
    assert result2.exit_code == 0
    assert "desk" in result2.output
    assert "maxrademacher/desk" in result2.output


def test_comms_comment_adds_user_comms(runner: CliRunner, tmp_path: Path) -> None:
    """comms comment creates a user comms file and appends to index."""
    with runner.isolated_filesystem(tmp_path):
        cwd = Path.cwd()
        (cwd / "comms").mkdir()
        result = runner.invoke(main, ["comms", "comment", "Hello from user"])
    assert result.exit_code == 0
    assert "Added:" in result.output
    index = cwd / "comms" / "index.txt"
    assert index.exists()
    order = [n.strip() for n in index.read_text().splitlines() if n.strip()]
    assert len(order) == 1
    assert order[0].startswith("001-user")
    assert (cwd / "comms" / order[0]).read_text().strip() == "Hello from user"


def test_plan_implement_help() -> None:
    result = CliRunner().invoke(main, ["plan-implement", "--help"])
    assert result.exit_code == 0
    assert "plan-implement" in result.output.lower()


def test_question_help() -> None:
    result = CliRunner().invoke(main, ["question", "--help"])
    assert result.exit_code == 0
    assert "question" in result.output.lower()


def test_implement_help() -> None:
    result = CliRunner().invoke(main, ["implement", "--help"])
    assert result.exit_code == 0
    assert "implement" in result.output.lower()


def test_implement_runs_headless_stream_json(runner: CliRunner, tmp_path: Path) -> None:
    """Implement runs agent with stream-json, no --mode ask, writes stream log to .logs."""
    with runner.isolated_filesystem(tmp_path):
        cwd = Path.cwd()
        (cwd / "agent-chat-id").write_text("chat-789")
        (cwd / "comms").mkdir()
        (cwd / "comms" / "index.txt").write_text("")
        streamed_line = (
            '{"type": "assistant", "message": {"content": [{"type": "text", "text": "Implementation done."}]}, '
            '"model_call_id": "m1"}\n'
        )
        mock_proc = MagicMock()
        mock_proc.stdout = iter([streamed_line])
        mock_proc.stderr.read.return_value = ""
        mock_proc.returncode = 0
        mock_proc.wait.return_value = None
        with patch("dev_sdk.agent_run.subprocess.Popen") as mock_popen:
            mock_popen.return_value = mock_proc
            result = runner.invoke(main, ["implement"])
    assert result.exit_code == 0
    assert mock_popen.called
    argv = mock_popen.call_args[0][0]
    assert argv[0] == "cursor"
    assert "--output-format" in argv
    assert "stream-json" in argv
    assert "--stream-partial-output" in argv
    assert "--resume" in argv
    assert "chat-789" in argv
    assert "--workspace" in argv
    assert "--trust" in argv
    # Implement must allow shell commands (pytest, git) so agent can run and commit
    assert "--force" in argv
    assert "--sandbox" in argv and "disabled" in argv
    # Implement must NOT use --mode ask so agent can edit and commit
    assert "--mode" not in argv
    assert "Starting implement" in result.output
    assert "Stream log:" in result.output
    assert "Summary written to" in result.output
    assert (cwd / ".logs").is_dir()
    assert list((cwd / ".logs").glob("dev-implement-stream-*.log"))
    index = cwd / "comms" / "index.txt"
    assert index.exists() and index.read_text().strip()
    order = [n.strip() for n in index.read_text().splitlines() if n.strip()]
    assert any("agent-implement" in name for name in order)
    impl_name = next(n for n in order if "agent-implement" in n)
    assert (cwd / "comms" / impl_name).read_text().strip() == "Implementation done."



