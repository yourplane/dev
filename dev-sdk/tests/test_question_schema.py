"""Tests for question_schema module."""

import json

from dev_sdk.question_schema import (
    extract_json_from_text,
    format_question_payload_json,
    normalize_question_payload,
    parse_question_output,
    QuestionPayload,
    QuestionItem,
    QuestionOption,
)


def test_extract_json_from_fenced_block() -> None:
    text = 'Some intro\n```json\n{"summary": "hi", "questions": []}\n```\n'
    assert extract_json_from_text(text) == '{"summary": "hi", "questions": []}'


def test_extract_json_uses_last_fenced_block() -> None:
    text = '```json\n{"a": 1}\n```\nmore\n```json\n{"summary": "", "questions": []}\n```'
    assert '"questions"' in (extract_json_from_text(text) or "")


def test_extract_json_from_bare_object() -> None:
    text = 'Here is output:\n{"summary": "x", "questions": []}'
    assert extract_json_from_text(text) == '{"summary": "x", "questions": []}'


def test_parse_question_output_success() -> None:
    text = '```json\n{"summary": "Need clarity", "questions": [{"text": "Which?", "options": ["A", "B"]}]}\n```'
    payload, errors = parse_question_output(text)
    assert errors == []
    assert payload is not None
    assert payload.summary == "Need clarity"
    assert len(payload.questions) == 1
    assert payload.questions[0].id == "q1"
    assert payload.questions[0].text == "Which?"
    assert payload.questions[0].options == [
        QuestionOption(label="A"),
        QuestionOption(label="B"),
    ]


def test_parse_question_output_accepts_legacy_intro() -> None:
    text = '{"intro": "Legacy", "questions": []}'
    payload, errors = parse_question_output(text)
    assert errors == []
    assert payload is not None
    assert payload.summary == "Legacy"


def test_parse_question_output_with_examples_and_object_options() -> None:
    text = """```json
{
  "summary": "Tradeoffs ahead",
  "response": "Thanks for the prior answer.",
  "questions": [{
    "text": "Which approach?",
    "examples": "e.g. monolith vs services.",
    "multiple": true,
    "options": [
      "Simple path",
      {"label": "Full service", "implications": "Adds a new service.", "complexity": "high"}
    ]
  }]
}
```"""
    payload, errors = parse_question_output(text)
    assert errors == []
    assert payload is not None
    assert payload.response == "Thanks for the prior answer."
    q = payload.questions[0]
    assert q.examples == "e.g. monolith vs services."
    assert q.multiple is True
    assert q.options[0] == QuestionOption(label="Simple path")
    assert q.options[1] == QuestionOption(
        label="Full service",
        implications="Adds a new service.",
        complexity="high",
    )


def test_parse_question_output_accepts_legacy_rationale() -> None:
    text = '{"summary": "", "questions": [{"text": "Q?", "rationale": "Because.", "options": ["A"]}]}'
    payload, errors = parse_question_output(text)
    assert errors == []
    assert payload is not None
    assert payload.questions[0].examples == "Because."


def test_parse_question_output_rejects_invalid_complexity() -> None:
    text = '{"summary": "", "questions": [{"text": "Q?", "options": [{"label": "X", "complexity": "extreme"}]}]}'
    payload, errors = parse_question_output(text)
    assert payload is None
    assert len(errors) >= 1


def test_parse_question_output_empty_questions() -> None:
    text = '{"summary": "All clear", "questions": []}'
    payload, errors = parse_question_output(text)
    assert errors == []
    assert payload is not None
    assert payload.questions == []


def test_parse_question_output_validation_error() -> None:
    text = '{"summary": "x", "questions": [{"options": []}]}'
    payload, errors = parse_question_output(text)
    assert payload is None
    assert len(errors) >= 1


def test_parse_question_output_no_json() -> None:
    payload, errors = parse_question_output("just prose, no json")
    assert payload is None
    assert "No JSON object found" in errors[0]


def test_normalize_assigns_q_ids() -> None:
    payload = QuestionPayload(
        summary="",
        questions=[
            QuestionItem(text="First?", options=[]),
            QuestionItem(id="custom", text="Second?", options=[QuestionOption(label="x")]),
        ],
    )
    normalized = normalize_question_payload(payload)
    assert normalized.questions[0].id == "q1"
    assert normalized.questions[1].id == "custom"


def test_parse_question_output_accepts_missing_summary() -> None:
    text = '{"questions": [{"text": "Which?", "options": ["A"]}]}'
    payload, errors = parse_question_output(text)
    assert errors == []
    assert payload is not None
    assert payload.summary == ""


def test_format_question_payload_json_omits_empty_summary() -> None:
    payload, _ = parse_question_output('{"questions": []}')
    assert payload is not None
    formatted = format_question_payload_json(payload)
    data = json.loads(formatted)
    assert "summary" not in data
    assert data["questions"] == []


def test_format_question_payload_json_plain_options() -> None:
    payload, _ = parse_question_output('{"summary": "a", "questions": []}')
    assert payload is not None
    formatted = format_question_payload_json(payload)
    data = json.loads(formatted)
    assert data["summary"] == "a"
    assert data["questions"] == []


def test_format_question_payload_json_preserves_metadata() -> None:
    payload, _ = parse_question_output(
        '{"summary": "a", "response": "Prior reply.", "questions": [{"text": "Q?", "examples": "Because.", '
        '"multiple": true, "options": ["A", {"label": "B", "implications": "More work.", "complexity": "medium"}]}]}'
    )
    assert payload is not None
    formatted = format_question_payload_json(payload)
    data = json.loads(formatted)
    assert data["response"] == "Prior reply."
    q = data["questions"][0]
    assert q["examples"] == "Because."
    assert q["multiple"] is True
    assert q["options"][0] == "A"
    assert q["options"][1] == {
        "label": "B",
        "implications": "More work.",
        "complexity": "medium",
    }
