"""Build markdown for user question answers comms entries."""

from __future__ import annotations

from typing import TypedDict


class AnswerItem(TypedDict, total=False):
    id: str
    text: str
    selected: str
    free_text: str


def build_answers_markdown(source: str, answers: list[AnswerItem]) -> str:
    """Format answers as markdown for *-user-answers.md."""
    lines = ["# Answers", "", f"Source: `{source}`", ""]
    for ans in answers:
        qid = ans.get("id", "")
        qtext = ans.get("text", "")
        header = f"## {qid} — {qtext}" if qid else f"## {qtext}"
        lines.append(header)
        lines.append("")
        selected = (ans.get("selected") or "").strip()
        free_text = (ans.get("free_text") or "").strip()
        if selected:
            lines.append(f"**Selected:** {selected}")
            lines.append("")
        if free_text:
            lines.append("**Additional notes:**")
            lines.append(free_text)
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"
