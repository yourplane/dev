"""Tests for agent_run module."""

import pytest

from dev_sdk.agent_run import (
    AgentRunError,
    extract_plan_from_stream_json,
    _latest_run_plan_script,
    _test_results_prompt,
)
from dev_sdk.comms import add_comms, comms_dir, read_index


def test_extract_plan_from_stream_json_prefers_result_type() -> None:
    """Final 'result' event with result field is preferred."""
    lines = [
        '{"type": "assistant", "message": {"content": [{"type": "text", "text": "Partial"}]}}',
        '{"type": "result", "result": "# Full Plan\\n\\nStep 1.\\nStep 2."}',
    ]
    out = extract_plan_from_stream_json("\n".join(lines))
    assert out == "# Full Plan\n\nStep 1.\nStep 2."


def test_extract_plan_from_stream_json_fallback_content() -> None:
    """Falls back to content/text/delta when no result event."""
    lines = [
        '{"content": "# Plan A"}',
        '{"text": " Plan B"}',
    ]
    out = extract_plan_from_stream_json("\n".join(lines))
    assert "# Plan A" in out and "Plan B" in out


def test_extract_plan_from_stream_json_empty_returns_original() -> None:
    """Empty or only whitespace returns original string."""
    raw = "  \n  "
    assert extract_plan_from_stream_json(raw) == raw


def test_latest_run_plan_script_returns_last_in_index(tmp_path) -> None:
    """Latest *-run-plan.sh is the last in index order."""
    cdir = tmp_path / "comms"
    cdir.mkdir()
    (cdir / "001-user.md").write_text("x")
    (cdir / "002-run-plan.sh").write_text("echo two")
    (cdir / "003-run-plan.sh").write_text("echo three")
    (cdir / "index.txt").write_text("001-user.md\n002-run-plan.sh\n003-run-plan.sh\n")
    path = _latest_run_plan_script(tmp_path)
    assert path is not None
    assert path.name == "003-run-plan.sh"


def test_latest_run_plan_script_none_when_no_script(tmp_path) -> None:
    """Returns None when no *-run-plan.sh in index."""
    cdir = tmp_path / "comms"
    cdir.mkdir()
    (cdir / "index.txt").write_text("001-user.md\n")
    assert _latest_run_plan_script(tmp_path) is None


def test_test_results_prompt_includes_exit_code() -> None:
    """Non-zero script exit code is mentioned in prompt."""
    prompt = _test_results_prompt(".logs/run.log", 1)
    assert "exit" in prompt.lower() and "1" in prompt


def test_test_results_prompt_zero_exit() -> None:
    """Zero exit code prompt has no exit note."""
    prompt = _test_results_prompt(".logs/run.log", 0)
    assert "exit" not in prompt.lower() or "code 0" not in prompt


def test_read_chat_id_raises_when_missing(tmp_path) -> None:
    """AgentRunError when agent-chat-id file is missing."""
    from dev_sdk.agent_run import _read_chat_id

    with pytest.raises(AgentRunError) as exc_info:
        _read_chat_id(tmp_path)
    assert "not found" in str(exc_info.value).lower() or "chat" in str(exc_info.value).lower()
