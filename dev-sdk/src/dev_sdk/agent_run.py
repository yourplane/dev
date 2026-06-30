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
from dev_sdk.question_schema import format_question_payload_json, parse_question_output
from dev_sdk.task_manager import TaskManager

# Agent command: constant or from env (SDK chooses; no parameter from CLI).
AGENT_CMD_DEFAULT = "cursor"
DEV_AGENT_CMD_ENV = "DEV_AGENT_CMD"

AGENT_CHAT_ID_FILE = "agent-chat-id"
PLAN_LOGS_DIR = ".logs"

PLAN_IMPLEMENT_STREAM_LOG_PREFIX = "dev-plan-stream-"
QUESTION_STREAM_LOG_PREFIX = "dev-question-stream-"
IMPLEMENT_STREAM_LOG_PREFIX = "dev-implement-stream-"
DO_STREAM_LOG_PREFIX = "dev-do-stream-"
MERGE_FROM_MAIN_STREAM_LOG_PREFIX = "dev-merge-from-main-stream-"

_PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


def _load_agent_prompt(name: str) -> str:
    """Load prompt text from dev_sdk/prompts (UTF-8)."""
    path = _PROMPTS_DIR / name
    return path.read_text(encoding="utf-8").strip()


PLAN_MODE_PROMPT = _load_agent_prompt("plan_mode.md")
QUESTION_MODE_PROMPT = _load_agent_prompt("question_mode.md")
IMPLEMENT_MODE_PROMPT = _load_agent_prompt("implement_mode.md")
MERGE_CONFLICT_MODE_PROMPT = _load_agent_prompt("merge_conflict_mode.md")

QUESTION_MODE_MAX_ATTEMPTS = 3

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


def _dedupe_adjacent_text_parts(parts: list[str]) -> str:
    """Join text parts; skip consecutive duplicates (stream-json quirk)."""
    out: list[str] = []
    for p in parts:
        if out and out[-1] == p:
            continue
        out.append(p)
    return "".join(out)


def _assistant_line_text(obj: dict) -> str | None:
    """User-visible assistant text from one stream-json object, or None."""
    if obj.get("type") != "assistant":
        return None
    message = obj.get("message")
    if not isinstance(message, dict):
        return None
    content = message.get("content")
    if not isinstance(content, list):
        return None
    raw: list[str] = []
    for item in content:
        if isinstance(item, dict) and item.get("type") == "text":
            text = item.get("text")
            if isinstance(text, str):
                raw.append(text)
    if not raw:
        return None
    return _dedupe_adjacent_text_parts(raw)


def _merge_assistant_cumulative(acc: str, chunk: str) -> str:
    """
    Merge a new assistant chunk into accumulated text.

    Stream-json often sends cumulative full text per line; concatenating would
    duplicate output (see dev-frontend logParser.ts assistant branch).
    """
    if not chunk:
        return acc
    if acc == chunk:
        return acc
    if chunk.startswith(acc):
        return chunk
    if acc.startswith(chunk):
        return acc
    return acc + chunk


def extract_last_assistant_section_from_stream_json(streamed_output: str) -> str:
    """Extract the last assistant section from Cursor agent stream-json output (any mode)."""
    lines = [line.strip() for line in streamed_output.splitlines() if line.strip()]
    if not lines:
        return streamed_output

    # Build ordered section strings: each model_call_id turn, then optional
    # trailing orphan-only section. Within a section, merge cumulative deltas.
    completed: list[str] = []
    open_id: str | None = None
    open_text = ""
    orphan_acc = ""

    def finalize_open() -> None:
        nonlocal open_id, open_text
        if open_id is not None:
            s = open_text.strip()
            if s:
                completed.append(s)
            open_id = None
            open_text = ""

    for line in lines:
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        t = _assistant_line_text(obj)
        if t is None:
            continue
        mid = obj.get("model_call_id")
        if not isinstance(mid, str) or not mid:
            orphan_acc = _merge_assistant_cumulative(orphan_acc, t)
            continue

        if open_id is None:
            open_id = mid
            open_text = _merge_assistant_cumulative(_merge_assistant_cumulative("", orphan_acc), t)
            orphan_acc = ""
        elif mid == open_id:
            merged = _merge_assistant_cumulative(open_text, orphan_acc)
            open_text = _merge_assistant_cumulative(merged, t)
            orphan_acc = ""
        else:
            finalize_open()
            open_id = mid
            open_text = _merge_assistant_cumulative(_merge_assistant_cumulative("", orphan_acc), t)
            orphan_acc = ""

    finalize_open()
    if orphan_acc.strip():
        completed.append(orphan_acc.strip())

    for s in reversed(completed):
        if s:
            return s
    return ""


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


def _create_ephemeral_chat() -> str:
    """Create a new agent chat (not persisted to agent-chat-id)."""
    return TaskManager(Path("."))._create_agent_chat()


def _question_retry_prompt(errors: list[str]) -> str:
    """Follow-up prompt after a failed question JSON parse."""
    bullet_list = "\n".join(f"- {e}" for e in errors)
    return (
        "Your previous output could not be parsed as valid question JSON. "
        "Fix the issues below and respond with ONLY a ```json fenced block "
        "containing the corrected schema (no other text).\n\n"
        f"Validation errors:\n{bullet_list}"
    )


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
class RunQuestionResult:
    stream_log_path: Path
    comms_path: Path


@dataclass(frozen=True)
class RunImplementResult:
    stream_log_path: Path
    comms_path: Path | None = None


