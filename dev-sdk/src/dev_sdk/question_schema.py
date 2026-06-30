"""Parse and validate structured question-mode agent output."""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, ValidationError

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)


class QuestionItem(BaseModel):
    id: str | None = None
    text: str
    options: list[str]


class QuestionPayload(BaseModel):
    intro: str
    questions: list[QuestionItem]


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


def normalize_question_payload(payload: QuestionPayload) -> QuestionPayload:
    """Assign q1, q2, … ids when missing."""
    questions: list[QuestionItem] = []
    for i, q in enumerate(payload.questions, start=1):
        qid = q.id.strip() if q.id and q.id.strip() else f"q{i}"
        questions.append(QuestionItem(id=qid, text=q.text, options=q.options))
    return QuestionPayload(intro=payload.intro, questions=questions)


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
    data = payload.model_dump()
    return json.dumps(data, indent=2) + "\n"
