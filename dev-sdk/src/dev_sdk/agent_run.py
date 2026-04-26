"""Agent task commands: run agent in stream-json mode, parse output, write comms and logs."""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from dev_sdk.comms import add_comms, comms_dir, index_path, next_sequence, read_index

# Agent command: constant or from env (SDK chooses; no parameter from CLI).
AGENT_CMD_DEFAULT = "cursor"
DEV_AGENT_CMD_ENV = "DEV_AGENT_CMD"

AGENT_CHAT_ID_FILE = "agent-chat-id"
PLAN_LOGS_DIR = ".logs"
TASK_PLAN_DRAFT = "task-plan-draft.md"

PLAN_IMPLEMENT_STREAM_LOG_PREFIX = "dev-plan-stream-"
IMPLEMENT_STREAM_LOG_PREFIX = "dev-implement-stream-"
DO_STREAM_LOG_PREFIX = "dev-do-stream-"
PLAN_TEST_STREAM_LOG_PREFIX = "dev-plan-test-stream-"
DEV_TEST_RUN_LOG_PREFIX = "dev-test-run-"
DEV_TEST_STREAM_LOG_PREFIX = "dev-test-stream-"

PLAN_MODE_PROMPT = """Read the task context in the `comms` directory (files listed in comms/index.txt, in order). There may be new entries in the comms directory since you last read it—double-check comms/index.txt and read any new files before proceeding. Produce a more detailed description and a step-by-step plan for the task. Ask any follow-up questions you need. Output only the detailed description and plan as markdown (no preamble or meta-commentary)."""

IMPLEMENT_MODE_PROMPT = """Read the task context in the `comms` directory (files listed in comms/index.txt, in order). There may be new entries in the comms directory since you last read it—double-check comms/index.txt and read any new files before proceeding. Implement the task and commit when done. When done, in the git project directory (the repo subdirectory under the task root, not the task root itself): fetch from origin, merge origin/main into the current branch, then push the current branch to origin."""

PLAN_TEST_MODE_PROMPT = """Read the task context in the `comms` directory (files listed in comms/index.txt, in order). Produce two artifacts in this exact order, with no other text before or after:

1) A manual, end-to-end testing plan in markdown. It must validate the entire task—all work and behavior described in the task context from the beginning, not just the most recent changes. Include feature testing (steps to verify the task's goals) and regression testing (steps to verify existing behavior is unchanged). Do not run or reference unit tests (e.g. pytest): unit tests are run separately and do not count as end-to-end regression testing. The plan is Unix-only; Windows is out of scope. Use system or project-appropriate commands (e.g. from PATH or the cloned repo). This is not unit or automated test code; it is a step-by-step manual test plan. Output only the plan as markdown.

2) On a new line, the exact delimiter line: ---BASH SCRIPT---

3) An executable bash script that runs the plan. The script must be very easy for a human to read: prioritize readability over fancy printouts or verification. Use shebang #!/usr/bin/env bash and set -e. Run each step from the plan using concrete commands (no angle brackets or placeholders in the script—bash would interpret < as a redirect). The script does not need to contain verification logic—it will be run by an agent that verifies the output. Use simple checks only where they are easy to read; if verification would be too complex to encode in bash, leave a comment describing the expected output instead. The script should be dead-simple: just straightforward bash commands, no progress counters or extra logic. Output only the script source (no markdown code fence)."""

PLAN_TEST_BASH_DELIMITER = "\n---BASH SCRIPT---\n"
PLAN_TEST_SCRIPT_PREFIX = "run-plan.sh"

DEV_TEST_LEVEL_ENV = "DEV_TEST_LEVEL"
DEV_TEST_MAX_LEVEL = 2  # Allow one nested run (level 0 and 1); level 2+ skipped

STREAM_READER_TIMEOUT_SEC = 300
PROC_WAIT_TIMEOUT_SEC = 5
CANCEL_TERMINATE_TIMEOUT_SEC = 5


