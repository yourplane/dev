"""Tests for merge-from-main validation helpers."""

import subprocess
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

from dev_sdk.bash_runner import BashRunResult
from dev_sdk.merge_from_main import (
    MergeFromMainError,
    MergeFromMainHooks,
    has_conflicted_merge_in_progress,
    merge_shell_command,
    run_merge_from_main,
    validate_merge_from_main_can_start,
)


def _init_repo(path: Path, *, branch: str = "feature") -> None:
    subprocess.run(["git", "init", "-b", branch], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True, capture_output=True)
    (path / "README.md").write_text("hello\n")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=path, check=True, capture_output=True)


def test_merge_shell_command_includes_cd_and_git_steps(tmp_path: Path) -> None:
    task = tmp_path / "task"
    repo = task / "myrepo"
    repo.mkdir(parents=True)
    _init_repo(repo)
    cmd = merge_shell_command(repo, task)
    assert cmd.startswith("cd myrepo && ")
    assert "git fetch origin" in cmd
    assert "git merge origin/main" in cmd
    assert "git push" in cmd


def test_validate_rejects_dirty_tree(tmp_path: Path) -> None:
    task = tmp_path / "task"
    repo = task / "myrepo"
    repo.mkdir(parents=True)
    _init_repo(repo)
    (repo / "dirty.txt").write_text("x\n")
    with pytest.raises(MergeFromMainError, match="Uncommitted changes"):
        validate_merge_from_main_can_start(task)


def test_validate_allows_conflicted_merge_with_dirty_tree(tmp_path: Path) -> None:
    task = tmp_path / "task"
    repo = task / "myrepo"
    repo.mkdir(parents=True)
    _init_repo(repo)
    with patch(
        "dev_sdk.merge_from_main.has_conflicted_merge_in_progress",
        return_value=True,
    ):
        root = validate_merge_from_main_can_start(task)
    assert root.resolve() == repo.resolve()


def test_has_conflicted_merge_false_without_merge_head(tmp_path: Path) -> None:
    task = tmp_path / "task"
    repo = task / "myrepo"
    repo.mkdir(parents=True)
    _init_repo(repo)
    assert not has_conflicted_merge_in_progress(repo)


def test_run_merge_from_main_skips_git_when_conflicted_merge_in_progress(tmp_path: Path) -> None:
    task = tmp_path / "task"
    repo = task / "myrepo"
    repo.mkdir(parents=True)
    _init_repo(repo)
    seen: dict[str, bool] = {"git": False, "agent": False}

    def stream_bash(*args: object, **kwargs: object) -> BashRunResult:
        seen["git"] = True
        return BashRunResult(0, False, False, False, None)

    def run_conflict(td: Path, cancel: threading.Event, on_start: object) -> None:
        seen["agent"] = True

    with patch(
        "dev_sdk.merge_from_main.has_conflicted_merge_in_progress",
        return_value=True,
    ):
        run_merge_from_main(
            task,
            cancel_event=threading.Event(),
            hooks=MergeFromMainHooks(
                stream_bash=stream_bash,
                run_conflict_resolution=run_conflict,
            ),
        )
    assert seen["agent"] is True
    assert seen["git"] is False


def test_run_merge_from_main_runs_agent_after_git_conflict(tmp_path: Path) -> None:
    task = tmp_path / "task"
    repo = task / "myrepo"
    repo.mkdir(parents=True)
    _init_repo(repo)
    seen: dict[str, bool] = {"agent": False}

    def stream_bash(*args: object, **kwargs: object) -> BashRunResult:
        return BashRunResult(1, False, False, False, None)

    def run_conflict(td: Path, cancel: threading.Event, on_start: object) -> None:
        seen["agent"] = True

    with patch(
        "dev_sdk.merge_from_main.has_conflicted_merge_in_progress",
        side_effect=[False, True],
    ):
        run_merge_from_main(
            task,
            cancel_event=threading.Event(),
            hooks=MergeFromMainHooks(
                stream_bash=stream_bash,
                run_conflict_resolution=run_conflict,
            ),
        )
    assert seen["agent"] is True


def test_run_merge_from_main_writes_clean_success_comms(tmp_path: Path) -> None:
    task = tmp_path / "task"
    repo = task / "myrepo"
    repo.mkdir(parents=True)
    _init_repo(repo)
    seen: dict[str, bool] = {"clean": False}

    def stream_bash(*args: object, **kwargs: object) -> BashRunResult:
        return BashRunResult(0, False, False, False, None)

    def on_clean() -> None:
        seen["clean"] = True
        from dev_sdk.merge_from_main import write_clean_merge_success_comms

        write_clean_merge_success_comms(task)

    with patch("dev_sdk.merge_from_main.has_conflicted_merge_in_progress", return_value=False):
        run_merge_from_main(
            task,
            cancel_event=threading.Event(),
            hooks=MergeFromMainHooks(
                stream_bash=stream_bash,
                run_conflict_resolution=lambda *a, **k: None,
                on_clean_merge_success=on_clean,
            ),
        )
    assert seen["clean"] is True
    from dev_sdk.comms import read_index

    assert any(name.endswith("-agent-merge-from-main.md") for name in read_index(task))
