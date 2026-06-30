"""Tests for question_schema module."""

import json

from dev_sdk.question_schema import (
    extract_json_from_text,
    format_question_payload_json,
    normalize_question_payload,
    parse_question_output,
    QuestionPayload,
    QuestionItem,
)


def test_extract_json_from_fenced_block() -> None:
    text = 'Some intro\n```json\n{"intro": "hi", "questions": []}\n```\n'
    assert extract_json_from_text(text) == '{"intro": "hi", "questions": []}'


def test_extract_json_uses_last_fenced_block() -> None:
    text = '```json\n{"a": 1}\n```\nmore\n```json\n{"intro": "", "questions": []}\n```'
    assert '"questions"' in (extract_json_from_text(text) or "")


def test_extract_json_from_bare_object() -> None:
    text = 'Here is output:\n{"intro": "x", "questions": []}'
    assert extract_json_from_text(text) == '{"intro": "x", "questions": []}'


def test_parse_question_output_success() -> None:
    text = '```json\n{"intro": "Need clarity", "questions": [{"text": "Which?", "options": ["A", "B"]}]}\n```'
    payload, errors = parse_question_output(text)
    assert errors == []
    assert payload is not None
    assert payload.intro == "Need clarity"
    assert len(payload.questions) == 1
    assert payload.questions[0].id == "q1"
    assert payload.questions[0].text == "Which?"
    assert payload.questions[0].options == ["A", "B"]


def test_parse_question_output_empty_questions() -> None:
    text = '{"intro": "All clear", "questions": []}'
    payload, errors = parse_question_output(text)
    assert errors == []
    assert payload is not None
    assert payload.questions == []


def test_parse_question_output_validation_error() -> None:
    text = '{"intro": "x", "questions": [{"options": []}]}'
    payload, errors = parse_question_output(text)
    assert payload is None
    assert len(errors) >= 1


def test_parse_question_output_no_json() -> None:
    payload, errors = parse_question_output("just prose, no json")
    assert payload is None
    assert "No JSON object found" in errors[0]


def test_normalize_assigns_q_ids() -> None:
    payload = QuestionPayload(
        intro="",
        questions=[
            QuestionItem(text="First?", options=[]),
            QuestionItem(id="custom", text="Second?", options=["x"]),
        ],
    )
    normalized = normalize_question_payload(payload)
    assert normalized.questions[0].id == "q1"
    assert normalized.questions[1].id == "custom"


def test_format_question_payload_json() -> None:
    payload, _ = parse_question_output('{"intro": "a", "questions": []}')
    assert payload is not None
    formatted = format_question_payload_json(payload)
    data = json.loads(formatted)
    assert data["intro"] == "a"
    assert data["questions"] == []