def _agent_cmd() -> str:
    """Resolve agent command (SDK internal; no CLI parameter)."""
    return os.environ.get(DEV_AGENT_CMD_ENV, AGENT_CMD_DEFAULT).strip() or AGENT_CMD_DEFAULT


def extract_plan_from_stream_json(streamed_output: str) -> str:
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


def _latest_run_plan_script(task_dir: Path) -> Path | None:
    """Return path to the latest *-run-plan.sh in comms (last in index order)."""
    cdir = comms_dir(task_dir)
    if not cdir.exists():
        return None
    order = read_index(task_dir)
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


StreamLineCallback = Callable[[str], None]


def _run_agent_ask_stream_json(
    task_dir: Path,
    chat_id: str,
    prompt: str,
    stream_log_prefix: str,
    *,
    extra_argv: list[str] | None = None,
    on_stream_line: StreamLineCallback | None = None,
    on_start: Callable[[Path], None] | None = None,
    cancel_event: threading.Event | None = None,
) -> tuple[Path, str]:
    """
    Run agent in ask mode with stream-json. Write each stdout line to log; optionally call on_stream_line(line).
    Returns (stream_log_path, streamed_output). Raises AgentRunError on failure.
    """
    agent_cmd = _agent_cmd()
    extra_argv = extra_argv or []
    base_argv = [
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
    argv = base_argv + extra_argv

    buffer: list[str] = []
    buffer_lock = threading.Lock()
    read_error: list[BaseException | None] = [None]

    logs_dir = task_dir / PLAN_LOGS_DIR
    logs_dir.mkdir(exist_ok=True)
    stream_log_name = f"{stream_log_prefix}{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.log"
    stream_log_path = logs_dir / stream_log_name
    if on_start:
        on_start(stream_log_path)

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
                    if on_stream_line:
                        on_stream_line(decoded)
                    with buffer_lock:
                        buffer.append(decoded)
        except Exception as e:
            read_error[0] = e

    try:
        proc = subprocess.Popen(
            argv,
            cwd=str(task_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
    except FileNotFoundError as e:
        raise AgentRunError(f"Agent command not found: {agent_cmd}") from e

    def cancel_watcher() -> None:
        if cancel_event is None:
            return
        cancel_event.wait()
        proc.terminate()
        time.sleep(CANCEL_TERMINATE_TIMEOUT_SEC)
        if proc.poll() is None:
            proc.kill()
        try:
            proc.wait(timeout=PROC_WAIT_TIMEOUT_SEC)
        except subprocess.TimeoutExpired:
            pass

    watcher: threading.Thread | None = None
    if cancel_event is not None:
        watcher = threading.Thread(target=cancel_watcher, daemon=True)
        watcher.start()

    reader = threading.Thread(target=read_stdout, args=(proc,))
    reader.start()
    reader.join(timeout=STREAM_READER_TIMEOUT_SEC)
    if reader.is_alive():
        proc.kill()
        proc.wait()
        raise AgentRunError("Agent timed out.")

    if cancel_event is not None and cancel_event.is_set():
        try:
            proc.wait(timeout=PROC_WAIT_TIMEOUT_SEC)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        raise AgentRunError("Cancelled.")

    try:
        proc.wait(timeout=PROC_WAIT_TIMEOUT_SEC)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()

    stderr_output = ""
    if proc.stderr:
        stderr_output = proc.stderr.read()

    if read_error[0] is not None:
        raise AgentRunError(str(read_error[0])) from read_error[0]

    streamed_output = "".join(buffer)
    if proc.returncode != 0:
        msg = stderr_output if stderr_output else f"Agent exited with code {proc.returncode} (no output)."
        raise AgentRunError(msg)

    return stream_log_path, streamed_output


def _read_chat_id(task_dir: Path) -> str:
    """Read chat ID from task_dir/AGENT_CHAT_ID_FILE. Raises AgentRunError if missing or empty."""
    chat_id_path = task_dir / AGENT_CHAT_ID_FILE
    if not chat_id_path.exists():
        raise AgentRunError(f"Chat ID file not found: {chat_id_path}. Run from a task directory or use --task.")
    chat_id = chat_id_path.read_text(encoding="utf-8").strip()
    if not chat_id:
        raise AgentRunError("Chat ID file is empty.")
    return chat_id


class AgentRunError(Exception):
    """Raised when agent run fails (missing chat ID, timeout, non-zero exit, etc.)."""

    pass


class AgentTestSkipped(Exception):
    """Raised when run_test is skipped (e.g. max nesting depth). CLI should exit 0."""

    pass


@dataclass(frozen=True)
class RunPlanImplementResult:
    stream_log_path: Path
    comms_path: Path


@dataclass(frozen=True)
class RunPlanTestResult:
    stream_log_path: Path
    comms_path: Path
    script_path: Path | None = None  # Set if a run-plan script was written


@dataclass(frozen=True)
class RunImplementResult:
    stream_log_path: Path


@dataclass(frozen=True)
class RunTestResult:
    run_log_path: Path
    stream_log_path: Path
    comms_path: Path
    script_exit_code: int


def run_plan_implement(
    task_dir: Path,
    *,
    on_stream_line: StreamLineCallback | None = None,
    on_start: Callable[[Path], None] | None = None,
    cancel_event: threading.Event | None = None,
) -> RunPlanImplementResult:
    """Run agent with plan prompt; write stream to log, extract plan, write task-plan-draft.md and add comms (plan)."""
    chat_id = _read_chat_id(task_dir)
    stream_log_path, streamed_output = _run_agent_ask_stream_json(
        task_dir,
        chat_id,
        PLAN_MODE_PROMPT,
        PLAN_IMPLEMENT_STREAM_LOG_PREFIX,
        on_stream_line=on_stream_line,
        on_start=on_start,
        cancel_event=cancel_event,
    )
    plan_text = extract_plan_from_stream_json(streamed_output)
    draft_path = task_dir / TASK_PLAN_DRAFT
    draft_path.write_text(plan_text, encoding="utf-8")
    comms_path = add_comms(task_dir, "agent", plan_text, kind="plan")
    return RunPlanImplementResult(stream_log_path=stream_log_path, comms_path=comms_path)


def run_plan_test(
    task_dir: Path,
    *,
    on_stream_line: StreamLineCallback | None = None,
    on_start: Callable[[Path], None] | None = None,
) -> RunPlanTestResult:
    """Run agent with plan-test prompt; extract plan + script, add comms (plan-test), write script to comms."""
    chat_id = _read_chat_id(task_dir)
    stream_log_path, streamed_output = _run_agent_ask_stream_json(
        task_dir,
        chat_id,
        PLAN_TEST_MODE_PROMPT,
        PLAN_TEST_STREAM_LOG_PREFIX,
        on_stream_line=on_stream_line,
        on_start=on_start,
    )
    full_output = extract_plan_from_stream_json(streamed_output)
    if PLAN_TEST_BASH_DELIMITER in full_output:
        plan_text, _, script_block = full_output.partition(PLAN_TEST_BASH_DELIMITER)
        plan_text = plan_text.strip()
        script_content = script_block.strip()
    else:
        plan_text = full_output.strip()
        script_content = None

    script_filename = None
    if script_content:
        plan_seq = next_sequence(task_dir)
        script_seq = plan_seq + 1
        script_filename = f"{script_seq:03d}-{PLAN_TEST_SCRIPT_PREFIX}"
        plan_text += f"\n\n## How to run\n\nExecute: `./comms/{script_filename}` or `bash comms/{script_filename}`\n"

    comms_path = add_comms(task_dir, "agent", plan_text, kind="plan-test")

    script_path_out: Path | None = None
    if script_content and script_filename:
        script_path_out = comms_dir(task_dir) / script_filename
        script_path_out.write_text(script_content.strip() + "\n", encoding="utf-8")
        script_path_out.chmod(0o755)
        with open(index_path(task_dir), "a", encoding="utf-8") as f:
            f.write(script_filename + "\n")

    return RunPlanTestResult(
        stream_log_path=stream_log_path,
        comms_path=comms_path,
        script_path=script_path_out,
    )


def run_implement(
    task_dir: Path,
    *,
    on_stream_line: StreamLineCallback | None = None,
    on_start: Callable[[Path], None] | None = None,
    cancel_event: threading.Event | None = None,
) -> RunImplementResult:
    """Run agent with implement prompt (--force, --sandbox disabled); write stream to log only."""
    chat_id = _read_chat_id(task_dir)
    agent_cmd = _agent_cmd()
    logs_dir = task_dir / PLAN_LOGS_DIR
    logs_dir.mkdir(exist_ok=True)
    stream_log_name = f"{IMPLEMENT_STREAM_LOG_PREFIX}{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.log"
    stream_log_path = logs_dir / stream_log_name
    if on_start:
        on_start(stream_log_path)
    # Implement mode: explicitly use non-ask mode, add --force and --sandbox disabled
    argv = [
        agent_cmd,
        "agent",
        "--print",
        "--force",
        "--mode",
        "code",
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
    read_error: list[BaseException | None] = [None]

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
                    if on_stream_line:
                        on_stream_line(decoded)
                    buffer.append(decoded)
        except Exception as e:
            read_error[0] = e

    try:
        proc = subprocess.Popen(
            argv,
            cwd=str(task_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
    except FileNotFoundError as e:
        raise AgentRunError(f"Agent command not found: {agent_cmd}") from e

    def cancel_watcher() -> None:
        if cancel_event is None:
            return
        cancel_event.wait()
        proc.terminate()
        time.sleep(CANCEL_TERMINATE_TIMEOUT_SEC)
        if proc.poll() is None:
            proc.kill()
        try:
            proc.wait(timeout=PROC_WAIT_TIMEOUT_SEC)
        except subprocess.TimeoutExpired:
            pass

    watcher: threading.Thread | None = None
    if cancel_event is not None:
        watcher = threading.Thread(target=cancel_watcher, daemon=True)
        watcher.start()

    read_stdout(proc)
    proc.wait()

    if cancel_event is not None and cancel_event.is_set():
        raise AgentRunError("Cancelled.")

    stderr_output = ""
    if proc.stderr:
        stderr_output = proc.stderr.read()

    if read_error[0] is not None:
        raise AgentRunError(str(read_error[0])) from read_error[0]

    if proc.returncode != 0:
        msg = stderr_output if stderr_output else f"Agent exited with code {proc.returncode} (no output)."
        raise AgentRunError(msg)

    return RunImplementResult(stream_log_path=stream_log_path)


def run_do(
    task_dir: Path,
    prompt: str,
    *,
    on_stream_line: StreamLineCallback | None = None,
    on_start: Callable[[Path], None] | None = None,
    cancel_event: threading.Event | None = None,
) -> RunImplementResult:
    """Run agent in implement style with a custom --trust prompt; logs-only (no comms)."""
    chat_id = _read_chat_id(task_dir)
    agent_cmd = _agent_cmd()
    logs_dir = task_dir / PLAN_LOGS_DIR
    logs_dir.mkdir(exist_ok=True)
    stream_log_name = f"{DO_STREAM_LOG_PREFIX}{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.log"
    stream_log_path = logs_dir / stream_log_name
    if on_start:
        on_start(stream_log_path)
    argv = [
        agent_cmd,
        "agent",
        "--print",
        "--force",
        "--mode",
        "code",
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
        prompt,
    ]

    buffer: list[str] = []
    read_error: list[BaseException | None] = [None]

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
                    if on_stream_line:
                        on_stream_line(decoded)
                    buffer.append(decoded)
        except Exception as e:
            read_error[0] = e

    try:
        proc = subprocess.Popen(
            argv,
            cwd=str(task_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
    except FileNotFoundError as e:
        raise AgentRunError(f"Agent command not found: {agent_cmd}") from e

    def cancel_watcher() -> None:
        if cancel_event is None:
            return
        cancel_event.wait()
        proc.terminate()
        time.sleep(CANCEL_TERMINATE_TIMEOUT_SEC)
        if proc.poll() is None:
            proc.kill()
        try:
            proc.wait(timeout=PROC_WAIT_TIMEOUT_SEC)
        except subprocess.TimeoutExpired:
            pass

    watcher: threading.Thread | None = None
    if cancel_event is not None:
        watcher = threading.Thread(target=cancel_watcher, daemon=True)
        watcher.start()

    read_stdout(proc)
    proc.wait()

    if cancel_event is not None and cancel_event.is_set():
        raise AgentRunError("Cancelled.")

    stderr_output = ""
    if proc.stderr:
        stderr_output = proc.stderr.read()

    if read_error[0] is not None:
        raise AgentRunError(str(read_error[0])) from read_error[0]

    if proc.returncode != 0:
        msg = stderr_output if stderr_output else f"Agent exited with code {proc.returncode} (no output)."
        raise AgentRunError(msg)

    return RunImplementResult(stream_log_path=stream_log_path)


def run_test(
    task_dir: Path,
    *,
    on_stream_line: StreamLineCallback | None = None,
    on_script_line: StreamLineCallback | None = None,
    on_before_agent: Callable[[], None] | None = None,
    on_start: Callable[[Path], None] | None = None,
) -> RunTestResult:
    """
    Full test flow: find latest run-plan script, run it and write run log,
    run agent with test-results prompt, extract result, add comms (test-results).
    Raises AgentTestSkipped if DEV_TEST_LEVEL >= DEV_TEST_MAX_LEVEL.
    """
    try:
        current_level = int(os.environ.get(DEV_TEST_LEVEL_ENV, "0"))
    except ValueError:
        current_level = 0
    if current_level >= DEV_TEST_MAX_LEVEL:
        raise AgentTestSkipped("Nested dev test skipped (max depth reached).")

    cdir = comms_dir(task_dir)
    if not cdir.exists():
        raise AgentRunError("Comms directory not found. Run from a task directory or use --task.")
    script_path = _latest_run_plan_script(task_dir)
    if script_path is None or not script_path.exists():
        raise AgentRunError(
            "No test script found in comms (expecting *-run-plan.sh). Run dev plan-test first."
        )

    logs_dir = task_dir / PLAN_LOGS_DIR
    logs_dir.mkdir(exist_ok=True)
    run_log_name = f"{DEV_TEST_RUN_LOG_PREFIX}{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.log"
    run_log_path = logs_dir / run_log_name
    script_env = {**os.environ, DEV_TEST_LEVEL_ENV: str(current_level + 1)}

    with open(run_log_path, "w", encoding="utf-8") as log_file:
        proc = subprocess.Popen(
            [str(script_path)],
            cwd=str(task_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=script_env,
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            log_file.write(line)
            if line and not line.endswith("\n"):
                log_file.write("\n")
            log_file.flush()
            if on_script_line:
                on_script_line(line)
        proc.wait()

    script_exit_code = proc.returncode if proc.returncode is not None else -1
    run_log_rel = f"{PLAN_LOGS_DIR}/{run_log_name}"
    prompt = _test_results_prompt(run_log_rel, script_exit_code)

    # Optional: allow CLI to echo "Starting test analysis..." before agent runs
    if on_before_agent:
        on_before_agent()

    chat_id = _read_chat_id(task_dir)
    stream_log_path, streamed_output = _run_agent_ask_stream_json(
        task_dir,
        chat_id,
        prompt,
        DEV_TEST_STREAM_LOG_PREFIX,
        on_stream_line=on_stream_line,
        on_start=on_start,
    )
    content = extract_plan_from_stream_json(streamed_output)
    comms_path = add_comms(task_dir, "agent", content, kind="test-results")

    return RunTestResult(
        run_log_path=run_log_path,
        stream_log_path=stream_log_path,
        comms_path=comms_path,
        script_exit_code=script_exit_code,
    )
