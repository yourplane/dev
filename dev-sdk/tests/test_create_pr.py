"""Tests for PR discovery (find_existing_pull_request)."""

import json
import os
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from dev_sdk.create_pr import _list_pull_requests_api, find_existing_pull_request


@pytest.fixture
def task_with_git_repo(tmp_path: Path) -> Path:
    """Task root named `my-task` with comms/ and one nested git repo on branch `feature`."""
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
    subprocess.run(["git", "checkout", "-b", "feature"], cwd=repo, check=True, capture_output=True)
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


@patch("dev_sdk.create_pr._list_pull_requests_api")
@patch("dev_sdk.create_pr._get_github_token")
def test_find_existing_returns_none_when_only_closed_pr(
    mock_token: object, mock_list: object, task_with_git_repo: Path
) -> None:
    mock_token.return_value = "tok"  # type: ignore[method-assign]
    mock_list.return_value = (  # type: ignore[method-assign]
        200,
        json.dumps(
            [
                {
                    "title": "my-task",
                    "state": "closed",
                    "html_url": "https://github.com/acme/test/pull/1",
                }
            ]
        ),
    )
    assert find_existing_pull_request(task_with_git_repo) is None


@patch("dev_sdk.create_pr._list_pull_requests_api")
@patch("dev_sdk.create_pr._get_github_token")
def test_find_existing_returns_url_for_open_pr(
    mock_token: object, mock_list: object, task_with_git_repo: Path
) -> None:
    mock_token.return_value = "tok"  # type: ignore[method-assign]
    url = "https://github.com/acme/test/pull/2"
    mock_list.return_value = (  # type: ignore[method-assign]
        200,
        json.dumps([{"title": "my-task", "state": "open", "html_url": url}]),
    )
    assert find_existing_pull_request(task_with_git_repo) == url


@patch("dev_sdk.create_pr._github_request")
def test_list_pull_requests_api_uses_state_open(mock_github: object) -> None:
    mock_github.return_value = (200, "[]")  # type: ignore[method-assign]
    _list_pull_requests_api("tok", "owner", "repo", head="owner:branch")
    _call = mock_github.call_args
    assert _call is not None
    _url = _call[0][2]
    assert "state=open" in _url
    assert "state=all" not in _url
