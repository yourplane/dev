"""Task management commands."""

import json
import os
import re
import sys
from pathlib import Path

import click

from dev_sdk.agent_run import (
    AGENT_CHAT_ID_FILE,
    AgentRunError,
    AgentTestSkipped,
    TASK_PLAN_DRAFT,
    run_implement,
    run_plan_implement,
    run_plan_test,
    run_test,
)
from dev_sdk.comms import add_comms, comms_dir, read_index
from dev_sdk.repo_config import resolve_repo
from dev_sdk.task_manager import TaskManager

TASKS_ROOT = Path.home() / "tasks"
AGENT_CMD = "cursor"
AGENT_CREATE_CHAT_ARGS = ["agent", "create-chat"]


def _task_dir_from_options(
    task_name: str | None, tasks_dir: Path
) -> tuple[Path, Path]:
    """Resolve task directory and comms dir. Raises on missing dir or missing comms."""
    if task_name is not None:
        task_dir = tasks_dir / task_name
    else:
        task_dir = Path.cwd()
    if not task_dir.exists() or not task_dir.is_dir():
        click.echo(f"Task directory not found: {task_dir}", err=True)
        raise SystemExit(1)
    return task_dir, comms_dir(task_dir)


def _resolve_task_dir(task_path: Path | None) -> Path:
    """Resolve task directory: given path if provided, else current working directory."""
    return (task_path or Path.cwd()).resolve()


def _format_stream_line_for_console(line: str) -> tuple[str | None, bool]:
    """Parse stream line; return (text_to_print, is_thinking). None means skip this line."""
    try:
        obj = json.loads(line)
        if not isinstance(obj, dict):
            return None, False
        if obj.get("type") == "assistant" and "message" in obj:
            msg = obj["message"]
            if isinstance(msg, dict) and "content" in msg:
                texts: list[str] = []
                for item in msg["content"] if isinstance(msg["content"], list) else []:
                    if isinstance(item, dict) and item.get("type") == "text" and "text" in item:
                        texts.append(item["text"])
                if texts:
                    return "".join(texts), False
        if obj.get("type") == "thinking" and obj.get("subtype") == "delta" and "text" in obj:
            text = obj["text"]
            if isinstance(text, str):
                # Indent thinking so it’s visually distinct; indent only at line starts (done in reader to avoid spaces between deltas)
                return text, True
        return None, False
    except json.JSONDecodeError:
        return None, False


def _make_stream_format_callback():
    """Return an on_stream_line callback that formats and prints to stdout (Thinking: + dim, etc.)."""
    thinking_started: list[bool] = [False]
    thinking_at_line_start: list[bool] = [True]

    def on_line(line: str) -> None:
        decoded = line.strip() if line else ""
        if not decoded:
            return
        formatted, is_thinking = _format_stream_line_for_console(decoded)
        if formatted is None or not sys.stdout:
            return
        if is_thinking:
            if not thinking_started[0]:
                thinking_started[0] = True
                out = "\n  Thinking:\n  "
                thinking_at_line_start[0] = False
            else:
                out = ""
            for ch in formatted:
                if thinking_at_line_start[0]:
                    out += "  "
                    thinking_at_line_start[0] = False
                out += ch
                if ch == "\n":
                    thinking_at_line_start[0] = True
            if out:
                sys.stdout.write(click.style(out, dim=True))
        else:
            sys.stdout.write(formatted)
        sys.stdout.flush()

    return on_line


def _run_plan_implement_mode(task_path: Path | None) -> None:
    """Run agent plan-implement via SDK; echo progress and result."""
    task_dir = _resolve_task_dir(task_path)
    click.echo("Starting plan (stream-json mode)...")
    try:
        result = run_plan_implement(
            task_dir,
            on_stream_line=_make_stream_format_callback(),
            on_start=lambda p: click.echo(f"Stream log: {p}"),
        )
        click.echo()
        click.echo()
        click.echo(click.style(f"Plan written to {result.comms_path.relative_to(task_dir)}", dim=True))
    except AgentRunError as e:
        click.echo(str(e), err=True)
        raise SystemExit(1)


def _run_plan_test_mode(task_path: Path | None) -> None:
    """Run agent plan-test via SDK; echo progress and result."""
    task_dir = _resolve_task_dir(task_path)
    click.echo("Starting plan-test (stream-json mode)...")
    try:
        result = run_plan_test(
            task_dir,
            on_stream_line=_make_stream_format_callback(),
            on_start=lambda p: click.echo(f"Stream log: {p}"),
        )
        click.echo()
        click.echo(click.style(f"Testing plan written to {result.comms_path.relative_to(task_dir)}", dim=True))
        if result.script_path:
            click.echo(click.style(f"Executable script written to {result.script_path.relative_to(task_dir)}", dim=True))
    except AgentRunError as e:
        click.echo(str(e), err=True)
        raise SystemExit(1)


