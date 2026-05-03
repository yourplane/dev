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
        out: dict = {}
        if "title" in data and isinstance(data["title"], str):
            out["title"] = data["title"]
        if "repo" in data:
            if data["repo"] is None:
                out["repo"] = None
            elif isinstance(data["repo"], str):
                out["repo"] = data["repo"]
        if "comment" in data and isinstance(data["comment"], str):
            out["comment"] = data["comment"]
        # Legacy drafts used no_code_checkout instead of repo: null
        if data.get("no_code_checkout") is True and "repo" not in out:
            out["repo"] = None
        return out if out else None
    except (json.JSONDecodeError, OSError):
        return None


def set_new_task_draft(
    tasks_root: Path,
    title: str = "",
    repo: str | None = None,
    comment: str = "",
) -> None:
    """Write new-task draft. ``repo`` may be None (JSON null) to mean no repository selected.

    Removes the draft file when title, comment, and repo are all empty (``repo`` empty means
    None or a blank string).
    """
    d = _drafts_dir(tasks_root)
    path = d / NEW_TASK_DRAFT_FILE
    # Remove draft only when everything is blank and repo is not an explicit null (null means
    # "task without a repo" in the UI, which we still persist).
    repo_blank = isinstance(repo, str) and not repo.strip()
    if not title.strip() and not (comment or "").strip() and repo_blank:
        if path.exists():
            path.unlink()
        return
    d.mkdir(parents=True, exist_ok=True)
    payload = {"title": title, "repo": repo, "comment": comment}
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


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
