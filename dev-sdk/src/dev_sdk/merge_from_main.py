"""Merge origin/main into the task's feature branch (fetch, merge, push).

Used by dev-server and cloud-worker merge-from-main command. Raises
MergeFromMainError on validation failure before git steps run.
"""

from __future__ import annotations

import shlex
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from dev_sdk.agent_run import AgentRunError
from dev_sdk.bash_runner import BashRunResult
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


@dataclass
class MergeFromMainHooks:
    """Runtime-specific hooks for merge-from-main orchestration."""

    stream_bash: Callable[
        [Path, str, Path, threading.Event],
        BashRunResult,
    ]
    run_conflict_resolution: Callable[
        [Path, threading.Event, Callable[[Path], None] | None],
        None,
    ]
    on_validation_error: Callable[[str], None] | None = None
    on_agent_error: Callable[[str], None] | None = None
    on_success_clear_error: Callable[[], None] | None = None
    on_agent_start: Callable[[Path], None] | None = None


def run_merge_from_main(
    task_dir: Path,
    *,
    cancel_event: threading.Event,
    hooks: MergeFromMainHooks,
) -> None:
    """
    Fetch/merge/push origin/main, or resume conflict resolution via agent.

    Validation and git/agent steps are shared; hooks wire bash streaming and
    conflict-resolution agent to each runtime.
    """
    try:
        repo_root = validate_merge_from_main_can_start(task_dir)

        def agent_start(stream_log_path: Path) -> None:
            if hooks.on_agent_start is not None:
                hooks.on_agent_start(stream_log_path)

        if has_conflicted_merge_in_progress(repo_root):
            hooks.run_conflict_resolution(task_dir, cancel_event, agent_start)
            return

        shell_command = merge_shell_command(repo_root, task_dir)
        result = hooks.stream_bash(task_dir, shell_command, task_dir, cancel_event)
        if cancel_event.is_set() or result.cancelled:
            return
        if result.exit_code == 0 and not has_conflicted_merge_in_progress(repo_root):
            return
        if has_conflicted_merge_in_progress(repo_root):
            hooks.run_conflict_resolution(task_dir, cancel_event, agent_start)
    except MergeFromMainError as e:
        if hooks.on_validation_error is not None:
            hooks.on_validation_error(str(e))
        else:
            raise
    except AgentRunError as e:
        if hooks.on_agent_error is not None:
            hooks.on_agent_error(str(e))
        else:
            raise
    else:
        if hooks.on_success_clear_error is not None:
            hooks.on_success_clear_error()
