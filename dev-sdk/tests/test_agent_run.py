"""Tests for agent_run module."""

import pytest

from dev_sdk.agent_run import (
    AgentRunError,
    _remove_empty_log_file,
    extract_plan_from_stream_json,
)


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


def test_read_chat_id_raises_when_missing(tmp_path) -> None:
    """AgentRunError when agent-chat-id file is missing."""
    from dev_sdk.agent_run import _read_chat_id

    with pytest.raises(AgentRunError) as exc_info:
        _read_chat_id(tmp_path)
    assert "not found" in str(exc_info.value).lower() or "chat" in str(exc_info.value).lower()


def test_remove_empty_log_file_deletes_zero_byte_file(tmp_path) -> None:
    """Empty stream log files are removed."""
    log_path = tmp_path / "empty.log"
    log_path.write_text("")
    _remove_empty_log_file(log_path)
    assert not log_path.exists()


def test_remove_empty_log_file_keeps_nonempty_file(tmp_path) -> None:
    """Non-empty stream logs are kept."""
    log_path = tmp_path / "non-empty.log"
    log_path.write_text("line\n")
    _remove_empty_log_file(log_path)
    assert log_path.exists()
