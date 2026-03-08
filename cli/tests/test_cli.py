"""Tests for CLI entry point."""

import json
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


def test_create_help() -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["create", "--help"])
    assert result.exit_code == 0
    assert "TITLE" in result.output
    assert "--repo" in result.output
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
            result = runner.invoke(main, ["interact"], catch_exceptions=True)
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
        (cwd / "agent-chat-id").write_text("chat-456")
        (cwd / "comms").mkdir()
        (cwd / "comms" / "index.txt").write_text("")
        # Simulate stream-json output: one NDJSON line with content field
        streamed_line = '{"content": "# Detailed Plan\\n\\nStep 1.\\nStep 2."}\n'
        mock_proc = MagicMock()
        mock_proc.stdout = iter([streamed_line])
        mock_proc.stderr.read.return_value = ""
        mock_proc.returncode = 0
        mock_proc.wait.return_value = None
        with patch("dev.commands.task.subprocess.Popen") as mock_popen:
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
    assert "--resume" in argv
    assert "chat-456" in argv
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
        with patch("dev.commands.task.subprocess.run") as mock_run:
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
        with patch("dev.commands.task.subprocess.run") as mock_run:
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
        streamed_line = '{"content": "Implementation done."}\n'
        mock_proc = MagicMock()
        mock_proc.stdout = iter([streamed_line])
        mock_proc.stderr.read.return_value = ""
        mock_proc.returncode = 0
        mock_proc.wait.return_value = None
        with patch("dev.commands.task.subprocess.Popen") as mock_popen:
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
    assert (cwd / ".logs").is_dir()
    assert list((cwd / ".logs").glob("dev-implement-stream-*.log"))
    # Implement does not write to comms
    index = cwd / "comms" / "index.txt"
    assert not index.exists() or index.read_text().strip() == ""


def test_plan_accept_updates_task_md(runner: CliRunner, tmp_path: Path) -> None:
    with runner.isolated_filesystem(tmp_path):
        cwd = Path.cwd()
        (cwd / "task.md").write_text("# Old\n\nOld description.")
        (cwd / "task-plan-draft.md").write_text("# New Title\n\nDetailed plan here.")
        result = runner.invoke(main, ["plan-implement", "accept"])
        task_content = (cwd / "task.md").read_text()
    assert result.exit_code == 0
    assert task_content == "# New Title\n\nDetailed plan here."
    assert "Plan accepted" in result.output


def test_plan_accept_missing_draft_exits_nonzero(runner: CliRunner, tmp_path: Path) -> None:
    with runner.isolated_filesystem(tmp_path):
        (Path.cwd() / "task.md").write_text("# Task\n\nDesc.")
        result = runner.invoke(main, ["plan-implement", "accept"])
    assert result.exit_code != 0
    assert "Draft plan not found" in result.output or "not found" in result.output


def test_plan_accept_with_task_flag(runner: CliRunner, tmp_path: Path) -> None:
    root = tmp_path / "tasks"
    root.mkdir()
    task_dir = root / "my-task"
    task_dir.mkdir()
    (task_dir / "task.md").write_text("# Old\n\nOld.")
    (task_dir / "task-plan-draft.md").write_text("# New\n\nNew plan.")
    result = runner.invoke(
        main,
        ["plan-implement", "accept", "--task", str(task_dir)],
    )
    assert result.exit_code == 0
    assert (task_dir / "task.md").read_text() == "# New\n\nNew plan."


def test_plan_accept_with_draft_option(runner: CliRunner, tmp_path: Path) -> None:
    with runner.isolated_filesystem(tmp_path):
        cwd = Path.cwd()
        (cwd / "task.md").write_text("# Task\n\nX.")
        (cwd / "custom-draft.md").write_text("# Custom\n\nCustom plan.")
        result = runner.invoke(main, ["plan-implement", "accept", "--draft", "custom-draft.md"])
        task_content = (cwd / "task.md").read_text()
    assert result.exit_code == 0
    assert task_content == "# Custom\n\nCustom plan."


