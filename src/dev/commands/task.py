"""Task management commands."""

import json
import os
import re
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

import click

SPINNER_CHARS = ["|", "/", "-", "\\"]

from dev.comms import add_comms, comms_dir, index_path, next_sequence, read_index
from dev.repo_config import resolve_repo
from dev.task_manager import TaskManager

TASKS_ROOT = Path.home() / "tasks"
AGENT_CMD = "cursor"
AGENT_CREATE_CHAT_ARGS = ["agent", "create-chat"]
AGENT_CHAT_ID_FILE = "agent-chat-id"
TASK_PLAN_DRAFT = "task-plan-draft.md"
PLAN_LOGS_DIR = ".logs"

PLAN_MODE_PROMPT = """Read the task context in the `comms` directory (files listed in comms/index.txt, in order). Produce a more detailed description and a step-by-step plan for the task. Ask any follow-up questions you need. Output only the detailed description and plan as markdown (no preamble or meta-commentary)."""
PLAN_IMPLEMENT_STREAM_LOG_PREFIX = "dev-plan-stream-"

IMPLEMENT_MODE_PROMPT = """Read the task context in the `comms` directory (files listed in comms/index.txt, in order). Implement the task and commit when done. When done, in the git project directory (the repo subdirectory under the task root, not the task root itself): fetch from origin, merge origin/main into the current branch, then push the current branch to origin."""
IMPLEMENT_STREAM_LOG_PREFIX = "dev-implement-stream-"

PLAN_TEST_MODE_PROMPT = """Read the task context in the `comms` directory (files listed in comms/index.txt, in order). Produce two artifacts in this exact order, with no other text before or after:

1) A manual, end-to-end testing plan in markdown. It must validate all changes from the current task. Include feature testing (steps to verify the task's goals) and regression testing (steps to verify existing behavior is unchanged). Do not run or reference unit tests (e.g. pytest): unit tests are run separately and do not count as end-to-end regression testing. The plan is Unix-only; Windows is out of scope. Every command in the plan must use the task's virtual environment: from the task root use .venv/<task_name>/bin/<command> (or activate the venv first). This is not unit or automated test code; it is a step-by-step manual test plan. Output only the plan as markdown.

2) On a new line, the exact delimiter line: ---BASH SCRIPT---

3) An executable bash script that runs the plan. The script must be very easy for a human to read: prioritize readability over fancy printouts or verification. Use shebang #!/usr/bin/env bash and set -e. Run each step from the plan using the actual venv path for CLI invocations. The script must never contain angle brackets or placeholders (e.g. do not write .venv/<task_name>/bin/<command> in the script—bash would interpret < as a redirect). Use the literal path with the real task name and command, e.g. .venv/bash-dev-plan-test/bin/dev. The script does not need to contain verification logic—it will be run by an agent that verifies the output. Use simple checks only where they are easy to read; if verification would be too complex to encode in bash, leave a comment describing the expected output instead. The script should be dead-simple: just straightforward bash commands, no progress counters or extra logic. Output only the script source (no markdown code fence)."""

PLAN_TEST_BASH_DELIMITER = "\n---BASH SCRIPT---\n"
PLAN_TEST_SCRIPT_PREFIX = "run-plan.sh"
PLAN_TEST_STREAM_LOG_PREFIX = "dev-plan-test-stream-"

DEV_TEST_RUN_LOG_PREFIX = "dev-test-run-"
DEV_TEST_STREAM_LOG_PREFIX = "dev-test-stream-"


def _latest_run_plan_script(task_dir: Path) -> Path | None:
    """Return path to the latest *-run-plan.sh in comms (last in index order)."""
    cdir = comms_dir(task_dir)
    if not cdir.exists():
        return None
    order = read_index(task_dir)
    # Last occurrence in index that is a run-plan script (matches plan-test naming).
    script_names = [n for n in order if n.endswith("run-plan.sh") and "-run-plan" in n]
    if not script_names:
        return None
    return cdir / script_names[-1]


def _test_results_prompt(run_log_rel: str, script_exit_code: int | None) -> str:
    """Build prompt for test-results agent; run_log_rel is path relative to task root."""
    exit_note = ""
    if script_exit_code is not None and script_exit_code != 0:
        exit_note = f" The test script exited with code {script_exit_code}.\n\n"
    return f"""Read the test run output from the file at {run_log_rel} (relative to the task workspace).{exit_note}Analyze the results: explain what passed or failed and why. Propose any fixes needed. Output only a single markdown document (no preamble or meta-commentary)."""


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


