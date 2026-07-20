"""Build markdown for user question answers comms entries."""

from __future__ import annotations

from typing import TypedDict


class AnswerItem(TypedDict, total=False):
    id: str
    text: str
    selected: str | list[str]
    free_text: str


def _normalize_selected(selected: str | list[str] | None) -> list[str]:
    if selected is None:
        return []
    if isinstance(selected, list):
        return [item.strip() for item in selected if isinstance(item, str) and item.strip()]
    stripped = selected.strip()
    return [stripped] if stripped else []


def _has_answer(ans: AnswerItem) -> bool:
    if _normalize_selected(ans.get("selected")):
        return True
    return bool((ans.get("free_text") or "").strip())


def build_answers_markdown(source: str, answers: list[AnswerItem]) -> str:
    """Format answers as markdown for *-user-answers.md."""
    lines = ["# Answers", "", f"Source: `{source}`", ""]
    for ans in answers:
        if not _has_answer(ans):
            continue
        qid = ans.get("id", "")
        qtext = ans.get("text", "")
        header = f"## {qid} — {qtext}" if qid else f"## {qtext}"
        lines.append(header)
        lines.append("")
        selected_items = _normalize_selected(ans.get("selected"))
        free_text = (ans.get("free_text") or "").strip()
        if selected_items:
            if len(selected_items) == 1:
                lines.append(f"**Selected:** {selected_items[0]}")
            else:
                lines.append("**Selected:**")
                for item in selected_items:
                    lines.append(f"- {item}")
            lines.append("")
        if free_text:
            lines.append("**Additional notes:**")
            lines.append(free_text)
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"
