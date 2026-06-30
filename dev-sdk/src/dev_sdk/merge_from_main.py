"""Merge origin/main into the task's feature branch (fetch, merge, push).

Used by dev-server merge-from-main command. Raises MergeFromMainError on
validation failure before git steps run.
"""

from __future__ import annotations

import shlex
import subprocess
from pathlib import Path

from dev_sdk.create_pr import _ensure_clean_tree, _find_single_git_repo_under


class MergeFromMainError(Exception):
    """Raised when merge-from-main validation fails. Message is user-facing."""

    pass


def has_conflicted_merge_in_progress(repo_root: Path) -> bool:
    """True when a merge is in progress and there are unmerged paths."""
    merge_head = repo_root / ".git" / "MERGE_HEAD"
    if not merge_head.is_file():
        return False
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "--diff-filter=U"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return False
    return bool(result.stdout.strip())


def validate_merge_from_main_can_start(task_root: Path) -> Path:
    """
    Ensure merge-from-main may start. Returns repo_root.

    When resuming an existing conflicted merge, a dirty tree is allowed.
    Otherwise the tree must be clean (same as Create PR).
    """
    try:
        repo_root = _find_single_git_repo_under(task_root)
    except Exception as e:
        raise MergeFromMainError(str(e)) from e
    if not has_conflicted_merge_in_progress(repo_root):
        try:
            _ensure_clean_tree(repo_root)
        except Exception as e:
            raise MergeFromMainError(str(e)) from e
    return repo_root


def merge_shell_command(repo_root: Path, task_root: Path) -> str:
    """Shell command for bash-style comms; run with cwd set to task_root."""
    try:
        rel = repo_root.resolve().relative_to(task_root.resolve())
        prefix = f"cd {shlex.quote(str(rel))} && "
    except ValueError:
        prefix = ""
    return (
        f"{prefix}git fetch origin && "
        "git merge origin/main && "
        "("
        'git rev-parse --abbrev-ref "@{u}" >/dev/null 2>&1 && git push || '
        'git push -u origin "$(git rev-parse --abbrev-ref HEAD)"'
        ")"
    )