def test_plan_test_help() -> None:
    result = CliRunner().invoke(main, ["plan-test", "--help"])
    assert result.exit_code == 0
    assert "plan-test" in result.output.lower()
    assert "E2E" in result.output or "testing" in result.output.lower()


def test_plan_test_runs_headless_writes_comms_only(runner: CliRunner, tmp_path: Path) -> None:
    """plan-test uses same chat-id, writes to comms only (no task-plan-draft.md)."""
    with runner.isolated_filesystem(tmp_path):
        cwd = Path.cwd()
        (cwd / "agent-chat-id").write_text("chat-plan-test")
        (cwd / "comms").mkdir()
        (cwd / "comms" / "index.txt").write_text("001-user.md\n")
        streamed_line = '{"content": "# Manual test plan\\n\\n## Feature\\n\\n1. Run .venv/foo/bin/dev --help.\\n\\n## Regression\\n\\n2. Run existing commands."}\n'
        mock_proc = MagicMock()
        mock_proc.stdout = iter([streamed_line])
        mock_proc.stderr.read.return_value = ""
        mock_proc.returncode = 0
        mock_proc.wait.return_value = None
        with patch("dev.commands.task.subprocess.Popen") as mock_popen:
            mock_popen.return_value = mock_proc
            result = runner.invoke(main, ["plan-test"])
    assert result.exit_code == 0
    assert mock_popen.called
    argv = mock_popen.call_args[0][0]
    assert argv[0] == "cursor"
    assert "--output-format" in argv
    assert "stream-json" in argv
    assert "--mode" in argv and "ask" in argv
    assert "--resume" in argv
    assert "chat-plan-test" in argv
    assert "--workspace" in argv
    assert "--trust" in argv
    # No draft file
    assert not (cwd / "task-plan-draft.md").exists()
    # Comms updated with plan-test entry
    index = cwd / "comms" / "index.txt"
    assert index.exists()
    order = [n.strip() for n in index.read_text().splitlines() if n.strip()]
    assert len(order) == 2
    assert order[0] == "001-user.md"
    assert "agent-plan-test" in order[1]
    plan_test_file = cwd / "comms" / order[1]
    assert plan_test_file.exists()
    content = plan_test_file.read_text()
    assert "Manual test plan" in content or "Feature" in content
    assert "Starting plan-test" in result.output
    assert "Testing plan written to" in result.output
    assert list((cwd / ".logs").glob("dev-plan-test-stream-*.log"))
    # No script when delimiter is absent
    assert not list((cwd / "comms").glob("*-run-plan.sh"))


def test_plan_test_writes_executable_script_when_delimiter_present(runner: CliRunner, tmp_path: Path) -> None:
    """When agent output contains ---BASH SCRIPT---, plan-test writes a numbered run-plan.sh and makes it executable."""
    import dev.commands.task as task_module

    with runner.isolated_filesystem(tmp_path):
        cwd = Path.cwd()
        (cwd / "agent-chat-id").write_text("chat-plan-test")
        (cwd / "comms").mkdir()
        (cwd / "comms" / "index.txt").write_text("001-user.md\n")
        plan_part = "# Manual test plan\n\n## Step 1\nRun dev --help."
        script_part = "#!/usr/bin/env bash\nset -e\necho Step 1\n.venv/foo/bin/dev --help"
        full_result = plan_part + "\n---BASH SCRIPT---\n" + script_part
        streamed_line = json.dumps({"type": "result", "result": full_result}) + "\n"
        mock_proc = MagicMock()
        mock_proc.stdout = iter([streamed_line])
        mock_proc.stderr.read.return_value = ""
        mock_proc.returncode = 0
        mock_proc.wait.return_value = None
        real_popen = task_module.subprocess.Popen

        def selective_popen(*args, **kwargs):
            argv = args[0] if args and args[0] else []
            if isinstance(argv, list) and "--output-format" in argv:
                return mock_proc
            return real_popen(*args, **kwargs)

        with patch.object(task_module.subprocess, "Popen", side_effect=selective_popen):
            result = runner.invoke(main, ["plan-test"])
    assert result.exit_code == 0
    order = [n.strip() for n in (cwd / "comms" / "index.txt").read_text().splitlines() if n.strip()]
    plan_file = cwd / "comms" / order[1]
    assert "How to run" in plan_file.read_text()
    script_files = list((cwd / "comms").glob("*-run-plan.sh"))
    assert len(script_files) == 1
    script_path = script_files[0]
    assert script_path.stat().st_mode & 0o111
    assert "#!/usr/bin/env bash" in script_path.read_text()
    assert "Executable script written to" in result.output


