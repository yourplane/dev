import re
from pathlib import Path

_KEY_MARKDOWN = re.compile(
    r"\[//\]:\s*#\s*\(\s*pr_comment_key:\s*([^\s)]+)\s*\)"
)
_KEY_HTML = re.compile(r"<!--\s*pr_comment_key:\s*([^\s]+)\s*-->")


def collect_existing_keys(work_dir: Path) -> set[str]:
    """Scan work_dir for previously saved comment keys (all regular files)."""
    keys: set[str] = set()
    if not work_dir.exists() or not work_dir.is_dir():
        return keys
    for path in work_dir.iterdir():
        if not path.is_file() or path.name == "index.txt":
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for pattern in (_KEY_MARKDOWN, _KEY_HTML):
            for m in pattern.finditer(text):
                keys.add(m.group(1))
    return keys


def workspace_has_pulled_comments(work_dir: Path) -> bool:
    """True if the directory already contains pulled PR comment files or keys."""
    if any(work_dir.glob("*-pr-comments.md")):
        return True
    return bool(collect_existing_keys(work_dir))
