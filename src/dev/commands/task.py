"""Task management commands."""

import os
import re
import subprocess
import sys
import threading
from pathlib import Path

import click

SPINNER_CHARS = ["|", "/", "-", "\\"]

from dev.comms import add_comms, comms_dir, read_index
from dev.repo_config import resolve_repo
from dev.task_manager import TaskManager

TASKS_ROOT = Path.home() / "tasks"
AGENT_CMD = "cursor"
AGENT_CREATE_CHAT_ARGS = ["agent", "create-chat"]
AGENT_CHAT_ID_FILE = "agent-chat-id"
TASK_PLAN_DRAFT = "task-plan-draft.md"

PLAN_MODE_PROMPT = """Read the task context in the `comms` directory (files listed in comms/index.txt, in order). Produce a more detailed description and a step-by-step plan for the task. Ask any follow-up questions you need. Output only the detailed description and plan as markdown (no preamble or meta-commentary). Do not make any edits or run any tools—only output the plan."""


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


def _run_plan_mode(
    task_name: str | None,
    tasks_dir: Path,
    agent_cmd: str,
) -> None:
    """Run agent in headless plan-only mode; output is written to task-plan-draft.md."""
    if task_name is not None:
        task_dir = tasks_dir / task_name
        chat_id_path = task_dir / AGENT_CHAT_ID_FILE
    else:
        task_dir = Path.cwd()
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

    argv = [
        agent_cmd,
        "agent",
        "--print",
        "--plan",
        "--resume",
        chat_id,
        "--workspace",
        str(task_dir),
        "--trust",
        PLAN_MODE_PROMPT,
    ]
    result_box: list[subprocess.CompletedProcess[str] | None] = [None]
    exc_box: list[BaseException | None] = [None]

    def run_agent() -> None:
        try:
            result_box[0] = subprocess.run(
                argv,
                cwd=str(task_dir),
                capture_output=True,
                text=True,
                timeout=300,
            )
        except FileNotFoundError as e:
            exc_box[0] = e
        except subprocess.TimeoutExpired as e:
            exc_box[0] = e

    click.echo("Starting plan (running agent in headless plan-only mode)...")
    thread = threading.Thread(target=run_agent)
    thread.start()
    n = 0
    while thread.is_alive():
        click.echo(f"\rPlanning {SPINNER_CHARS[n % 4]} ", nl=False)
        if sys.stdout:
            sys.stdout.flush()
        thread.join(timeout=0.15)
        n += 1
    click.echo("\r" + " " * 12 + "\r", nl=False)
    if sys.stdout:
        sys.stdout.flush()

    if exc_box[0] is not None:
        e = exc_box[0]
        if isinstance(e, subprocess.TimeoutExpired):
            click.echo("Agent plan mode timed out.", err=True)
        elif isinstance(e, FileNotFoundError):
            click.echo(f"Agent command not found: {agent_cmd}", err=True)
        else:
            click.echo(str(e), err=True)
        raise SystemExit(1)

    result = result_box[0]
    assert result is not None
    out = (result.stdout or "").strip()
    if result.returncode != 0 and not out:
        click.echo(result.stderr or f"Agent exited with code {result.returncode}", err=True)
        raise SystemExit(1)

    draft_path = task_dir / TASK_PLAN_DRAFT
    draft_path.write_text(out, encoding="utf-8")
    comms_path = add_comms(task_dir, "agent", out, kind="plan")
    click.echo("Plan ready:\n")
    click.echo(out)
    click.echo(f"\nPlan written to {comms_path.relative_to(task_dir)}")
    if result.returncode != 0:
        raise SystemExit(result.returncode)


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
@click.option(
    "--agent-cmd",
    type=str,
    default=AGENT_CMD,
    envvar="DEV_AGENT_CMD",
    help="Command to run for the agent (e.g. cursor).",
)
def launch_interact(
    task_name: str | None,
    tasks_dir: Path,
    agent_cmd: str,
) -> None:
    """Interact with the agent for this task (resume chat using saved chat ID)."""
    if task_name is not None:
        task_dir = tasks_dir / task_name
        chat_id_path = task_dir / AGENT_CHAT_ID_FILE
    else:
        task_dir = Path.cwd()
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
    "--task-dir",
    "-t",
    "task_dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Task directory (root containing .venv/<task-name>). Default: current working directory.",
)
def activate_path(task_dir: Path | None) -> None:
    """Print path to the task venv activate script for use with: source $(dev activate-path)."""
    task_root = (task_dir or Path.cwd()).resolve()
    activate_script = _venv_activate_path(task_root)
    if not activate_script.exists():
        click.echo(
            f"Activate script not found: {activate_script}. Run from a task directory or use --task-dir.",
            err=True,
        )
        raise SystemExit(1)
    click.echo(str(activate_script))


@click.command("plan")
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
@click.option(
    "--agent-cmd",
    type=str,
    default=AGENT_CMD,
    envvar="DEV_AGENT_CMD",
    help="Command to run for the agent (e.g. cursor).",
)
def plan_cmd(
    task_name: str | None,
    tasks_dir: Path,
    agent_cmd: str,
) -> None:
    """Run headless plan mode; plan is written to the comms directory."""
    _run_plan_mode(task_name=task_name, tasks_dir=tasks_dir, agent_cmd=agent_cmd)
