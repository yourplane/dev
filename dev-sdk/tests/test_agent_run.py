"""Tests for agent_run module."""

import json

import pytest

from dev_sdk.agent_run import (
    AgentRunError,
    QUESTION_STREAM_LOG_PREFIX,
    _remove_empty_log_file,
    extract_last_assistant_section_from_stream_json,
    run_question_mode,
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


def test_run_question_mode_writes_comms_with_json(tmp_path, monkeypatch) -> None:
    """Question mode writes canonical JSON to agent-question comms on successful parse."""
    task_dir = tmp_path / "task"
    task_dir.mkdir()
    (task_dir / "comms").mkdir()
    (task_dir / "comms" / "index.txt").write_text("")

    valid_json = '{"intro": "Need clarity", "questions": [{"text": "What scope?", "options": ["A", "B"]}]}'
    assistant_text = f"```json\n{valid_json}\n```"
    streamed = json.dumps(
        {
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": assistant_text}]},
            "model_call_id": "c1",
        }
    ) + "\n"

    def fake_run(task_dir_arg, prompt, prefix, **kwargs):
        log_path = task_dir / ".logs" / f"{prefix}test.log"
        log_path.parent.mkdir(exist_ok=True)
        log_path.write_text(streamed)
        return log_path, streamed

    monkeypatch.setattr("dev_sdk.agent_run._create_ephemeral_chat", lambda: "ephemeral-chat-id")
    monkeypatch.setattr("dev_sdk.agent_run._run_agent_ask_stream_json", fake_run)
    result = run_question_mode(task_dir)
    assert result.comms_path.name.endswith("-agent-question.md")
    comms_text = result.comms_path.read_text(encoding="utf-8")
    assert '"summary": "Need clarity"' in comms_text
    assert '"id": "q1"' in comms_text
    assert not (task_dir / "task-question-draft.md").exists()
    index = (task_dir / "comms" / "index.txt").read_text()
    assert "agent-question" in index
    assert QUESTION_STREAM_LOG_PREFIX in result.stream_log_path.name


def test_run_question_mode_retries_then_succeeds(tmp_path, monkeypatch) -> None:
    """Question mode retries on parse failure and writes comms only after success."""
    task_dir = tmp_path / "task"
    task_dir.mkdir()
    (task_dir / "comms").mkdir()
    (task_dir / "comms" / "index.txt").write_text("")

    invalid = json.dumps(
        {
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": "not json"}]},
            "model_call_id": "c1",
        }
    ) + "\n"
    valid_json = '{"intro": "", "questions": []}'
    valid = json.dumps(
        {
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": f"```json\n{valid_json}\n```"}]},
            "model_call_id": "c2",
        }
    ) + "\n"
    calls: list[str] = []

    def fake_run(task_dir_arg, prompt, prefix, **kwargs):
        calls.append(prompt)
        log_path = task_dir / ".logs" / f"{prefix}{len(calls)}.log"
        log_path.parent.mkdir(exist_ok=True)
        body = invalid if len(calls) == 1 else valid
        log_path.write_text(body)
        return log_path, body

    monkeypatch.setattr("dev_sdk.agent_run._create_ephemeral_chat", lambda: "ephemeral-chat-id")
    monkeypatch.setattr("dev_sdk.agent_run._run_agent_ask_stream_json", fake_run)
    result = run_question_mode(task_dir)
    assert len(calls) == 2
    assert "Validation errors" in calls[1]
    assert '"questions": []' in result.comms_path.read_text(encoding="utf-8")


def test_run_question_mode_failure_writes_raw_output(tmp_path, monkeypatch) -> None:
    """After 3 failed parses, comms contains raw last-run output."""
    task_dir = tmp_path / "task"
    task_dir.mkdir()
    (task_dir / "comms").mkdir()
    (task_dir / "comms" / "index.txt").write_text("")

    invalid = json.dumps(
        {
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": "bad output"}]},
            "model_call_id": "c1",
        }
    ) + "\n"

    def fake_run(task_dir_arg, prompt, prefix, **kwargs):
        log_path = task_dir / ".logs" / f"{prefix}test.log"
        log_path.parent.mkdir(exist_ok=True)
        log_path.write_text(invalid)
        return log_path, invalid

    monkeypatch.setattr("dev_sdk.agent_run._create_ephemeral_chat", lambda: "ephemeral-chat-id")
    monkeypatch.setattr("dev_sdk.agent_run._run_agent_ask_stream_json", fake_run)
    result = run_question_mode(task_dir)
    assert result.comms_path.read_text(encoding="utf-8").strip() == "bad output"
