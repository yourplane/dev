"""Tests for create_pr module."""

import pytest

from dev_sdk.create_pr import (
    CreatePrError,
    parse_owner_repo,
    validate_task_root,
    find_single_git_repo_under,
    ensure_not_main,
    ensure_clean_tree,
)


def test_parse_owner_repo_https() -> None:
    assert parse_owner_repo("https://github.com/owner/repo.git") == ("owner", "repo")
    assert parse_owner_repo("https://github.com/owner/repo") == ("owner", "repo")
    assert parse_owner_repo("https://user@github.com/foo/bar.git") == ("foo", "bar")


def test_parse_owner_repo_ssh() -> None:
    assert parse_owner_repo("git@github.com:owner/repo.git") == ("owner", "repo")
    assert parse_owner_repo("git@github.com:foo/bar") == ("foo", "bar")


def test_parse_owner_repo_invalid() -> None:
    with pytest.raises(ValueError, match="Cannot parse"):
        parse_owner_repo("https://gitlab.com/owner/repo.git")
    with pytest.raises(ValueError, match="Cannot parse"):
        parse_owner_repo("not-a-url")


def test_validate_task_root_missing(tmp_path) -> None:
    with pytest.raises(CreatePrError, match="Task directory not found"):
        validate_task_root(tmp_path / "nonexistent")


def test_validate_task_root_no_comms(tmp_path) -> None:
    task_root = tmp_path / "task"
    task_root.mkdir()
    with pytest.raises(CreatePrError, match="Not a task root"):
        validate_task_root(task_root)


def test_validate_task_root_ok(tmp_path) -> None:
    (tmp_path / "comms").mkdir()
    validate_task_root(tmp_path)


def test_ensure_not_main(tmp_path) -> None:
    """ensure_not_main raises when current branch is main (mocked git)."""
    from unittest.mock import patch
    repo = tmp_path / "repo"
    repo.mkdir()
    with patch("dev_sdk.create_pr.git_output") as mock_git:
        mock_git.return_value = "main"
        with pytest.raises(CreatePrError, match="feature branch"):
            ensure_not_main(repo)


def test_ensure_clean_tree_dirty(tmp_path) -> None:
    import subprocess
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "checkout", "-b", "feature"], cwd=repo, capture_output=True, check=True)
    (repo / "file").write_text("x")
    with pytest.raises(CreatePrError, match="Uncommitted"):
        ensure_clean_tree(repo)
