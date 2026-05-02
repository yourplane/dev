"""Draft storage: all drafts under tasks root .drafts (so the agent never sees them in task dirs)."""

from pathlib import Path
import json

DRAFTS_DIR = ".drafts"
NEW_TASK_DRAFT_FILE = "new-task.json"
COMMENT_DRAFT_PREFIX = "comment-"
BASH_DRAFT_PREFIX = "bash-"


def _drafts_dir(tasks_root: Path) -> Path:
    """Return path to .drafts under tasks root (all drafts live here)."""
    return Path(tasks_root) / DRAFTS_DIR


def _safe_comment_filename(task_name: str) -> str:
    r"""Safe filename for task comment draft (task_name already validated: no / or \)."""
    return f"{COMMENT_DRAFT_PREFIX}{task_name}"


def _safe_bash_filename(task_name: str) -> str:
    r"""Safe filename for task bash-input draft."""
    return f"{BASH_DRAFT_PREFIX}{task_name}"


def get_new_task_draft(tasks_root: Path) -> dict | None:
    """Read new-task draft from tasks_root/.drafts/new-task.json. Returns None if missing or empty."""
    d = _drafts_dir(tasks_root)
    path = d / NEW_TASK_DRAFT_FILE
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        out = {}
        for key in ("title", "repo", "comment"):
            if key in data and isinstance(data[key], str):
                out[key] = data[key]
        return out if out else None
    except (json.JSONDecodeError, OSError):
        return None


def set_new_task_draft(
    tasks_root: Path,
    title: str = "",
    repo: str = "",
    comment: str = "",
) -> None:
    """Write new-task draft. Empty strings clear the draft (file is removed if all empty)."""
    d = _drafts_dir(tasks_root)
    path = d / NEW_TASK_DRAFT_FILE
    if not title.strip() and not repo.strip() and not comment.strip():
        if path.exists():
            path.unlink()
        return
    d.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"title": title, "repo": repo, "comment": comment}, indent=2),
        encoding="utf-8",
    )


def get_task_comment_draft(tasks_root: Path, task_name: str) -> str:
    """Read comment draft for task from tasks_root/.drafts/comment-<task_name>. Returns '' if missing."""
    d = _drafts_dir(tasks_root)
    path = d / _safe_comment_filename(task_name)
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def set_task_comment_draft(tasks_root: Path, task_name: str, content: str) -> None:
    """Write comment draft. Empty content removes the file."""
    d = _drafts_dir(tasks_root)
    path = d / _safe_comment_filename(task_name)
    if not content.strip():
        if path.exists():
            path.unlink()
        return
    d.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def get_task_bash_draft(tasks_root: Path, task_name: str) -> str:
    """Read bash-input draft for task from tasks_root/.drafts/bash-<task_name>. Returns '' if missing."""
    d = _drafts_dir(tasks_root)
    path = d / _safe_bash_filename(task_name)
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def set_task_bash_draft(tasks_root: Path, task_name: str, content: str) -> None:
    """Write bash-input draft. Empty content removes the file."""
    d = _drafts_dir(tasks_root)
    path = d / _safe_bash_filename(task_name)
    if not content.strip():
        if path.exists():
            path.unlink()
        return
    d.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
