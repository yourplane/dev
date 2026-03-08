"""Task management commands (thin CLI wrapper over dev_sdk)."""

import os
from pathlib import Path

import click

from dev_sdk.comms import add_comms, comms_dir, read_index
from dev_sdk.exceptions import (
    AgentNotFoundError,
    AgentRunError,
    AgentTimeoutError,
    ChatIdNotFoundError,
)
from dev_sdk.prompts import (
    AGENT_CHAT_ID_FILE,
    PLAN_IMPLEMENT_STREAM_LOG_PREFIX,
    PLAN_LOGS_DIR,
    TASK_PLAN_DRAFT,
)
from dev_sdk.repo_config import resolve_repo
from dev_sdk.task_manager import TaskManager, repo_name_from_url, slugify
from dev_sdk.agent import read_chat_id
from dev_sdk.workflows import (
    run_implement,
    run_plan_implement,
    run_plan_test,
    run_test,
)

TASKS_ROOT = Path.home() / "tasks"
AGENT_CMD = "cursor"
AGENT_CREATE_CHAT_ARGS = ["agent", "create-chat"]


def _task_dir_from_options(
    task_name: str | None, tasks_dir: Path
) -> tuple[Path, Path]:
    """Resolve task directory and comms dir. Raises on missing dir."""
    if task_name is not None:
        task_dir = tasks_dir / task_name
    else:
        task_dir = Path.cwd()
    if not task_dir.exists() or not task_dir.is_dir():
        click.echo(f"Task directory not found: {task_dir}", err=True)
        raise SystemExit(1)
    return task_dir, comms_dir(task_dir)


def _resolve_task_dir(task_path: Path | None) -> Path:
    return (task_path or Path.cwd()).resolve()


def _stream_log_path(task_dir: Path, prefix: str) -> Path:
    from datetime import datetime, timezone
    logs_dir = task_dir / PLAN_LOGS_DIR
    logs_dir.mkdir(exist_ok=True)
    name = f"{prefix}{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.log"
    return logs_dir / name


def _on_line(formatted: str, is_thinking: bool) -> None:
    """Echo a streamed line; dim thinking."""
    if is_thinking:
        click.echo(click.style(formatted, dim=True), nl=False)
    else:
        click.echo(formatted, nl=False)


@click.command("create")
@click.argument("title", type=str)
@click.option(
    "--repo",
    "-r",
    "repo_url",
    required=True,
    type=str,
    help="Git repository URL or shorthand (e.g. desk) from config (~/.config/dev/repos.json).",
)
@click.option(
    "--comment",
    "-c",
    "comment",
    default=None,
    type=str,
    help="Optional initial user comment (same as task comms comment).",
)
@click.option(
    "--tasks-dir",
    type=click.Path(path_type=Path),
    default=TASKS_ROOT,
    envvar="DEV_TASKS_DIR",
    help="Root directory for tasks (default: ~/tasks).",
)
def start_task(
    title: str,
    repo_url: str,
    comment: str | None,
    tasks_dir: Path,
) -> None:
    """Create a new task: create directory, comms dir, agent chat, and clone repo."""
    try:
        repo_url = resolve_repo(repo_url)
    except ValueError as e:
        click.echo(str(e), err=True)
        raise SystemExit(1)
    name = slugify(title)
    manager = TaskManager(tasks_root=tasks_dir)
    try:
        manager.start_task(
            title=title,
            task_name=name,
            comment=comment,
            repo_url=repo_url,
            agent_cmd=AGENT_CMD,
            agent_create_chat_args=AGENT_CREATE_CHAT_ARGS,
            on_progress=click.echo,
        )
        task_dir = tasks_dir / name
        repo_dir = repo_name_from_url(repo_url)
        click.echo(f"Task created: {task_dir}")
        click.echo(f"  Comms: {comms_dir(task_dir)}")
        click.echo(f"  Chat ID file: {task_dir / AGENT_CHAT_ID_FILE}")
        click.echo(f"  Repo cloned into: {task_dir / repo_dir}")
        venv_dir = task_dir / ".venv" / name
        if venv_dir.exists():
            click.echo(f"  Venv: {venv_dir} (repo installed in editable mode)")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)


