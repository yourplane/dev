"""Tests for GitHub Compare branch status."""

import json
import os
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from dev_sdk.branch_status import (
    get_branch_status_from_metadata,
    get_branch_status_from_task,
)


@pytest.fixture
def task_with_git_repo(tmp_path: Path) -> Path:
    task = tmp_path / "my-task"
    task.mkdir()
    (task / "comms").mkdir()
    repo = task / "repo"
    repo.mkdir()
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "test",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "test",
        "GIT_COMMITTER_EMAIL": "test@example.com",
    }
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "checkout", "-b", "task/my-task"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "--allow-empty", "-m", "init"],
        cwd=repo,
        check=True,
        capture_output=True,
        env=env,
    )
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/acme/test.git"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    return task


@patch("dev_sdk.branch_status._compare_branches_api")
@patch("dev_sdk.branch_status._get_github_token")
@patch("dev_sdk.branch_status._secret_name_for_github_owner", return_value="dummy-secret")
def test_get_branch_status_from_task_returns_counts(
    _mock_secret: object,
    mock_token: object,
    mock_compare: object,
    task_with_git_repo: Path,
) -> None:
    mock_token.return_value = "tok"  # type: ignore[method-assign]
    mock_compare.return_value = (  # type: ignore[method-assign]
        200,
        json.dumps({"ahead_by": 3, "behind_by": 5, "status": "diverged"}),
    )
    assert get_branch_status_from_task(task_with_git_repo) == {"ahead": 3, "behind": 5}


@patch("dev_sdk.branch_status._compare_branches_api")
@patch("dev_sdk.branch_status._get_github_token")
@patch("dev_sdk.branch_status._secret_name_for_github_owner", return_value="dummy-secret")
def test_get_branch_status_from_task_hides_on_404(
    _mock_secret: object,
    mock_token: object,
    mock_compare: object,
    task_with_git_repo: Path,
) -> None:
    mock_token.return_value = "tok"  # type: ignore[method-assign]
    mock_compare.return_value = (404, '{"message":"Not Found"}')  # type: ignore[method-assign]
    assert get_branch_status_from_task(task_with_git_repo) is None


@patch("dev_sdk.branch_status._compare_branches_api")
def test_get_branch_status_from_metadata_up_to_date(mock_compare: object) -> None:
    mock_compare.return_value = (  # type: ignore[method-assign]
        200,
        json.dumps({"ahead_by": 0, "behind_by": 0, "status": "identical"}),
    )
    bots = [{"org": "acme", "secret": "sec"}]
    with patch("dev_sdk.branch_status._get_github_token_boto", return_value="tok"):
        assert get_branch_status_from_metadata(
            owner="acme",
            repo="test",
            branch="task/foo",
            bots=bots,
        ) == {"ahead": 0, "behind": 0}


@patch("dev_sdk.branch_status._compare_branches_api")
def test_get_branch_status_from_metadata_hides_on_error(mock_compare: object) -> None:
    mock_compare.return_value = (403, '{"message":"Forbidden"}')  # type: ignore[method-assign]
    bots = [{"org": "acme", "secret": "sec"}]
    with patch("dev_sdk.branch_status._get_github_token_boto", return_value="tok"):
        assert get_branch_status_from_metadata(
            owner="acme",
            repo="test",
            branch="task/foo",
            bots=bots,
        ) is None
