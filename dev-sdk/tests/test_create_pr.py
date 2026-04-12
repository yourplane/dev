"""Tests for PR discovery (find_existing_pull_request) and bot secret resolution."""

import json
import os
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from dev_sdk.create_pr import (
    CreatePRError,
    _list_pull_requests_api,
    _secret_name_for_github_owner,
    find_existing_pull_request,
)


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
@patch("dev_sdk.create_pr._secret_name_for_github_owner", return_value="dummy-secret")
def test_find_existing_returns_none_when_only_closed_pr(
    _mock_secret: object, mock_token: object, mock_list: object, task_with_git_repo: Path
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
@patch("dev_sdk.create_pr._secret_name_for_github_owner", return_value="dummy-secret")
def test_find_existing_returns_url_for_open_pr(
    _mock_secret: object, mock_token: object, mock_list: object, task_with_git_repo: Path
) -> None:
    mock_token.return_value = "tok"  # type: ignore[method-assign]
    url = "https://github.com/acme/test/pull/2"
    mock_list.return_value = (  # type: ignore[method-assign]
        200,
        json.dumps([{"title": "my-task", "state": "open", "html_url": url}]),
    )
    assert find_existing_pull_request(task_with_git_repo) == url


def test_secret_name_case_insensitive(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg = tmp_path / ".config" / "git-auth"
    cfg.mkdir(parents=True)
    (cfg / "bots.json").write_text(
        json.dumps({"bots": [{"org": "ACME", "secret": "  my-secret  "}]}),
        encoding="utf-8",
    )
    assert _secret_name_for_github_owner("acme") == "my-secret"


def test_secret_name_missing_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    with pytest.raises(CreatePRError, match="GitHub bot config not found"):
        _secret_name_for_github_owner("acme")


def test_secret_name_unknown_owner(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg = tmp_path / ".config" / "git-auth"
    cfg.mkdir(parents=True)
    (cfg / "bots.json").write_text(
        json.dumps({"bots": [{"org": "other", "secret": "x"}]}),
        encoding="utf-8",
    )
    with pytest.raises(CreatePRError, match="No GitHub bot secret configured"):
        _secret_name_for_github_owner("acme")


def test_secret_name_invalid_json(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg = tmp_path / ".config" / "git-auth"
    cfg.mkdir(parents=True)
    (cfg / "bots.json").write_text("{", encoding="utf-8")
    with pytest.raises(CreatePRError, match="Invalid JSON"):
        _secret_name_for_github_owner("acme")


@patch("dev_sdk.create_pr._github_request")
def test_list_pull_requests_api_uses_state_open(mock_github: object) -> None:
    mock_github.return_value = (200, "[]")  # type: ignore[method-assign]
    _list_pull_requests_api("tok", "owner", "repo", head="owner:branch")
    _call = mock_github.call_args
    assert _call is not None
    _url = _call[0][2]
    assert "state=open" in _url
    assert "state=all" not in _url
