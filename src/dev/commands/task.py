"""Task management commands."""

import re
import subprocess
from pathlib import Path

import click

from dev.task_manager import TaskManager

TASKS_ROOT = Path.home() / "tasks"
AGENT_CMD = "cursor"
AGENT_CREATE_CHAT_ARGS = ["agent", "create-chat"]


def _slugify(title: str) -> str:
    """Convert task title to a safe directory name."""
    s = title.lower().strip()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[-\s]+", "-", s)
    return s or "task"


@click.command("create")
@click.argument("title", type=str)
@click.option(
    "--repo",
    "-r",
    "repo_url",
    required=True,
    type=str,
    help="Git repository URL to clone into the task directory.",
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
        click.echo(f"Task created: {tasks_dir / name}")
        click.echo(f"  Task file: {tasks_dir / name / 'task.md'}")
        click.echo(f"  Launch script: {tasks_dir / name / 'launch-agent.sh'}")
        click.echo(f"  Repo cloned into: {tasks_dir / name / name}")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        raise SystemExit(1)
