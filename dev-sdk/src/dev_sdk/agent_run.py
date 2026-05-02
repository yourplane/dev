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

from dev_sdk.comms import add_comms

# Agent command: constant or from env (SDK chooses; no parameter from CLI).
AGENT_CMD_DEFAULT = "cursor"
DEV_AGENT_CMD_ENV = "DEV_AGENT_CMD"

AGENT_CHAT_ID_FILE = "agent-chat-id"
PLAN_LOGS_DIR = ".logs"
TASK_PLAN_DRAFT = "task-plan-draft.md"

PLAN_IMPLEMENT_STREAM_LOG_PREFIX = "dev-plan-stream-"
IMPLEMENT_STREAM_LOG_PREFIX = "dev-implement-stream-"
DO_STREAM_LOG_PREFIX = "dev-do-stream-"

_PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


def _load_agent_prompt(name: str) -> str:
    """Load prompt text from dev_sdk/prompts (UTF-8)."""
    path = _PROMPTS_DIR / name
    return path.read_text(encoding="utf-8").strip()


PLAN_MODE_PROMPT = _load_agent_prompt("plan_mode.md")
IMPLEMENT_MODE_PROMPT = _load_agent_prompt("implement_mode.md")

STREAM_READER_TIMEOUT_SEC = 300
PROC_WAIT_TIMEOUT_SEC = 5
CANCEL_TERMINATE_TIMEOUT_SEC = 5


def _remove_empty_log_file(path: Path) -> None:
    """Delete the stream log when it is empty."""
    try:
        if path.exists() and path.stat().st_size == 0:
            path.unlink()
    except OSError:
        # Best-effort cleanup only.
        pass


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


StreamLineCallback = Callable[[str], None]


def _run_agent_ask_stream_json(
    task_dir: Path,
    prompt: str,
    stream_log_prefix: str,
    *,
    chat_id: str | None = None,
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
        "--workspace",
        str(task_dir),
        "--trust",
        prompt,
    ]
    if chat_id:
        base_argv[10:10] = ["--resume", chat_id]
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
    _remove_empty_log_file(stream_log_path)

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


@dataclass(frozen=True)
class RunPlanImplementResult:
    stream_log_path: Path
    comms_path: Path


@dataclass(frozen=True)
class RunImplementResult:
    stream_log_path: Path


def run_plan_implement(
    task_dir: Path,
    *,
    on_stream_line: StreamLineCallback | None = None,
    on_start: Callable[[Path], None] | None = None,
    cancel_event: threading.Event | None = None,
) -> RunPlanImplementResult:
    """Run agent with plan-mode prompt; write stream to log, extract plan, write task-plan-draft.md and add comms (plan)."""
    stream_log_path, streamed_output = _run_agent_ask_stream_json(
        task_dir,
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

    _remove_empty_log_file(stream_log_path)

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

    _remove_empty_log_file(stream_log_path)

    if proc.returncode != 0:
        msg = stderr_output if stderr_output else f"Agent exited with code {proc.returncode} (no output)."
        raise AgentRunError(msg)

    return RunImplementResult(stream_log_path=stream_log_path)