@click.command("interact")
@click.option(
    "--task",
    "-t",
    "task_path",
    type=click.Path(path_type=Path),
    default=None,
    help="Path to task directory. If not set, use current working directory.",
)
@click.option(
    "--agent-cmd",
    type=str,
    default=AGENT_CMD,
    envvar="DEV_AGENT_CMD",
    help="Command to run for the agent (e.g. cursor).",
)
def launch_interact(
    task_path: Path | None,
    agent_cmd: str,
) -> None:
    """Interact with the agent for this task (resume chat using saved chat ID)."""
    task_dir = _resolve_task_dir(task_path)
    try:
        chat_id = read_chat_id(task_dir)
    except ChatIdNotFoundError as e:
        click.echo(str(e), err=True)
        raise SystemExit(1)
    argv = [agent_cmd, "agent", "--force", "--resume", chat_id]
    os.execvp(agent_cmd, argv)


@click.command("list")
@click.option(
    "--tasks-dir",
    type=click.Path(path_type=Path),
    default=TASKS_ROOT,
    envvar="DEV_TASKS_DIR",
    help="Root directory for tasks (default: ~/tasks).",
)
def list_tasks(tasks_dir: Path) -> None:
    """List task directories (excludes .archive)."""
    manager = TaskManager(tasks_root=tasks_dir)
    names = manager.list_tasks()
    if not names:
        click.echo("No tasks.")
        return
    for name in names:
        click.echo(name)


@click.command("archive")
@click.argument("task_name", type=str)
@click.option(
    "--tasks-dir",
    type=click.Path(path_type=Path),
    default=TASKS_ROOT,
    envvar="DEV_TASKS_DIR",
    help="Root directory for tasks (default: ~/tasks).",
)
def archive_task(task_name: str, tasks_dir: Path) -> None:
    """Move a task to ~/tasks/.archive with a unique name (date + random suffix)."""
    manager = TaskManager(tasks_root=tasks_dir)
    try:
        dest = manager.archive_task(task_name)
        click.echo(f"Archived to {dest}")
    except FileNotFoundError as e:
        click.echo(str(e), err=True)
        raise SystemExit(1)


@click.group("comms", invoke_without_command=True)
@click.option(
    "--task",
    "-t",
    "task_name",
    type=str,
    default=None,
    help="Task name (directory name). If not set, use current directory.",
)
@click.option(
    "--tasks-dir",
    type=click.Path(path_type=Path),
    default=TASKS_ROOT,
    envvar="DEV_TASKS_DIR",
    help="Root directory for tasks (used only with --task).",
)
@click.pass_context
def comms_group(
    ctx: click.Context,
    task_name: str | None,
    tasks_dir: Path,
) -> None:
    """Add or list task comms (user comments and agent notes)."""
    if ctx.invoked_subcommand is not None:
        return
    task_dir, cdir = _task_dir_from_options(task_name, tasks_dir)
    if not cdir.exists():
        click.echo("No comms yet.")
        return
    order = read_index(task_dir)
    if not order:
        click.echo("No comms yet.")
        return
    for name in order:
        click.echo(name)


@comms_group.command("comment")
@click.argument("message", type=str, required=False)
@click.option(
    "--task",
    "-t",
    "task_name",
    type=str,
    default=None,
    help="Task name (directory name). If not set, use current directory.",
)
@click.option(
    "--tasks-dir",
    type=click.Path(path_type=Path),
    default=TASKS_ROOT,
    envvar="DEV_TASKS_DIR",
    help="Root directory for tasks (used only with --task).",
)
def comms_comment(
    message: str | None,
    task_name: str | None,
    tasks_dir: Path,
) -> None:
    """Add a user comment to the task comms."""
    task_dir, _ = _task_dir_from_options(task_name, tasks_dir)
    if not message or not message.strip():
        click.echo("Provide a message: dev task comms comment \"Your message\"", err=True)
        raise SystemExit(1)
    path = add_comms(task_dir, "user", message.strip())
    click.echo(f"Added: {path.relative_to(task_dir)}")