def run_plan_implement(
    task_dir: Path,
    *,
    on_stream_line: StreamLineCallback | None = None,
    on_start: Callable[[Path], None] | None = None,
    cancel_event: threading.Event | None = None,
) -> RunPlanImplementResult:
    """Run agent with plan-mode prompt; write stream to log, extract plan, add comms (plan)."""
    stream_log_path, streamed_output = _run_agent_ask_stream_json(
        task_dir,
        PLAN_MODE_PROMPT,
        PLAN_IMPLEMENT_STREAM_LOG_PREFIX,
        on_stream_line=on_stream_line,
        on_start=on_start,
        cancel_event=cancel_event,
    )
    plan_text = extract_last_assistant_section_from_stream_json(streamed_output)
    comms_path = add_comms(task_dir, "agent", plan_text, kind="plan")
    return RunPlanImplementResult(stream_log_path=stream_log_path, comms_path=comms_path)


def run_question_mode(
    task_dir: Path,
    *,
    on_stream_line: StreamLineCallback | None = None,
    on_start: Callable[[Path], None] | None = None,
    cancel_event: threading.Event | None = None,
) -> RunQuestionResult:
    """Run agent with question-mode prompt; parse JSON with retries; write comms when complete."""
    chat_id = _create_ephemeral_chat()
    last_stream_log_path: Path | None = None
    last_output = ""
    parsed_payload = None
    parse_errors: list[str] = []

    for attempt in range(QUESTION_MODE_MAX_ATTEMPTS):
        if cancel_event is not None and cancel_event.is_set():
            raise AgentRunError("Cancelled.")
        prompt = QUESTION_MODE_PROMPT if attempt == 0 else _question_retry_prompt(parse_errors)
        stream_log_path, streamed_output = _run_agent_ask_stream_json(
            task_dir,
            prompt,
            QUESTION_STREAM_LOG_PREFIX,
            chat_id=chat_id,
            on_stream_line=on_stream_line,
            on_start=on_start,
            cancel_event=cancel_event,
        )
        last_stream_log_path = stream_log_path
        last_output = extract_last_assistant_section_from_stream_json(streamed_output)
        parsed_payload, parse_errors = parse_question_output(last_output)
        if parsed_payload is not None:
            break

    if last_stream_log_path is None:
        raise AgentRunError("Question mode produced no output.")

    if parsed_payload is not None:
        comms_content = format_question_payload_json(parsed_payload)
    else:
        comms_content = last_output

    comms_path = add_comms(task_dir, "agent", comms_content, kind="question")
    return RunQuestionResult(stream_log_path=last_stream_log_path, comms_path=comms_path)


def run_implement(
    task_dir: Path,
    *,
    on_stream_line: StreamLineCallback | None = None,
    on_start: Callable[[Path], None] | None = None,
    cancel_event: threading.Event | None = None,
) -> RunImplementResult:
    """Run agent with implement prompt (--force, --sandbox disabled); log stream; add comms from last assistant section."""
    return _run_agent_trust_stream_json(
        task_dir,
        IMPLEMENT_MODE_PROMPT,
        IMPLEMENT_STREAM_LOG_PREFIX,
        comms_kind="implement",
        on_stream_line=on_stream_line,
        on_start=on_start,
        cancel_event=cancel_event,
    )


def _run_agent_trust_stream_json(
    task_dir: Path,
    prompt: str,
    stream_log_prefix: str,
    *,
    comms_kind: str | None = None,
    on_stream_line: StreamLineCallback | None = None,
    on_start: Callable[[Path], None] | None = None,
    cancel_event: threading.Event | None = None,
) -> RunImplementResult:
    """Run agent with --force, --sandbox disabled, --resume; optional comms from last assistant section."""
    chat_id = _read_chat_id(task_dir)
    agent_cmd = _agent_cmd()
    logs_dir = task_dir / PLAN_LOGS_DIR
    logs_dir.mkdir(exist_ok=True)
    stream_log_name = f"{stream_log_prefix}{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.log"
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

    if cancel_event is not None:
        threading.Thread(target=cancel_watcher, daemon=True).start()

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

    comms_path: Path | None = None
    if comms_kind is not None:
        streamed_output = "".join(buffer)
        summary_text = extract_last_assistant_section_from_stream_json(streamed_output)
        comms_path = add_comms(task_dir, "agent", summary_text, kind=comms_kind)
    return RunImplementResult(stream_log_path=stream_log_path, comms_path=comms_path)


def run_do(
    task_dir: Path,
    prompt: str,
    *,
    on_stream_line: StreamLineCallback | None = None,
    on_start: Callable[[Path], None] | None = None,
    cancel_event: threading.Event | None = None,
) -> RunImplementResult:
    """Run agent in implement style with a custom --trust prompt; logs-only (no comms)."""
    return _run_agent_trust_stream_json(
        task_dir,
        prompt,
        DO_STREAM_LOG_PREFIX,
        on_stream_line=on_stream_line,
        on_start=on_start,
        cancel_event=cancel_event,
    )


def run_merge_conflict_resolution(
    task_dir: Path,
    *,
    on_stream_line: StreamLineCallback | None = None,
    on_start: Callable[[Path], None] | None = None,
    cancel_event: threading.Event | None = None,
) -> RunImplementResult:
    """Run agent to resolve merge conflicts; log stream; add comms from last assistant section."""
    return _run_agent_trust_stream_json(
        task_dir,
        MERGE_CONFLICT_MODE_PROMPT,
        MERGE_FROM_MAIN_STREAM_LOG_PREFIX,
        comms_kind="merge-from-main",
        on_stream_line=on_stream_line,
        on_start=on_start,
        cancel_event=cancel_event,
    )
