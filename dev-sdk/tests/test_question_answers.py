"""Tests for question_answers markdown builder."""

from dev_sdk.question_answers import build_answers_markdown


def test_build_answers_markdown_includes_source_and_selections() -> None:
    md = build_answers_markdown(
        "002-agent-question.md",
        [
            {"id": "q1", "text": "Which database?", "selected": "Postgres", "free_text": "Need pooling"},
        ],
    )
    assert "Source: `002-agent-question.md`" in md
    assert "## q1 — Which database?" in md
    assert "**Selected:** Postgres" in md
    assert "**Additional notes:**" in md
    assert "Need pooling" in md


def test_build_answers_markdown_omits_blank_sections() -> None:
    md = build_answers_markdown(
        "003-agent-question.md",
        [{"id": "q1", "text": "Notes only?", "selected": "", "free_text": "Just text"}],
    )
    assert "**Selected:**" not in md
    assert "**Additional notes:**" in md


def test_build_answers_markdown_omits_unanswered_questions() -> None:
    md = build_answers_markdown(
        "004-agent-question.md",
        [
            {"id": "q1", "text": "Answered?", "selected": "A", "free_text": ""},
            {"id": "q2", "text": "Skipped?", "selected": "", "free_text": ""},
        ],
    )
    assert "## q1 — Answered?" in md
    assert "## q2 — Skipped?" not in md


def test_build_answers_markdown_multi_select_uses_bullets() -> None:
    md = build_answers_markdown(
        "005-agent-question.md",
        [
            {
                "id": "q1",
                "text": "Pick many?",
                "selected": ["A", "B"],
                "free_text": "",
            },
        ],
    )
    assert "**Selected:**" in md
    assert "- A" in md
    assert "- B" in md
    assert "**Selected:** A" not in md