ACTIVATE_SCRIPT = "bin/activate"


def _venv_activate_path(task_root: Path) -> Path:
    return task_root / ".venv" / task_root.name / ACTIVATE_SCRIPT


@click.command("activate-path")
@click.option(
    "--task",
    "-t",
    "task_path",
    type=click.Path(path_type=Path),
    default=None,
    help="Path to task directory (root containing .venv/<task-name>). Default: current working directory.",
)
def activate_path(task_path: Path | None) -> None:
    """Print path to the task venv activate script for use with: source $(dev activate-path)."""
    task_root = _resolve_task_dir(task_path)
    activate_script = _venv_activate_path(task_root)
    if not activate_script.exists():
        click.echo(
            f"Activate script not found: {activate_script}. Run from a task directory or use --task.",
            err=True,
        )
        raise SystemExit(1)
    click.echo(str(activate_script))


@click.group("plan-implement", invoke_without_command=True)
@click.option(
    "--task",
    "-t",
    "task_path",
    type=click.Path(path_type=Path),
    default=None,
    help="Path to task directory. If not set, use current working directory.",
)
@click.option(
    "--agent-cmd",
    type=str,
    default=AGENT_CMD,
    envvar="DEV_AGENT_CMD",
    help="Command to run for the agent (e.g. cursor).",
)
@click.pass_context
def plan_implement_group(
    ctx: click.Context,
    task_path: Path | None,
    agent_cmd: str,
) -> None:
    """Run headless plan-implement mode or manage task plans (e.g. accept draft into task.md)."""
    if ctx.invoked_subcommand is None:
        _run_plan_implement_mode(task_path=task_path, agent_cmd=agent_cmd)


def _run_plan_implement_mode(
    task_path: Path | None,
    agent_cmd: str,
) -> None:
    task_dir = _resolve_task_dir(task_path)
    stream_log_path = _stream_log_path(task_dir, PLAN_IMPLEMENT_STREAM_LOG_PREFIX)
    try:
        click.echo("Starting plan (stream-json mode)...")
        click.echo(f"Stream log: {stream_log_path}")
        _, comms_path = run_plan_implement(
            task_dir, agent_cmd, stream_log_path, on_line=_on_line
        )
        click.echo()
        click.echo()
        click.echo(click.style(f"Plan written to {comms_path.relative_to(task_dir)}", dim=True))
    except ChatIdNotFoundError as e:
        click.echo(str(e), err=True)
        raise SystemExit(1)
    except AgentNotFoundError as e:
        click.echo(str(e), err=True)
        raise SystemExit(1)
    except AgentTimeoutError as e:
        click.echo(str(e), err=True)
        raise SystemExit(1)
    except AgentRunError as e:
        if e.stderr:
            click.echo(e.stderr, err=True)
        if not e.streamed_output.strip() and not e.stderr:
            click.echo("The agent may not support --output-format stream-json.", err=True)
        click.echo(str(e), err=True)
        raise SystemExit(1)


@plan_implement_group.command("accept")
@click.option(
    "--task",
    "-t",
    "task_path",
    type=click.Path(path_type=Path),
    default=None,
    help="Path to task directory. If not set, use current working directory.",
)
@click.option(
    "--draft",
    type=click.Path(path_type=Path),
    default=None,
    help=f"Path to draft plan file (default: <task directory>/{TASK_PLAN_DRAFT}).",
)
def plan_accept(
    task_path: Path | None,
    draft: Path | None,
) -> None:
    """Write the accepted plan from task-plan-draft.md into task.md."""
    task_dir = _resolve_task_dir(task_path)
    draft_path = draft if draft is not None else task_dir / TASK_PLAN_DRAFT
    task_md_path = task_dir / "task.md"
    if not draft_path.exists():
        click.echo(
            f"Draft plan not found: {draft_path}. Run plan mode first (dev plan-implement).",
            err=True,
        )
        raise SystemExit(1)
    content = draft_path.read_text(encoding="utf-8")
    task_md_path.write_text(content, encoding="utf-8")
    click.echo(f"Plan accepted: {task_md_path} updated from {draft_path.name}.")


