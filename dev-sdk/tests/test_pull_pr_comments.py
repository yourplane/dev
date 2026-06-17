"""Tests for dev-sdk pull_pr_comments adapter."""

import os
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from dev_sdk.create_pr import CreatePRError, pull_pr_comments


@pytest.fixture
def task_with_comms(tmp_path: Path) -> Path:
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


@patch("dev_sdk.create_pr._get_github_token", return_value="tok")
@patch("dev_sdk.create_pr._secret_name_for_github_owner", return_value="secret")
@patch("dev_sdk.create_pr.find_existing_pull_request")
@patch("pr_comments.pull.fetch_github_comments")
def test_pull_pr_comments_writes_comms(
    mock_fetch: object,
    mock_find: object,
    _mock_secret: object,
    _mock_token: object,
    task_with_comms: Path,
) -> None:
    mock_find.return_value = "https://github.com/acme/test/pull/5"  # type: ignore[method-assign]
    mock_fetch.return_value = [  # type: ignore[attr-defined]
        {
            "kind": "issue",
            "key": "issue:1",
            "payload": {
                "id": 1,
                "user": {"login": "rev"},
                "created_at": "2024-01-01",
                "body": "Looks good",
            },
        }
    ]
    pr_url, count, filename = pull_pr_comments(task_with_comms)
    assert pr_url == "https://github.com/acme/test/pull/5"
    assert count == 1
    assert filename is not None
    assert filename.endswith("-agent-pr-comments.md")
    content = (task_with_comms / "comms" / filename).read_text(encoding="utf-8")
    assert "issue:1" in content
    index = (task_with_comms / "comms" / "index.txt").read_text(encoding="utf-8")
    assert filename in index


@patch("dev_sdk.create_pr.find_existing_pull_request", return_value=None)
def test_pull_pr_comments_no_pr(_mock_find: object, task_with_comms: Path) -> None:
    with pytest.raises(CreatePRError, match="No existing PR"):
        pull_pr_comments(task_with_comms)
