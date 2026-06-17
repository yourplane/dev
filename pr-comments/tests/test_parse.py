"""Tests for URL parsing."""

import pytest

from pr_comments.errors import PrCommentsError
from pr_comments.parse import parse_pr_url


def test_parse_github_url() -> None:
    cfg = parse_pr_url("https://github.com/acme/my-repo/pull/42")
    assert cfg.provider == "github"
    assert cfg.owner == "acme"
    assert cfg.repo == "my-repo"
    assert cfg.pr_id == 42


def test_parse_bitbucket_url() -> None:
    cfg = parse_pr_url("https://bitbucket.org/ws/repo/pull-requests/7")
    assert cfg.provider == "bitbucket"
    assert cfg.owner == "ws"
    assert cfg.repo == "repo"
    assert cfg.pr_id == 7


def test_invalid_url_raises() -> None:
    with pytest.raises(PrCommentsError):
        parse_pr_url("https://gitlab.com/a/b/-/merge_requests/1")
