"""Agent execution: run in ask mode with stream-json, capture and optional line callback."""

from __future__ import annotations

import subprocess
import threading
from pathlib import Path
from typing import Callable

from dev_sdk.exceptions import (
    AgentNotFoundError,
    AgentRunError,
    AgentTimeoutError,
    ChatIdNotFoundError,
)
from dev_sdk.prompts import AGENT_CHAT_ID_FILE
from dev_sdk.stream_json import format_stream_line_for_console

LineCallback = Callable[[str, bool], None]  # (formatted_text, is_thinking)


def read_chat_id(task_dir: Path) -> str:
    """Read chat ID from task directory. Raises ChatIdNotFoundError if missing or empty."""
    chat_id_path = task_dir / AGENT_CHAT_ID_FILE
    if not chat_id_path.exists():
        raise ChatIdNotFoundError(f"Chat ID file not found: {chat_id_path}")
    chat_id = chat_id_path.read_text(encoding="utf-8").strip()
    if not chat_id:
        raise ChatIdNotFoundError("Chat ID file is empty.")
    return chat_id


def run_agent_ask_stream_json(
    task_dir: Path,
    agent_cmd: str,
    prompt: str,
    stream_log_path: Path,
    *,
    timeout: int = 300,
    on_line: LineCallback | None = None,
) -> str:
    """
    Run agent in ask mode with stream-json. Writes raw output to stream_log_path.
    Returns full streamed output. Calls on_line(formatted_text, is_thinking) for each parsed line if provided.
    Raises: ChatIdNotFoundError, AgentNotFoundError, AgentTimeoutError, AgentRunError.
    """
    chat_id = read_chat_id(task_dir)
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

    def read_stdout(proc: subprocess.Popen[str]) -> None:
        try:
            assert proc.stdout is not None
            stream_log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(stream_log_path, "w", encoding="utf-8") as log:
                for line in proc.stdout:
                    decoded = line if isinstance(line, str) else line.decode("utf-8", errors="replace")
                    log.write(decoded)
                    if decoded and not decoded.endswith("\n"):
                        log.write("\n")
                    log.flush()
                    formatted, is_thinking = format_stream_line_for_console(decoded.strip())
                    if formatted is not None and on_line:
                        on_line(formatted, is_thinking)
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
    except FileNotFoundError:
        raise AgentNotFoundError(f"Agent command not found: {agent_cmd}")

    reader = threading.Thread(target=read_stdout, args=(proc,))
    reader.start()
    reader.join(timeout=timeout)
    if reader.is_alive():
        proc.kill()
        proc.wait()
        raise AgentTimeoutError("Agent timed out.")

    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()

    stderr_output = ""
    if proc.stderr:
        stderr_output = proc.stderr.read()

    if read_error[0] is not None:
        raise AgentRunError(
            str(read_error[0]),
            returncode=proc.returncode or -1,
            stderr=stderr_output,
            streamed_output="".join(buffer),
        )

    streamed_output = "".join(buffer)
    if proc.returncode != 0:
        msg = "Agent exited with non-zero code."
        if not streamed_output.strip() and not stderr_output:
            msg += " The agent may not support --output-format stream-json."
        raise AgentRunError(msg, returncode=proc.returncode or -1, stderr=stderr_output, streamed_output=streamed_output)

    return streamed_output


def run_agent_implement_stream_json(
    task_dir: Path,
    agent_cmd: str,
    prompt: str,
    stream_log_path: Path,
    *,
    timeout: int = 300,
    on_line: LineCallback | None = None,
) -> None:
    """
    Run agent in implement mode (no --mode ask; uses --force --sandbox disabled).
    Streams to log and optional on_line. Raises on failure; returns None on success.
    """
    chat_id = read_chat_id(task_dir)
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
    buffer_lock = threading.Lock()
    read_error: list[BaseException | None] = [None]

    def read_stdout(proc: subprocess.Popen[str]) -> None:
        try:
            assert proc.stdout is not None
            stream_log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(stream_log_path, "w", encoding="utf-8") as log:
                for line in proc.stdout:
                    decoded = line if isinstance(line, str) else line.decode("utf-8", errors="replace")
                    log.write(decoded)
                    if decoded and not decoded.endswith("\n"):
                        log.write("\n")
                    log.flush()
                    formatted, is_thinking = format_stream_line_for_console(decoded.strip())
                    if formatted is not None and on_line:
                        on_line(formatted, is_thinking)
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
    except FileNotFoundError:
        raise AgentNotFoundError(f"Agent command not found: {agent_cmd}")

    reader = threading.Thread(target=read_stdout, args=(proc,))
    reader.start()
    reader.join(timeout=timeout)
    if reader.is_alive():
        proc.kill()
        proc.wait()
        raise AgentTimeoutError("Agent implement mode timed out.")

    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()

    stderr_output = ""
    if proc.stderr:
        stderr_output = proc.stderr.read()

    if read_error[0] is not None:
        raise AgentRunError(
            str(read_error[0]),
            returncode=proc.returncode or -1,
            stderr=stderr_output,
            streamed_output="".join(buffer),
        )

    if proc.returncode != 0:
        streamed_output = "".join(buffer)
        msg = "Agent exited with non-zero code."
        if not streamed_output.strip() and not stderr_output:
            msg += " The agent may not support --output-format stream-json."
        raise AgentRunError(msg, returncode=proc.returncode or -1, stderr=stderr_output, streamed_output=streamed_output)