def _run_implement_mode(task_path: Path | None) -> None:
    """Run agent implement via SDK; echo progress."""
    task_dir = _resolve_task_dir(task_path)
    click.echo("Starting implement (stream-json mode)...")
    try:
        result = run_implement(
            task_dir,
            on_stream_line=_make_stream_format_callback(),
            on_start=lambda p: click.echo(f"Stream log: {p}"),
        )
        click.echo()
    except AgentRunError as e:
        click.echo(str(e), err=True)
        raise SystemExit(1)


def _run_test_mode(task_path: Path | None) -> None:
    """Run test flow via SDK (script + agent); echo progress and result."""
    task_dir = _resolve_task_dir(task_path)

    def on_script_line(line: str) -> None:
        click.echo(line, nl=False)

    def on_before_agent() -> None:
        click.echo("Starting test analysis (stream-json mode)...")

    def on_start(path: Path) -> None:
        click.echo(f"Stream log: {path}")

    try:
        result = run_test(
            task_dir,
            on_stream_line=_make_stream_format_callback(),
            on_script_line=on_script_line,
            on_before_agent=on_before_agent,
            on_start=on_start,
        )
        click.echo(f"Stream log: {result.stream_log_path}")
        if result.script_exit_code != 0:
            click.echo(
                f"Test script exited with code {result.script_exit_code}. Run log: {result.run_log_path}",
                err=True,
            )
        else:
            click.echo(f"Run log: {result.run_log_path}")
        click.echo()
        click.echo(click.style(f"Test results written to {result.comms_path.relative_to(task_dir)}", dim=True))
    except AgentTestSkipped as e:
        click.echo(str(e))
        raise SystemExit(0)
    except AgentRunError as e:
        click.echo(str(e), err=True)
        raise SystemExit(1)


def _slugify(title: str) -> str:
    """Convert task title to a safe directory name."""
    s = title.lower().strip()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[-\s]+", "-", s)
    return s or "task"


def _repo_name_from_url(repo_url: str) -> str:
    """Derive repo directory name from URL (e.g. .../repo.git -> repo)."""
    name = repo_url.rstrip("/").split("/")[-1]
    return name.removesuffix(".git") if name.endswith(".git") else name or "repo"


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
    name = _slugify(title)
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
        repo_dir = _repo_name_from_url(repo_url)
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
    chat_id_path = task_dir / AGENT_CHAT_ID_FILE

    if not chat_id_path.exists():
        click.echo(
            f"Chat ID file not found: {chat_id_path}. Run from a task directory or use --task.",
            err=True,
        )
        raise SystemExit(1)

    chat_id = chat_id_path.read_text(encoding="utf-8").strip()
    if not chat_id:
        click.echo("Chat ID file is empty.", err=True)
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
    # Default: list comms
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
    """Return path to the task venv activate script: task_root/.venv/{task_name}/bin/activate."""
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
@click.pass_context
def plan_implement_group(
    ctx: click.Context,
    task_path: Path | None,
) -> None:
    """Run headless plan-implement mode or manage task plans (e.g. accept draft into task.md)."""
    if ctx.invoked_subcommand is None:
        _run_plan_implement_mode(task_path=task_path)


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
def plan_test_cmd(task_path: Path | None) -> None:
    """Generate a manual E2E testing plan from task context and save it to comms."""
    _run_plan_test_mode(task_path=task_path)


@click.command("implement")
@click.option(
    "--task",
    "-t",
    "task_path",
    type=click.Path(path_type=Path),
    default=None,
    help="Path to task directory. If not set, use current working directory.",
)
def implement_cmd(task_path: Path | None) -> None:
    """Run headless implement mode: agent implements the task, commits, then fetches, merges origin/main, and pushes."""
    _run_implement_mode(task_path=task_path)


@click.command("test")
@click.option(
    "--task",
    "-t",
    "task_path",
    type=click.Path(path_type=Path),
    default=None,
    help="Path to task directory. If not set, use current working directory.",
)
def test_cmd(task_path: Path | None) -> None:
    """Run the latest comms test script, save output to .logs, then run an agent to analyze results and add a markdown report to comms."""
    _run_test_mode(task_path=task_path)
