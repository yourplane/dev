"""Tests for stream-json parsing."""

import pytest

from dev_sdk.stream_json import extract_plan_from_stream_json, format_stream_line_for_console


def test_extract_plan_prefers_result_event() -> None:
    raw = '{"type":"other"}\n{"type":"result","result":"# Plan\\n\\nStep 1."}'
    assert extract_plan_from_stream_json(raw) == "# Plan\n\nStep 1."


def test_extract_plan_fallback_accumulates_content() -> None:
    raw = '{"type":"assistant","message":{"content":[{"type":"text","text":"Hello"}]}}\n{"type":"text","text":" world"}'
    assert "Hello" in extract_plan_from_stream_json(raw)
    assert "world" in extract_plan_from_stream_json(raw)


def test_extract_plan_empty_returns_original() -> None:
    raw = ""
    assert extract_plan_from_stream_json(raw) == ""


def test_format_stream_line_assistant_text() -> None:
    line = '{"type":"assistant","message":{"content":[{"type":"text","text":"Hi"}]}}'
    text, is_thinking = format_stream_line_for_console(line)
    assert text == "Hi"
    assert is_thinking is False


def test_format_stream_line_thinking_delta() -> None:
    line = '{"type":"thinking","subtype":"delta","text":"..."}'
    text, is_thinking = format_stream_line_for_console(line)
    assert text == "..."
    assert is_thinking is True


def test_format_stream_line_skip_unknown() -> None:
    text, is_thinking = format_stream_line_for_console('{"type":"unknown"}')
    assert text is None
    assert is_thinking is False
