from pr_comments.models import CommentItem


def context_lines_for_comment(kind: str, payload: dict) -> list[str]:
    """File/line and optional diff snippet for review/inline comments."""
    out: list[str] = []
    if kind in ("issue", "general"):
        out.append("- Context: general PR conversation (not tied to a file or line)")
        return out
    if kind == "inline":
        inline = payload.get("inline")
        if isinstance(inline, dict):
            path = inline.get("path")
            if isinstance(path, str) and path.strip():
                out.append(f"- File: `{path.strip()}`")
            to_line = inline.get("to")
            from_line = inline.get("from")
            if isinstance(from_line, int) and isinstance(to_line, int) and from_line != to_line:
                out.append(f"- Lines: {from_line}-{to_line}")
            elif isinstance(to_line, int):
                out.append(f"- Line: {to_line}")
            elif isinstance(from_line, int):
                out.append(f"- Line: {from_line}")
        return out
    # GitHub review comment
    path = payload.get("path")
    if isinstance(path, str) and path.strip():
        out.append(f"- File: `{path.strip()}`")
    line = payload.get("line")
    original_line = payload.get("original_line")
    start_line = payload.get("start_line")
    if isinstance(start_line, int) and isinstance(line, int) and start_line != line:
        out.append(f"- Lines: {start_line}-{line}")
    elif isinstance(line, int):
        out.append(f"- Line: {line}")
    elif isinstance(original_line, int):
        out.append(f"- Line (as of original diff): {original_line}")
    elif path:
        out.append("- Line: _(not reported by API for this comment)_")
    diff_hunk = payload.get("diff_hunk")
    if isinstance(diff_hunk, str) and diff_hunk.strip():
        snippet = diff_hunk.strip()
        max_chars = 4000
        if len(snippet) > max_chars:
            snippet = snippet[:max_chars] + "\n… _(truncated)_"
        out.append("")
        out.append("Surrounding diff:")
        out.append("")
        out.append("```diff")
        out.append(snippet)
        out.append("```")
    return out


def _author_name(kind: str, payload: dict) -> str:
    if kind in ("general", "inline"):
        user = payload.get("user")
        if isinstance(user, dict):
            display = user.get("display_name") or user.get("nickname")
            if isinstance(display, str) and display.strip():
                return display.strip()
    user = payload.get("user") if isinstance(payload.get("user"), dict) else {}
    login = user.get("login") or user.get("nickname")
    if isinstance(login, str) and login.strip():
        return login.strip()
    return "unknown"


def _created_at(payload: dict) -> str:
    created = payload.get("created_at") or payload.get("created_on")
    return str(created or "unknown")


def _html_url(payload: dict) -> str:
    for key in ("html_url", "links"):
        val = payload.get(key)
        if isinstance(val, str) and val:
            return val
        if isinstance(val, dict):
            html = val.get("html")
            if isinstance(html, dict):
                href = html.get("href")
                if isinstance(href, str):
                    return href
    return ""


def _body_text(payload: dict) -> str:
    content = payload.get("content")
    if isinstance(content, dict):
        raw = content.get("raw")
        if isinstance(raw, str):
            return raw.strip()
    body = payload.get("body")
    if isinstance(body, str):
        return body.strip()
    return ""


def format_comments_markdown(
    pr_url: str, pr_id: int, items: list[CommentItem]
) -> str:
    lines: list[str] = []
    lines.append(f"# Pulled PR comments ({len(items)} new)")
    lines.append("")
    lines.append(f"- PR: {pr_url}")
    lines.append(f"- PR number: {pr_id}")
    lines.append("")
    for item in items:
        payload = item.payload
        author = _author_name(item.kind, payload)
        created_at = _created_at(payload)
        html_url = _html_url(payload)
        body = _body_text(payload)
        title_kind = item.kind.replace("_", " ").title()
        lines.append(f"## {title_kind} comment `{item.key}`")
        lines.append(f"- Author: {author}")
        lines.append(f"- Created: {created_at}")
        if html_url:
            lines.append(f"- URL: {html_url}")
        lines.extend(context_lines_for_comment(item.kind, payload))
        lines.append("")
        lines.append(body if body else "_(no body)_")
        lines.append("")
        lines.append(f"[//]: # (pr_comment_key: {item.key})")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
