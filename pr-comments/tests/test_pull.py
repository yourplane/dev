"""Tests for init and pull orchestration."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from pr_comments.errors import PrCommentsError
from pr_comments.pull import init_workspace, pull_comments


def test_init_writes_config(tmp_path: Path) -> None:
    cfg = init_workspace(tmp_path, "https://github.com/o/r/pull/3")
    assert cfg.pr_id == 3
    data = json.loads((tmp_path / "pr-comments.json").read_text(encoding="utf-8"))
    assert data["provider"] == "github"


def test_init_fails_when_config_exists(tmp_path: Path) -> None:
    init_workspace(tmp_path, "https://github.com/o/r/pull/1")
    with pytest.raises(PrCommentsError, match="already initialized"):
        init_workspace(tmp_path, "https://github.com/o/r/pull/2")


def test_init_fails_when_comments_exist(tmp_path: Path) -> None:
    (tmp_path / "001-pr-comments.md").write_text(
        "[//]: # (pr_comment_key: review:1)\n", encoding="utf-8"
    )
    with pytest.raises(PrCommentsError, match="already exist"):
        init_workspace(tmp_path, "https://github.com/o/r/pull/1")


@patch("pr_comments.pull.fetch_github_comments")
def test_pull_writes_new_file(mock_fetch: object, tmp_path: Path) -> None:
    init_workspace(tmp_path, "https://github.com/o/r/pull/1")
    mock_fetch.return_value = [  # type: ignore[attr-defined]
        {
            "kind": "issue",
            "key": "issue:7",
            "payload": {
                "id": 7,
                "user": {"login": "rev"},
                "created_at": "2024-01-02",
                "body": "LGTM",
            },
        }
    ]
    result = pull_comments(tmp_path, token="tok")
    assert result.new_count == 1
    assert result.output_filename == "001-pr-comments.md"
    assert (tmp_path / "001-pr-comments.md").exists()
    assert "issue:7" in (tmp_path / "001-pr-comments.md").read_text(encoding="utf-8")


@patch("pr_comments.pull.fetch_github_comments")
def test_pull_skips_known_comments(mock_fetch: object, tmp_path: Path) -> None:
    init_workspace(tmp_path, "https://github.com/o/r/pull/1")
    (tmp_path / "001-pr-comments.md").write_text(
        "[//]: # (pr_comment_key: issue:7)\n", encoding="utf-8"
    )
    mock_fetch.return_value = [  # type: ignore[attr-defined]
        {
            "kind": "issue",
            "key": "issue:7",
            "payload": {"id": 7, "user": {"login": "rev"}, "created_at": "t", "body": "x"},
        }
    ]
    result = pull_comments(tmp_path, token="tok")
    assert result.new_count == 0
    assert result.output_filename is None


@patch("pr_comments.pull.fetch_github_comments")
def test_pull_custom_write_output(mock_fetch: object, tmp_path: Path) -> None:
    mock_fetch.return_value = [  # type: ignore[attr-defined]
        {
            "kind": "review",
            "key": "review:1",
            "payload": {
                "id": 1,
                "user": {"login": "a"},
                "created_at": "t",
                "body": "hi",
            },
        }
    ]
    written: list[str] = []

    def writer(md: str) -> str:
        written.append(md)
        return "custom.md"

    result = pull_comments(
        tmp_path,
        pr_url="https://github.com/o/r/pull/9",
        token="tok",
        write_output=writer,
    )
    assert result.output_filename == "custom.md"
    assert len(written) == 1
    assert "review:1" in written[0]
