"""Task management commands."""

import os
import re
import subprocess
from pathlib import Path

import click

from dev.repo_config import resolve_repo
from dev.task_manager import TaskManager

TASKS_ROOT = Path.home() / "tasks"
AGENT_CMD = "cursor"
AGENT_CREATE_CHAT_ARGS = ["agent", "create-chat"]
AGENT_CHAT_ID_FILE = "agent-chat-id"


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
    "--description",
    "-d",
    "description",
    required=True,
    type=str,
    help="Task description or goal.",
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
    description: str,
    tasks_dir: Path,
) -> None:
    """Create a new task: create directory, task file, agent chat, and clone repo."""
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
            description=description,
            repo_url=repo_url,
            agent_cmd=AGENT_CMD,
            agent_create_chat_args=AGENT_CREATE_CHAT_ARGS,
        )
        task_dir = tasks_dir / name
        repo_dir = _repo_name_from_url(repo_url)
        click.echo(f"Task created: {task_dir}")
        click.echo(f"  Task file: {task_dir / 'task.md'}")
        click.echo(f"  Chat ID file: {task_dir / AGENT_CHAT_ID_FILE}")
        click.echo(f"  Repo cloned into: {task_dir / repo_dir}")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)


@click.command("agent")
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
def launch_agent(
    task_name: str | None,
    tasks_dir: Path,
    agent_cmd: str,
) -> None:
    """Launch the agent for this task (resume chat using saved chat ID)."""
    if task_name is not None:
        task_dir = tasks_dir / task_name
        chat_id_path = task_dir / AGENT_CHAT_ID_FILE
    else:
        chat_id_path = Path.cwd() / AGENT_CHAT_ID_FILE

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

    # Prompt the agent to read task.md and do it
    prompt = "Read the task.md file and do it."
    # Launch agent the same way launch-agent.sh did: exec agent --force --resume <chat_id>
    argv = [agent_cmd, "agent", "--force", "--resume", chat_id, prompt]
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
