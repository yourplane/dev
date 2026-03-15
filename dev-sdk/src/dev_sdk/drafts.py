"""Draft storage: new-task draft under tasks root .drafts, comment draft under task_dir .drafts."""

from pathlib import Path
import json

DRAFTS_DIR = ".drafts"
NEW_TASK_DRAFT_FILE = "new-task.json"
COMMENT_DRAFT_FILE = "comment"


def drafts_dir_for_new_task(tasks_root: Path) -> Path:
    """Return path to .drafts under tasks root (for the single 'new task' draft)."""
    return Path(tasks_root) / DRAFTS_DIR


def drafts_dir_for_task(task_dir: Path) -> Path:
    """Return path to .drafts under the given task directory."""
    return Path(task_dir) / DRAFTS_DIR


def get_new_task_draft(tasks_root: Path) -> dict | None:
    """Read new-task draft from tasks_root/.drafts/new-task.json. Returns None if missing or empty."""
    d = drafts_dir_for_new_task(tasks_root)
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
    d = drafts_dir_for_new_task(tasks_root)
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


def get_task_comment_draft(task_dir: Path) -> str:
    """Read comment draft for task from task_dir/.drafts/comment. Returns '' if missing."""
    d = drafts_dir_for_task(task_dir)
    path = d / COMMENT_DRAFT_FILE
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def set_task_comment_draft(task_dir: Path, content: str) -> None:
    """Write comment draft. Empty content removes the file."""
    d = drafts_dir_for_task(task_dir)
    path = d / COMMENT_DRAFT_FILE
    if not content.strip():
        if path.exists():
            path.unlink()
        return
    d.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
