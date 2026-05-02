"""Tests for agent_run module."""

import pytest

from dev_sdk.agent_run import (
    AgentRunError,
    _remove_empty_log_file,
    extract_last_assistant_section_from_stream_json,
)


def test_extract_last_assistant_section_dedupes_cumulative_assistant_deltas() -> None:
    """Cumulative assistant lines for one model_call_id must not concatenate duplicate text."""
    lines = [
        '{"type": "assistant", "message": {"content": [{"type": "text", "text": "He"}]}, "model_call_id": "1"}',
        '{"type": "assistant", "message": {"content": [{"type": "text", "text": "Hello"}]}, "model_call_id": "1"}',
    ]
    out = extract_last_assistant_section_from_stream_json("\n".join(lines))
    assert out == "Hello"


def test_extract_last_assistant_section_dedupes_adjacent_duplicate_content_blocks() -> None:
    """Same text twice in one message content list is not doubled."""
    line = (
        '{"type": "assistant", "message": {"content": ['
        '{"type": "text", "text": "x"}, {"type": "text", "text": "x"}'
        ']}, "model_call_id": "1"}'
    )
    assert extract_last_assistant_section_from_stream_json(line) == "x"


def test_extract_last_assistant_section_returns_last_model_section() -> None:
    """Only the final assistant model section is returned."""
    lines = [
        '{"type": "assistant", "message": {"content": [{"type": "text", "text": "Old section"}]}, "model_call_id": "call-1"}',
        '{"type": "assistant", "message": {"content": [{"type": "text", "text": "Latest"}]}, "model_call_id": "call-2"}',
        '{"type": "result", "result": "ignored"}',
    ]
    out = extract_last_assistant_section_from_stream_json("\n".join(lines))
    assert out == "Latest"


def test_extract_last_assistant_section_orphan_chunks_attach_to_next_model_call() -> None:
    """Assistant chunks without model_call_id are grouped with the next model call."""
    lines = [
        '{"type": "assistant", "message": {"content": [{"type": "text", "text": "prefix "}]} }',
        '{"type": "assistant", "message": {"content": [{"type": "text", "text": "body"}]}, "model_call_id": "call-2"}',
    ]
    out = extract_last_assistant_section_from_stream_json("\n".join(lines))
    assert out == "prefix body"


def test_extract_last_assistant_section_ignores_non_assistant_text_fields() -> None:
    """Non-assistant objects with generic text fields are ignored."""
    lines = [
        '{"content": "not assistant"}',
        '{"type": "tool_call", "text": "still not assistant"}',
        '{"type": "assistant", "message": {"content": [{"type": "text", "text": "Plan"}]}, "model_call_id": "call-3"}',
    ]
    out = extract_last_assistant_section_from_stream_json("\n".join(lines))
    assert out == "Plan"


def test_extract_last_assistant_section_returns_empty_without_assistant_text() -> None:
    """No assistant content yields an empty string."""
    lines = [
        '{"type": "result", "result": "# Plan"}',
        '{"type": "tool_call", "message": "run tests"}',
    ]
    out = extract_last_assistant_section_from_stream_json("\n".join(lines))
    assert out == ""


def test_extract_last_assistant_section_empty_input_returns_original() -> None:
    """Empty or only whitespace returns original string."""
    raw = "  \n  "
    assert extract_last_assistant_section_from_stream_json(raw) == raw


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
