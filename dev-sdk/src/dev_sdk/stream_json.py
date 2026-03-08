"""Stream-json parsing for Cursor agent output."""

import json


def extract_plan_from_stream_json(streamed_output: str) -> str:
    """Extract plan markdown from streamed JSON (Cursor agent stream-json format)."""
    lines = [line.strip() for line in streamed_output.splitlines() if line.strip()]
    if not lines:
        return streamed_output
    # Prefer final "result" event (full plan text)
    for line in reversed(lines):
        try:
            obj = json.loads(line)
            if isinstance(obj, dict) and obj.get("type") == "result" and "result" in obj:
                result = obj["result"]
                if isinstance(result, str) and result.strip():
                    return result.strip()
        except json.JSONDecodeError:
            pass
    # Fall back: accumulate assistant message text and content/text/delta fields
    parts: list[str] = []
    for line in lines:
        try:
            obj = json.loads(line)
            if isinstance(obj, dict):
                if obj.get("type") == "assistant" and "message" in obj:
                    msg = obj["message"]
                    if isinstance(msg, dict) and "content" in msg:
                        for item in msg["content"] if isinstance(msg["content"], list) else []:
                            if isinstance(item, dict) and item.get("type") == "text" and "text" in item:
                                parts.append(item["text"])
                        continue
                for key in ("content", "text", "delta", "result"):
                    if key in obj and isinstance(obj[key], str):
                        parts.append(obj[key])
                        break
            elif isinstance(obj, str):
                parts.append(obj)
        except json.JSONDecodeError:
            parts.append(line)
    if parts:
        return "".join(parts).strip() or "\n".join(parts)
    return streamed_output


def format_stream_line_for_console(line: str) -> tuple[str | None, bool]:
    """Parse stream line; return (text_to_print, is_thinking). None means skip this line."""
    try:
        obj = json.loads(line)
        if not isinstance(obj, dict):
            return None, False
        if obj.get("type") == "assistant" and "message" in obj:
            msg = obj["message"]
            if isinstance(msg, dict) and "content" in msg:
                texts: list[str] = []
                for item in msg["content"] if isinstance(msg["content"], list) else []:
                    if isinstance(item, dict) and item.get("type") == "text" and "text" in item:
                        texts.append(item["text"])
                if texts:
                    return "".join(texts), False
        if obj.get("type") == "thinking" and obj.get("subtype") == "delta" and "text" in obj:
            text = obj["text"]
            if isinstance(text, str):
                return text, True
        return None, False
    except json.JSONDecodeError:
        return None, False
