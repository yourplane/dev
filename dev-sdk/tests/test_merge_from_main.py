"""Tests for merge-from-main validation helpers."""

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from dev_sdk.merge_from_main import (
    MergeFromMainError,
    has_conflicted_merge_in_progress,
    merge_shell_command,
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