def _run_agent_ask_stream_json(
    task_path: Path | None,
    agent_cmd: str,
    prompt: str,
    stream_log_prefix: str,
    start_message: str,
    timeout_message: str,
) -> tuple[Path, str]:
    """Run agent in ask mode with stream-json; return (task_dir, streamed_output). Exits on failure."""
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

    argv = [
        agent_cmd,
        "agent",
        "--print",
        "--output-format",
        "stream-json",
        "--stream-partial-output",
        "--mode",
        "ask",
        "--resume",
        chat_id,
        "--workspace",
        str(task_dir),
        "--trust",
        prompt,
    ]
    buffer: list[str] = []
    buffer_lock = threading.Lock()
    read_error: list[BaseException | None] = [None]
    logs_dir = task_dir / PLAN_LOGS_DIR
    logs_dir.mkdir(exist_ok=True)
    stream_log_name = f"{stream_log_prefix}{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.log"
    stream_log_path = logs_dir / stream_log_name
    thinking_started: list[bool] = [False]
    thinking_at_line_start: list[bool] = [True]

    def read_stdout(proc: subprocess.Popen[str]) -> None:
        try:
            assert proc.stdout is not None
            with open(stream_log_path, "w", encoding="utf-8") as log:
                for line in proc.stdout:
                    decoded = line if isinstance(line, str) else line.decode("utf-8", errors="replace")
                    log.write(decoded)
                    if decoded and not decoded.endswith("\n"):
                        log.write("\n")
                    log.flush()
                    formatted, is_thinking = _format_stream_line_for_console(decoded.strip())
                    if formatted is not None and sys.stdout:
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
                    with buffer_lock:
                        buffer.append(decoded)
        except Exception as e:
            read_error[0] = e

    click.echo(start_message)
    click.echo(f"Stream log: {stream_log_path}")
    try:
        proc = subprocess.Popen(
            argv,
            cwd=str(task_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
    except FileNotFoundError:
        click.echo(f"Agent command not found: {agent_cmd}", err=True)
        raise SystemExit(1)

    reader = threading.Thread(target=read_stdout, args=(proc,))
    reader.start()
    reader.join(timeout=300)
    if reader.is_alive():
        proc.kill()
        proc.wait()
        click.echo(timeout_message, err=True)
        raise SystemExit(1)

    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()

    stderr_output = ""
    if proc.stderr:
        stderr_output = proc.stderr.read()

    if read_error[0] is not None:
        click.echo(str(read_error[0]), err=True)
        raise SystemExit(1)

    streamed_output = "".join(buffer)
    if proc.returncode != 0:
        if stderr_output:
            click.echo(stderr_output, err=True)
        if not streamed_output.strip() and not stderr_output:
            click.echo(f"Agent exited with code {proc.returncode} (no output).", err=True)
            click.echo(
                "The agent may not support --output-format stream-json.",
                err=True,
            )
        raise SystemExit(1)

    return task_dir, streamed_output


def _run_plan_implement_mode(
    task_path: Path | None,
    agent_cmd: str,
) -> None:
    """Run agent in headless plan-implement mode; output is written to task-plan-draft.md and comms."""
    task_dir, streamed_output = _run_agent_ask_stream_json(
        task_path,
        agent_cmd,
        PLAN_MODE_PROMPT,
        PLAN_IMPLEMENT_STREAM_LOG_PREFIX,
        "Starting plan (stream-json mode)...",
        "Agent plan mode timed out.",
    )
    plan_text = _extract_plan_from_stream_json(streamed_output)
    draft_path = task_dir / TASK_PLAN_DRAFT
    draft_path.write_text(plan_text, encoding="utf-8")
    comms_path = add_comms(task_dir, "agent", plan_text, kind="plan")
    click.echo()
    click.echo()
    click.echo(click.style(f"Plan written to {comms_path.relative_to(task_dir)}", dim=True))


def _run_plan_test_mode(
    task_path: Path | None,
    agent_cmd: str,
) -> None:
    """Run agent to generate a manual E2E testing plan and executable bash script; both written to comms."""
    task_dir, streamed_output = _run_agent_ask_stream_json(
        task_path,
        agent_cmd,
        PLAN_TEST_MODE_PROMPT,
        PLAN_TEST_STREAM_LOG_PREFIX,
        "Starting plan-test (stream-json mode)...",
        "Agent plan-test mode timed out.",
    )
    full_output = _extract_plan_from_stream_json(streamed_output)
    if PLAN_TEST_BASH_DELIMITER in full_output:
        plan_text, _, script_block = full_output.partition(PLAN_TEST_BASH_DELIMITER)
        plan_text = plan_text.strip()
        script_content = script_block.strip()
    else:
        plan_text = full_output.strip()
        script_content = None

    script_filename = None
    if script_content:
        plan_seq = next_sequence(task_dir)  # next add_comms will use this
        script_seq = plan_seq + 1
        script_filename = f"{script_seq:03d}-{PLAN_TEST_SCRIPT_PREFIX}"
        plan_text += f"\n\n## How to run\n\nExecute: `./comms/{script_filename}` or `bash comms/{script_filename}`\n"

    comms_path = add_comms(task_dir, "agent", plan_text, kind="plan-test")
    click.echo()
    click.echo(click.style(f"Testing plan written to {comms_path.relative_to(task_dir)}", dim=True))

    if script_content and script_filename:
        script_path = comms_dir(task_dir) / script_filename
        script_path.write_text(script_content.strip() + "\n", encoding="utf-8")
        script_path.chmod(0o755)
        with open(index_path(task_dir), "a", encoding="utf-8") as f:
            f.write(script_filename + "\n")
        click.echo(click.style(f"Executable script written to {script_path.relative_to(task_dir)}", dim=True))


def _run_test_mode(
    task_path: Path | None,
    agent_cmd: str,
) -> None:
    """Run latest comms test script, save output to .logs, then agent analyzes and writes comms."""
    task_dir = _resolve_task_dir(task_path)
    cdir = comms_dir(task_dir)
    if not cdir.exists():
        click.echo("Comms directory not found. Run from a task directory or use --task.", err=True)
        raise SystemExit(1)
    script_path = _latest_run_plan_script(task_dir)
    if script_path is None or not script_path.exists():
        click.echo(
            "No test script found in comms (expecting *-run-plan.sh). Run dev plan-test first.",
            err=True,
        )
        raise SystemExit(1)
    logs_dir = task_dir / PLAN_LOGS_DIR
    logs_dir.mkdir(exist_ok=True)
    run_log_name = f"{DEV_TEST_RUN_LOG_PREFIX}{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.log"
    run_log_path = logs_dir / run_log_name
    run_output_parts: list[str] = []
    with open(run_log_path, "w", encoding="utf-8") as log_file:
        proc = subprocess.Popen(
            [str(script_path)],
            cwd=str(task_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            log_file.write(line)
            if line and not line.endswith("\n"):
                log_file.write("\n")
            log_file.flush()
            run_output_parts.append(line)
            click.echo(line, nl=False)
        proc.wait()
    run_output = "".join(run_output_parts)
    run_log_rel = f"{PLAN_LOGS_DIR}/{run_log_name}"
    if proc.returncode != 0:
        click.echo(f"Test script exited with code {proc.returncode}. Run log: {run_log_path}", err=True)
    else:
        click.echo(f"Run log: {run_log_path}")
    prompt = _test_results_prompt(run_log_rel, proc.returncode)
    task_dir_after, streamed_output = _run_agent_ask_stream_json(
        task_path,
        agent_cmd,
        prompt,
        DEV_TEST_STREAM_LOG_PREFIX,
        "Starting test analysis (stream-json mode)...",
        "Agent test analysis timed out.",
    )
    content = _extract_plan_from_stream_json(streamed_output)
    comms_path = add_comms(task_dir_after, "agent", content, kind="test-results")
    click.echo()
    click.echo(click.style(f"Test results written to {comms_path.relative_to(task_dir_after)}", dim=True))


def _run_implement_mode(
    task_path: Path | None,
    agent_cmd: str,
) -> None:
    """Run agent in headless implement mode; stream output to console and .logs only."""
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

    argv = [
        agent_cmd,
        "agent",
        "--print",
        "--force",
        "--sandbox",
        "disabled",
        "--output-format",
        "stream-json",
        "--stream-partial-output",
        "--resume",
        chat_id,
        "--workspace",
        str(task_dir),
        "--trust",
        IMPLEMENT_MODE_PROMPT,
    ]
    buffer: list[str] = []
    buffer_lock = threading.Lock()
    read_error: list[BaseException | None] = [None]
    logs_dir = task_dir / PLAN_LOGS_DIR
    logs_dir.mkdir(exist_ok=True)
    stream_log_name = f"{IMPLEMENT_STREAM_LOG_PREFIX}{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.log"
    stream_log_path = logs_dir / stream_log_name
    thinking_started: list[bool] = [False]
    thinking_at_line_start: list[bool] = [True]

    def read_stdout(proc: subprocess.Popen[str]) -> None:
        try:
            assert proc.stdout is not None
            with open(stream_log_path, "w", encoding="utf-8") as log:
                for line in proc.stdout:
                    decoded = line if isinstance(line, str) else line.decode("utf-8", errors="replace")
                    log.write(decoded)
                    if decoded and not decoded.endswith("\n"):
                        log.write("\n")
                    log.flush()
                    formatted, is_thinking = _format_stream_line_for_console(decoded.strip())
                    if formatted is not None and sys.stdout:
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
                    with buffer_lock:
                        buffer.append(decoded)
        except Exception as e:
            read_error[0] = e

    click.echo("Starting implement (stream-json mode)...")
    click.echo(f"Stream log: {stream_log_path}")
    try:
        proc = subprocess.Popen(
            argv,
            cwd=str(task_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
    except FileNotFoundError:
        click.echo(f"Agent command not found: {agent_cmd}", err=True)
        raise SystemExit(1)

    reader = threading.Thread(target=read_stdout, args=(proc,))
    reader.start()
    reader.join(timeout=300)
    if reader.is_alive():
        proc.kill()
        proc.wait()
        click.echo("Agent implement mode timed out.", err=True)
        raise SystemExit(1)

    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()

    stderr_output = ""
    if proc.stderr:
        stderr_output = proc.stderr.read()

    if read_error[0] is not None:
        click.echo(str(read_error[0]), err=True)
        raise SystemExit(1)

    if proc.returncode != 0:
        streamed_output = "".join(buffer)
        if stderr_output:
            click.echo(stderr_output, err=True)
        if not streamed_output.strip() and not stderr_output:
            click.echo(f"Agent exited with code {proc.returncode} (no output).", err=True)
            click.echo(
                "The agent may not support --output-format stream-json.",
                err=True,
            )
        raise SystemExit(1)

    click.echo()


def _extract_plan_from_stream_json(streamed_output: str) -> str:
    """Extract plan markdown from streamed JSON (Cursor agent stream-json format)."""
    lines = [line.strip() for line in streamed_output.splitlines() if line.strip()]
    if not lines:
        return streamed_output
    # Prefer final "result" event (full plan text)
    for line in reversed(lines):
        try:
            obj = json.loads(line)
            if isinstance(obj, dict) and obj.get("type") == "result" and "result" in obj:
                result = obj["result"]
                if isinstance(result, str) and result.strip():
                    return result.strip()
        except json.JSONDecodeError:
            pass
    # Fall back: accumulate assistant message text and content/text/delta fields
    parts: list[str] = []
    for line in lines:
        try:
            obj = json.loads(line)
            if isinstance(obj, dict):
                if obj.get("type") == "assistant" and "message" in obj:
                    msg = obj["message"]
                    if isinstance(msg, dict) and "content" in msg:
                        for item in msg["content"] if isinstance(msg["content"], list) else []:
                            if isinstance(item, dict) and item.get("type") == "text" and "text" in item:
                                parts.append(item["text"])
                        continue
                for key in ("content", "text", "delta", "result"):
                    if key in obj and isinstance(obj[key], str):
                        parts.append(obj[key])
                        break
            elif isinstance(obj, str):
                parts.append(obj)
        except json.JSONDecodeError:
            parts.append(line)
    if parts:
        return "".join(parts).strip() or "\n".join(parts)
    return streamed_output


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
    _run_plan_test_mode(task_path=task_path, agent_cmd=agent_cmd)


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
    _run_implement_mode(task_path=task_path, agent_cmd=agent_cmd)


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
    _run_test_mode(task_path=task_path, agent_cmd=agent_cmd)
