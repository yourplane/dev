"""Run agent commands (plan-implement, implement) in a subprocess. Used by dev-server for async runs."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from dev_sdk.comms import add_comms

if TYPE_CHECKING:
    import subprocess

AGENT_CHAT_ID_FILE = "agent-chat-id"
PLAN_LOGS_DIR = ".logs"
TASK_PLAN_DRAFT = "task-plan-draft.md"

PLAN_MODE_PROMPT = """Read the task context in the `comms` directory (files listed in comms/index.txt, in order). Produce a more detailed description and a step-by-step plan for the task. Ask any follow-up questions you need. Output only the detailed description and plan as markdown (no preamble or meta-commentary)."""
PLAN_IMPLEMENT_STREAM_LOG_PREFIX = "dev-plan-stream-"

IMPLEMENT_MODE_PROMPT = """Read the task context in the `comms` directory (files listed in comms/index.txt, in order). Implement the task and commit when done. When done, in the git project directory (the repo subdirectory under the task root, not the task root itself): fetch from origin, merge origin/main into the current branch, then push the current branch to origin."""
IMPLEMENT_STREAM_LOG_PREFIX = "dev-implement-stream-"

SUPPORTED_COMMANDS = ("plan-implement", "implement")


def _read_chat_id(task_dir: Path) -> str:
    path = task_dir / AGENT_CHAT_ID_FILE
    if not path.exists():
        raise FileNotFoundError(f"Chat ID file not found: {path}")
    chat_id = path.read_text(encoding="utf-8").strip()
    if not chat_id:
        raise ValueError("Chat ID file is empty")
    return chat_id


def _stream_log_path(task_dir: Path, command_id: str) -> Path:
    logs_dir = task_dir / PLAN_LOGS_DIR
    logs_dir.mkdir(exist_ok=True)
    prefix = (
        PLAN_IMPLEMENT_STREAM_LOG_PREFIX
        if command_id == "plan-implement"
        else IMPLEMENT_STREAM_LOG_PREFIX
    )
    name = f"{prefix}{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.log"
    return logs_dir / name


def get_stream_log_path(task_dir: Path, command_id: str) -> Path:
    """Return path for the stream log file for this command (creates .logs dir)."""
    return _stream_log_path(task_dir, command_id)


def build_agent_argv(
    task_dir: Path,
    command_id: str,
    agent_cmd: str = "cursor",
) -> list[str]:
    """Build argv for the agent subprocess. Raises FileNotFoundError/ValueError if chat ID missing."""
    chat_id = _read_chat_id(task_dir)
    if command_id == "plan-implement":
        return [
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
            PLAN_MODE_PROMPT,
        ]
    if command_id == "implement":
        return [
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
    raise ValueError(f"Unsupported command: {command_id!r}")


def start_agent_process(
    task_dir: Path,
    command_id: str,
    agent_cmd: str = "cursor",
    env: dict[str, str] | None = None,
) -> tuple["subprocess.Popen[str]", Path]:
    """
    Start the agent subprocess for the given command. Stdout is written to a new stream log file.
    Returns (process, stream_log_path). Caller must wait on the process and may call
    post_process_plan_implement when command_id is plan-implement after process exits.
    """
    import subprocess

    argv = build_agent_argv(task_dir, command_id, agent_cmd)
    stream_log_path = _stream_log_path(task_dir, command_id)
    run_env = dict(env) if env else {}
    # Ensure no PYTHONUNBUFFERED etc. break the child
    proc_env = {**run_env}

    log_file = open(stream_log_path, "w", encoding="utf-8")
    try:
        proc = subprocess.Popen(
            argv,
            cwd=str(task_dir),
            stdout=log_file,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=proc_env,
        )
    except Exception:
        log_file.close()
        raise
    # Don't close log_file; process will write to it. When process exits, reaper can close or leave to GC.
    return proc, stream_log_path


def extract_plan_from_stream_json(streamed_output: str) -> str:
    """Extract plan markdown from streamed JSON (Cursor agent stream-json format)."""
    lines = [line.strip() for line in streamed_output.splitlines() if line.strip()]
    if not lines:
        return streamed_output
    for line in reversed(lines):
        try:
            obj = json.loads(line)
            if isinstance(obj, dict) and obj.get("type") == "result" and "result" in obj:
                result = obj["result"]
                if isinstance(result, str) and result.strip():
                    return result.strip()
        except json.JSONDecodeError:
            pass
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


def post_process_plan_implement(task_dir: Path, stream_log_path: Path) -> Path:
    """
    After plan-implement process has exited: read stream log, extract plan,
    write task-plan-draft.md and add plan to comms. Returns path to the comms file.
    """
    content = stream_log_path.read_text(encoding="utf-8")
    plan_text = extract_plan_from_stream_json(content)
    draft_path = task_dir / TASK_PLAN_DRAFT
    draft_path.write_text(plan_text, encoding="utf-8")
    return add_comms(task_dir, "agent", plan_text, kind="plan")