def test_test_fails_without_comms(runner: CliRunner, tmp_path: Path) -> None:
    """dev test fails when comms dir is missing."""
    with runner.isolated_filesystem(tmp_path):
        cwd = Path.cwd()
        (cwd / "agent-chat-id").write_text("chat-id")
        result = runner.invoke(main, ["test"])
    assert result.exit_code != 0
    assert "comms" in result.output.lower()


def test_test_fails_without_agent_chat_id(runner: CliRunner, tmp_path: Path) -> None:
    """dev test fails when agent-chat-id is missing (after running script)."""
    with runner.isolated_filesystem(tmp_path):
        cwd = Path.cwd()
        (cwd / "comms").mkdir()
        (cwd / "comms" / "index.txt").write_text("001-run-plan.sh\n")
        (cwd / "comms" / "001-run-plan.sh").write_text("#!/bin/bash\necho x\n")
        (cwd / "comms" / "001-run-plan.sh").chmod(0o755)
        with patch("dev.commands.task.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            result = runner.invoke(main, ["test"])
    assert result.exit_code != 0
    assert "chat" in result.output.lower() or "agent-chat-id" in result.output


def test_test_fails_without_run_plan_script(runner: CliRunner, tmp_path: Path) -> None:
    """dev test fails when comms has no *-run-plan.sh."""
    with runner.isolated_filesystem(tmp_path):
        cwd = Path.cwd()
        (cwd / "agent-chat-id").write_text("chat-id")
        (cwd / "comms").mkdir()
        (cwd / "comms" / "index.txt").write_text("001-user.md\n")
        result = runner.invoke(main, ["test"])
    assert result.exit_code != 0
    assert "run-plan" in result.output or "plan-test" in result.output


def test_test_runs_script_then_agent_writes_comms(runner: CliRunner, tmp_path: Path) -> None:
    """dev test runs latest run-plan script, saves log, runs agent in ask mode, adds test-results to comms."""
    with runner.isolated_filesystem(tmp_path):
        cwd = Path.cwd()
        (cwd / "agent-chat-id").write_text("chat-test")
        (cwd / "comms").mkdir()
        (cwd / "comms" / "index.txt").write_text("001-user.md\n002-run-plan.sh\n")
        script = cwd / "comms" / "002-run-plan.sh"
        script.write_text("#!/usr/bin/env bash\necho 'test output'\n")
        script.chmod(0o755)
        script_proc = MagicMock()
        script_proc.stdout = iter(["test output\n"])
        script_proc.returncode = 0
        script_proc.wait.return_value = None
        streamed_line = json.dumps({"type": "result", "result": "# Test results\n\nAll passed."}) + "\n"
        agent_proc = MagicMock()
        agent_proc.stdout = iter([streamed_line])
        agent_proc.stderr.read.return_value = ""
        agent_proc.returncode = 0
        agent_proc.wait.return_value = None
        with patch("dev.commands.task.subprocess.Popen", side_effect=[script_proc, agent_proc]) as mock_popen:
            result = runner.invoke(main, ["test"])
    assert result.exit_code == 0
    assert mock_popen.call_count >= 2
    # First Popen is the test script
    run_args = mock_popen.call_args_list[0][0][0]
    assert str(script) in run_args or script.name in str(run_args)
    logs = list((cwd / ".logs").glob("dev-test-run-*.log"))
    assert len(logs) == 1
    assert "test output" in logs[0].read_text()
    # Second Popen is the agent
    argv = mock_popen.call_args_list[1][0][0]
    assert "--mode" in argv and "ask" in argv
    assert "test-results" in str(mock_popen.call_args) or ".logs" in str(argv)
    order = [n.strip() for n in (cwd / "comms" / "index.txt").read_text().splitlines() if n.strip()]
    assert any("test-results" in n or "agent" in n for n in order)
    assert "Test results written to" in result.output


def test_test_uses_latest_script_when_multiple(runner: CliRunner, tmp_path: Path) -> None:
    """dev test runs the script that appears last in index among *-run-plan.sh."""
    with runner.isolated_filesystem(tmp_path):
        cwd = Path.cwd()
        (cwd / "agent-chat-id").write_text("chat-test")
        (cwd / "comms").mkdir()
        (cwd / "comms" / "index.txt").write_text("001-user.md\n002-run-plan.sh\n003-run-plan.sh\n")
        (cwd / "comms" / "002-run-plan.sh").write_text("#!/bin/bash\necho two\n")
        (cwd / "comms" / "002-run-plan.sh").chmod(0o755)
        (cwd / "comms" / "003-run-plan.sh").write_text("#!/bin/bash\necho three\n")
        (cwd / "comms" / "003-run-plan.sh").chmod(0o755)
        script_proc = MagicMock()
        script_proc.stdout = iter(["three\n"])
        script_proc.returncode = 0
        script_proc.wait.return_value = None
        streamed_line = json.dumps({"type": "result", "result": "# Ok"}) + "\n"
        agent_proc = MagicMock()
        agent_proc.stdout = iter([streamed_line])
        agent_proc.stderr.read.return_value = ""
        agent_proc.returncode = 0
        agent_proc.wait.return_value = None
        with patch("dev.commands.task.subprocess.Popen", side_effect=[script_proc, agent_proc]) as mock_popen:
            result = runner.invoke(main, ["test"])
    assert result.exit_code == 0
    run_args = mock_popen.call_args_list[0][0][0]
    assert "003-run-plan.sh" in str(run_args)


def test_activate_path_help() -> None:
    result = CliRunner().invoke(main, ["activate-path", "--help"])
    assert result.exit_code == 0
    assert "activate" in result.output
    assert "--task" in result.output


def test_activate_path_prints_path_when_venv_exists(runner: CliRunner, tmp_path: Path) -> None:
    """From a task dir with .venv/<task-name>/bin/activate, prints that path."""
    task_root = tmp_path / "my-task"
    task_root.mkdir()
    (task_root / ".venv" / "my-task" / "bin").mkdir(parents=True)
    (task_root / ".venv" / "my-task" / "bin" / "activate").write_text("# activate script\n")
    result = runner.invoke(main, ["activate-path", "--task", str(task_root)])
    assert result.exit_code == 0
    assert result.output.strip().endswith(".venv/my-task/bin/activate")
    assert "activate" in result.output


def test_activate_path_uses_cwd_when_no_task_dir(runner: CliRunner, tmp_path: Path) -> None:
    """Without --task, uses cwd; from a dir with .venv/<name>, prints path."""
    with runner.isolated_filesystem(tmp_path):
        cwd = Path.cwd()
        task_name = cwd.name
        (cwd / ".venv" / task_name / "bin").mkdir(parents=True)
        (cwd / ".venv" / task_name / "bin" / "activate").write_text("# activate\n")
        result = runner.invoke(main, ["activate-path"])
    assert result.exit_code == 0
    assert ".venv/" in result.output and "/bin/activate" in result.output


def test_activate_path_missing_venv_exits_nonzero(runner: CliRunner, tmp_path: Path) -> None:
    """When .venv/<task-name>/bin/activate does not exist, exit non-zero and print error."""
    task_root = tmp_path / "empty-task"
    task_root.mkdir()
    result = runner.invoke(main, ["activate-path", "--task", str(task_root)])
    assert result.exit_code != 0
    assert "not found" in result.output or "Activate script" in result.output