@click.command("plan-test")
@click.option(
    "--task",
    "-t",
    "task_path",
    type=click.Path(path_type=Path),
    default=None,
    help="Path to task directory. If not set, use current working directory.",
)
@click.option(
    "--agent-cmd",
    type=str,
    default=AGENT_CMD,
    envvar="DEV_AGENT_CMD",
    help="Command to run for the agent (e.g. cursor).",
)
def plan_test_cmd(
    task_path: Path | None,
    agent_cmd: str,
) -> None:
    """Generate a manual E2E testing plan from task context and save it to comms."""
    task_dir = _resolve_task_dir(task_path)
    from dev_sdk.prompts import PLAN_TEST_STREAM_LOG_PREFIX
    stream_log_path = _stream_log_path(task_dir, PLAN_TEST_STREAM_LOG_PREFIX)
    try:
        click.echo("Starting plan-test (stream-json mode)...")
        click.echo(f"Stream log: {stream_log_path}")
        comms_path, script_path = run_plan_test(
            task_dir, agent_cmd, stream_log_path, on_line=_on_line
        )
        click.echo()
        click.echo(click.style(f"Testing plan written to {comms_path.relative_to(task_dir)}", dim=True))
        if script_path:
            click.echo(click.style(f"Executable script written to {script_path.relative_to(task_dir)}", dim=True))
    except (ChatIdNotFoundError, AgentNotFoundError, AgentTimeoutError, AgentRunError) as e:
        click.echo(str(e), err=True)
        raise SystemExit(1)


@click.command("implement")
@click.option(
    "--task",
    "-t",
    "task_path",
    type=click.Path(path_type=Path),
    default=None,
    help="Path to task directory. If not set, use current working directory.",
)
@click.option(
    "--agent-cmd",
    type=str,
    default=AGENT_CMD,
    envvar="DEV_AGENT_CMD",
    help="Command to run for the agent (e.g. cursor).",
)
def implement_cmd(
    task_path: Path | None,
    agent_cmd: str,
) -> None:
    """Run headless implement mode: agent implements the task, commits, then fetches, merges origin/main, and pushes."""
    task_dir = _resolve_task_dir(task_path)
    from dev_sdk.prompts import IMPLEMENT_STREAM_LOG_PREFIX
    stream_log_path = _stream_log_path(task_dir, IMPLEMENT_STREAM_LOG_PREFIX)
    try:
        click.echo("Starting implement (stream-json mode)...")
        click.echo(f"Stream log: {stream_log_path}")
        run_implement(task_dir, agent_cmd, stream_log_path, on_line=_on_line)
        click.echo()
    except (ChatIdNotFoundError, AgentNotFoundError, AgentTimeoutError, AgentRunError) as e:
        click.echo(str(e), err=True)
        raise SystemExit(1)


@click.command("test")
@click.option(
    "--task",
    "-t",
    "task_path",
    type=click.Path(path_type=Path),
    default=None,
    help="Path to task directory. If not set, use current working directory.",
)
@click.option(
    "--agent-cmd",
    type=str,
    default=AGENT_CMD,
    envvar="DEV_AGENT_CMD",
    help="Command to run for the agent (e.g. cursor).",
)
def test_cmd(
    task_path: Path | None,
    agent_cmd: str,
) -> None:
    """Run the latest comms test script, save output to .logs, then run an agent to analyze results and add a markdown report to comms."""
    task_dir = _resolve_task_dir(task_path)

    def on_script_line(line: str) -> None:
        click.echo(line, nl=False)

    try:
        result = run_test(
            task_dir, agent_cmd,
            on_line=_on_line,
            on_script_line=on_script_line,
        )
        if result is None:
            click.echo("Nested dev test skipped (max depth reached).")
            raise SystemExit(0)
        click.echo()
        click.echo(click.style(f"Test results written to {result.relative_to(task_dir)}", dim=True))
    except FileNotFoundError as e:
        click.echo(str(e), err=True)
        raise SystemExit(1)
    except (ChatIdNotFoundError, AgentNotFoundError, AgentTimeoutError, AgentRunError) as e:
        click.echo(str(e), err=True)
        raise SystemExit(1)
