"""Prompts and constants for agent flows."""

AGENT_CHAT_ID_FILE = "agent-chat-id"
TASK_PLAN_DRAFT = "task-plan-draft.md"
PLAN_LOGS_DIR = ".logs"

PLAN_MODE_PROMPT = """Read the task context in the `comms` directory (files listed in comms/index.txt, in order). Produce a more detailed description and a step-by-step plan for the task. Ask any follow-up questions you need. Output only the detailed description and plan as markdown (no preamble or meta-commentary)."""
PLAN_IMPLEMENT_STREAM_LOG_PREFIX = "dev-plan-stream-"

IMPLEMENT_MODE_PROMPT = """Read the task context in the `comms` directory (files listed in comms/index.txt, in order). Implement the task and commit when done. When done, in the git project directory (the repo subdirectory under the task root, not the task root itself): fetch from origin, merge origin/main into the current branch, then push the current branch to origin."""
IMPLEMENT_STREAM_LOG_PREFIX = "dev-implement-stream-"

PLAN_TEST_MODE_PROMPT = """Read the task context in the `comms` directory (files listed in comms/index.txt, in order). Produce two artifacts in this exact order, with no other text before or after:

1) A manual, end-to-end testing plan in markdown. It must validate the entire task—all work and behavior described in the task context from the beginning, not just the most recent changes. Include feature testing (steps to verify the task's goals) and regression testing (steps to verify existing behavior is unchanged). Do not run or reference unit tests (e.g. pytest): unit tests are run separately and do not count as end-to-end regression testing. The plan is Unix-only; Windows is out of scope. Every command in the plan must use the task's virtual environment: from the task root use .venv/<task_name>/bin/<command> (or activate the venv first). This is not unit or automated test code; it is a step-by-step manual test plan. Output only the plan as markdown.

2) On a new line, the exact delimiter line: ---BASH SCRIPT---

3) An executable bash script that runs the plan. The script must be very easy for a human to read: prioritize readability over fancy printouts or verification. Use shebang #!/usr/bin/env bash and set -e. Run each step from the plan using the actual venv path for CLI invocations. The script must never contain angle brackets or placeholders (e.g. do not write .venv/<task_name>/bin/<command> in the script—bash would interpret < as a redirect). Use the literal path with the real task name and command, e.g. .venv/bash-dev-plan-test/bin/dev. The script does not need to contain verification logic—it will be run by an agent that verifies the output. Use simple checks only where they are easy to read; if verification would be too complex to encode in bash, leave a comment describing the expected output instead. The script should be dead-simple: just straightforward bash commands, no progress counters or extra logic. Output only the script source (no markdown code fence)."""

PLAN_TEST_BASH_DELIMITER = "\n---BASH SCRIPT---\n"
PLAN_TEST_SCRIPT_PREFIX = "run-plan.sh"
PLAN_TEST_STREAM_LOG_PREFIX = "dev-plan-test-stream-"

DEV_TEST_RUN_LOG_PREFIX = "dev-test-run-"
DEV_TEST_STREAM_LOG_PREFIX = "dev-test-stream-"
DEV_TEST_LEVEL_ENV = "DEV_TEST_LEVEL"
DEV_TEST_MAX_LEVEL = 2  # Allow one nested run (level 0 and 1); level 2+ skipped


def test_results_prompt(run_log_rel: str, script_exit_code: int | None) -> str:
    """Build prompt for test-results agent; run_log_rel is path relative to task root."""
    exit_note = ""
    if script_exit_code is not None and script_exit_code != 0:
        exit_note = f" The test script exited with code {script_exit_code}.\n\n"
    return f"""Read the test run output from the file at {run_log_rel} (relative to the task workspace).{exit_note}Analyze the results: explain what passed or failed and why. Propose any fixes needed. Output only a single markdown document (no preamble or meta-commentary)."""
