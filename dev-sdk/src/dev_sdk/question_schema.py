"""Parse and validate structured question-mode agent output."""

from __future__ import annotations

import json
import re
from typing import Any, Literal

from pydantic import BaseModel, ValidationError, field_validator, model_validator

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)

ComplexityLevel = Literal["low", "medium", "high"]


class QuestionOption(BaseModel):
    label: str
    implications: str | None = None
    complexity: ComplexityLevel | None = None


class QuestionItem(BaseModel):
    id: str | None = None
    text: str
    examples: str | None = None
    multiple: bool = False
    options: list[QuestionOption]

    @model_validator(mode="before")
    @classmethod
    def _legacy_fields(cls, value: Any) -> Any:
        if isinstance(value, dict) and "rationale" in value and "examples" not in value:
            value = {**value, "examples": value["rationale"]}
        return value

    @field_validator("options", mode="before")
    @classmethod
    def _coerce_options(cls, value: Any) -> list[Any]:
        if not isinstance(value, list):
            raise ValueError("options must be a list")
        coerced: list[Any] = []
        for item in value:
            if isinstance(item, str):
                coerced.append({"label": item})
            else:
                coerced.append(item)
        return coerced


class QuestionPayload(BaseModel):
    summary: str = ""
    response: str | None = None
    questions: list[QuestionItem]

    @model_validator(mode="before")
    @classmethod
    def _legacy_intro(cls, value: Any) -> Any:
        if isinstance(value, dict) and "intro" in value and "summary" not in value:
            value = {**value, "summary": value["intro"]}
        return value


def extract_json_from_text(text: str) -> str | None:
    """Extract JSON from agent output: prefer last ```json fence, else last complete object."""
    fenced = list(_JSON_FENCE_RE.finditer(text))
    if fenced:
        candidate = fenced[-1].group(1).strip()
        if candidate:
            return candidate
    return _extract_last_json_object(text)


def _extract_last_json_object(text: str) -> str | None:
    depth = 0
    end = -1
    for i in range(len(text) - 1, -1, -1):
        ch = text[i]
        if ch == "}":
            if depth == 0:
                end = i
            depth += 1
        elif ch == "{":
            depth -= 1
            if depth == 0 and end >= 0:
                return text[i : end + 1]
    return None


def _format_validation_errors(exc: ValidationError) -> list[str]:
    errors: list[str] = []
    for err in exc.errors():
        loc = ".".join(str(part) for part in err.get("loc", ()))
        msg = err.get("msg", "invalid value")
        if loc:
            errors.append(f"{loc}: {msg}")
        else:
            errors.append(str(msg))
    return errors


def _serialize_option(option: QuestionOption) -> str | dict[str, str]:
    """Plain string when only a label; object when implications or complexity are set."""
    if option.implications is None and option.complexity is None:
        return option.label
    data: dict[str, str] = {"label": option.label}
    if option.implications is not None:
        data["implications"] = option.implications
    if option.complexity is not None:
        data["complexity"] = option.complexity
    return data


def normalize_question_payload(payload: QuestionPayload) -> QuestionPayload:
    """Assign q1, q2, … ids when missing."""
    questions: list[QuestionItem] = []
    for i, q in enumerate(payload.questions, start=1):
        qid = q.id.strip() if q.id and q.id.strip() else f"q{i}"
        questions.append(
            QuestionItem(
                id=qid,
                text=q.text,
                examples=q.examples,
                multiple=q.multiple,
                options=q.options,
            )
        )
    return QuestionPayload(
        summary=payload.summary,
        response=payload.response,
        questions=questions,
    )


def parse_question_output(text: str) -> tuple[QuestionPayload | None, list[str]]:
    """
    Parse agent output into a validated QuestionPayload.
    Returns (payload, errors). payload is None when parsing or validation fails.
    """
    raw = extract_json_from_text(text)
    if raw is None:
        return None, ["No JSON object found in output"]
    try:
        data: Any = json.loads(raw)
    except json.JSONDecodeError as e:
        return None, [f"Invalid JSON: {e}"]
    try:
        payload = QuestionPayload.model_validate(data)
    except ValidationError as e:
        return None, _format_validation_errors(e)
    return normalize_question_payload(payload), []


def format_question_payload_json(payload: QuestionPayload) -> str:
    """Canonical pretty-printed JSON for comms storage."""
    data: dict[str, Any] = {
        "questions": [],
    }
    if payload.summary.strip():
        data["summary"] = payload.summary
    if payload.response:
        data["response"] = payload.response
    for q in payload.questions:
        item: dict[str, Any] = {
            "id": q.id,
            "text": q.text,
            "options": [_serialize_option(o) for o in q.options],
        }
        if q.examples:
            item["examples"] = q.examples
        if q.multiple:
            item["multiple"] = True
        data["questions"].append(item)
    return json.dumps(data, indent=2) + "\n"
