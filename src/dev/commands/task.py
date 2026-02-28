"""Task management commands."""

import os
import re
import subprocess
import sys
import threading
from pathlib import Path

import click

SPINNER_CHARS = ["|", "/", "-", "\\"]

from dev.repo_config import resolve_repo
from dev.task_manager import TaskManager

TASKS_ROOT = Path.home() / "tasks"
AGENT_CMD = "cursor"
AGENT_CREATE_CHAT_ARGS = ["agent", "create-chat"]
AGENT_CHAT_ID_FILE = "agent-chat-id"
TASK_PLAN_DRAFT = "task-plan-draft.md"

PLAN_MODE_PROMPT = """Read the task.md file in this workspace. Produce a more detailed description and a step-by-step plan for the task. Ask any follow-up questions you need. Output only the detailed description and plan as markdown (no preamble or meta-commentary). Do not make any edits or run any tools—only output the plan."""


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
    default=None,
    type=str,
    help="Task description or goal. If not set, you will be prompted.",
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
    description: str | None,
    tasks_dir: Path,
) -> None:
    """Create a new task: create directory, task file, agent chat, and clone repo."""
    if description is None:
        description = click.prompt("Description")
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
            on_progress=click.echo,
        )
        task_dir = tasks_dir / name
        repo_dir = _repo_name_from_url(repo_url)
        click.echo(f"Task created: {task_dir}")
        click.echo(f"  Task file: {task_dir / 'task.md'}")
        click.echo(f"  Chat ID file: {task_dir / AGENT_CHAT_ID_FILE}")
        click.echo(f"  Repo cloned into: {task_dir / repo_dir}")
        venv_dir = task_dir / name
        if venv_dir.exists():
            click.echo(f"  Venv: {venv_dir} (repo installed in editable mode)")
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
@click.option(
    "--plan",
    "plan_mode",
    is_flag=True,
    default=False,
    help="Run agent in headless plan-only mode; output is written to task-plan-draft.md. Then run 'dev plan accept' to write it into task.md.",
)
def launch_agent(
    task_name: str | None,
    tasks_dir: Path,
    agent_cmd: str,
    plan_mode: bool,
) -> None:
    """Launch the agent for this task (resume chat using saved chat ID)."""
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

    if plan_mode:
        # Headless plan-only: run agent with --print and --plan, capture stdout, write to draft file
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
        click.echo("Plan ready:\n")
        click.echo(out)
        click.echo(f"\nPlan written to {draft_path}")
        if result.returncode != 0:
            raise SystemExit(result.returncode)
        return

    # Interactive: exec into the agent
    prompt = "Read the task.md file and do it."
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


@click.group("plan")
def plan_group() -> None:
    """Manage task plans: accept a draft plan into task.md after reviewing."""
    pass


@plan_group.command("accept")
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
    "--draft",
    type=click.Path(path_type=Path),
    default=None,
    help=f"Path to draft plan file (default: <task-dir>/{TASK_PLAN_DRAFT}).",
)
def plan_accept(
    task_name: str | None,
    tasks_dir: Path,
    draft: Path | None,
) -> None:
    """Write the accepted plan from task-plan-draft.md into task.md."""
    if task_name is not None:
        task_dir = tasks_dir / task_name
    else:
        task_dir = Path.cwd()

    draft_path = draft if draft is not None else task_dir / TASK_PLAN_DRAFT
    task_path = task_dir / "task.md"

    if not draft_path.exists():
        click.echo(
            f"Draft plan not found: {draft_path}. Run the agent in plan mode first (dev agent --plan).",
            err=True,
        )
        raise SystemExit(1)

    content = draft_path.read_text(encoding="utf-8")
    task_path.write_text(content, encoding="utf-8")
    click.echo(f"Plan accepted: {task_path} updated from {draft_path.name}.")
