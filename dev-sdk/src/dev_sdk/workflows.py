"""Workflow logic: plan-implement, plan-test, implement, test."""

from __future__ import annotations

import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from dev_sdk.agent import run_agent_ask_stream_json, run_agent_implement_stream_json, read_chat_id
from dev_sdk.comms import add_comms, comms_dir, index_path, next_sequence, read_index
from dev_sdk.prompts import (
    DEV_TEST_LEVEL_ENV,
    DEV_TEST_MAX_LEVEL,
    DEV_TEST_RUN_LOG_PREFIX,
    DEV_TEST_STREAM_LOG_PREFIX,
    IMPLEMENT_MODE_PROMPT,
    PLAN_LOGS_DIR,
    PLAN_MODE_PROMPT,
    PLAN_TEST_BASH_DELIMITER,
    PLAN_TEST_SCRIPT_PREFIX,
    PLAN_TEST_STREAM_LOG_PREFIX,
    TASK_PLAN_DRAFT,
    PLAN_TEST_MODE_PROMPT,
    test_results_prompt,
)
from dev_sdk.stream_json import extract_plan_from_stream_json

LineCallback = Callable[[str, bool], None]


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


def _stream_log_path(task_dir: Path, prefix: str) -> Path:
    """Build stream log path under task_dir/.logs."""
    logs_dir = task_dir / PLAN_LOGS_DIR
    logs_dir.mkdir(exist_ok=True)
    name = f"{prefix}{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.log"
    return logs_dir / name


def run_plan_implement(
    task_dir: Path,
    agent_cmd: str,
    stream_log_path: Path,
    *,
    on_line: LineCallback | None = None,
) -> tuple[Path, Path]:
    """
    Run agent in plan mode; write draft to task-plan-draft.md and add plan to comms.
    Returns (draft_path, comms_path).
    """
    streamed = run_agent_ask_stream_json(
        task_dir, agent_cmd, PLAN_MODE_PROMPT, stream_log_path, on_line=on_line
    )
    plan_text = extract_plan_from_stream_json(streamed)
    draft_path = task_dir / TASK_PLAN_DRAFT
    draft_path.write_text(plan_text, encoding="utf-8")
    comms_path = add_comms(task_dir, "agent", plan_text, kind="plan")
    return draft_path, comms_path


def run_plan_test(
    task_dir: Path,
    agent_cmd: str,
    stream_log_path: Path,
    *,
    on_line: LineCallback | None = None,
) -> tuple[Path, Path | None]:
    """
    Run agent to generate E2E test plan and optional bash script; write to comms.
    Returns (plan_comms_path, script_path or None).
    """
    streamed = run_agent_ask_stream_json(
        task_dir, agent_cmd, PLAN_TEST_MODE_PROMPT, stream_log_path, on_line=on_line
    )
    full_output = extract_plan_from_stream_json(streamed)
    if PLAN_TEST_BASH_DELIMITER in full_output:
        plan_text, _, script_block = full_output.partition(PLAN_TEST_BASH_DELIMITER)
        plan_text = plan_text.strip()
        script_content = script_block.strip()
    else:
        plan_text = full_output.strip()
        script_content = None

    script_path = None
    if script_content:
        plan_seq = next_sequence(task_dir)
        script_seq = plan_seq + 1
        script_filename = f"{script_seq:03d}-{PLAN_TEST_SCRIPT_PREFIX}"
        plan_text += f"\n\n## How to run\n\nExecute: `./comms/{script_filename}` or `bash comms/{script_filename}`\n"
        comms_path = add_comms(task_dir, "agent", plan_text, kind="plan-test")
        script_path = comms_dir(task_dir) / script_filename
        script_path.write_text(script_content.strip() + "\n", encoding="utf-8")
        script_path.chmod(0o755)
        with open(index_path(task_dir), "a", encoding="utf-8") as f:
            f.write(script_filename + "\n")
    else:
        comms_path = add_comms(task_dir, "agent", plan_text, kind="plan-test")

    return comms_path, script_path


def run_implement(
    task_dir: Path,
    agent_cmd: str,
    stream_log_path: Path,
    *,
    on_line: LineCallback | None = None,
) -> None:
    """Run agent in implement mode. Raises on failure."""
    run_agent_implement_stream_json(
        task_dir, agent_cmd, IMPLEMENT_MODE_PROMPT, stream_log_path, on_line=on_line
    )


def run_test(
    task_dir: Path,
    agent_cmd: str,
    *,
    on_line: LineCallback | None = None,
    on_script_line: Callable[[str], None] | None = None,
) -> Path | None:
    """
    Run latest comms test script, then run agent to analyze and add test-results to comms.
    Returns comms_path of test-results, or None if skipped (e.g. max depth).
    """
    try:
        current_level = int(os.environ.get(DEV_TEST_LEVEL_ENV, "0"))
    except ValueError:
        current_level = 0
    if current_level >= DEV_TEST_MAX_LEVEL:
        return None  # Skipped

    cdir = comms_dir(task_dir)
    if not cdir.exists():
        raise FileNotFoundError("Comms directory not found.")
    script_path = _latest_run_plan_script(task_dir)
    if script_path is None or not script_path.exists():
        raise FileNotFoundError("No test script found in comms (expecting *-run-plan.sh). Run dev plan-test first.")

    logs_dir = task_dir / PLAN_LOGS_DIR
    logs_dir.mkdir(exist_ok=True)
    run_log_name = f"{DEV_TEST_RUN_LOG_PREFIX}{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.log"
    run_log_path = logs_dir / run_log_name
    run_output_parts: list[str] = []
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
            run_output_parts.append(line)
            if on_script_line:
                on_script_line(line)
        proc.wait()

    run_log_rel = f"{PLAN_LOGS_DIR}/{run_log_name}"
    prompt = test_results_prompt(run_log_rel, proc.returncode)
    stream_log_path = _stream_log_path(task_dir, DEV_TEST_STREAM_LOG_PREFIX)
    streamed = run_agent_ask_stream_json(
        task_dir, agent_cmd, prompt, stream_log_path, on_line=on_line
    )
    content = extract_plan_from_stream_json(streamed)
    comms_path = add_comms(task_dir, "agent", content, kind="test-results")
    return comms_path
