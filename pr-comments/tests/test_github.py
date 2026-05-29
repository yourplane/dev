"""Tests for GitHub provider HTTP helpers."""

import json
from unittest.mock import MagicMock, patch

import pytest

from pr_comments.errors import PrCommentsError
from pr_comments.providers.github import fetch_github_comments, list_paginated_github_items


@patch("pr_comments.providers.github.github_request")
def test_list_paginated_github_items(mock_req: MagicMock) -> None:
    mock_req.side_effect = [
        (200, json.dumps([{"id": 1}])),
        (200, json.dumps([])),
    ]
    items = list_paginated_github_items("tok", "https://api.github.com/x")
    assert items == [{"id": 1}]


@patch("pr_comments.providers.github.list_paginated_github_items")
def test_fetch_github_comments(mock_list: MagicMock) -> None:
    mock_list.side_effect = [
        [{"id": 10, "body": "inline"}],
        [{"id": 20, "body": "general"}],
    ]
    items = fetch_github_comments("tok", "o", "r", 1)
    assert len(items) == 2
    assert items[0]["key"] == "review:10"
    assert items[1]["key"] == "issue:20"


@patch("pr_comments.providers.github.github_request")
def test_list_paginated_error(mock_req: MagicMock) -> None:
    mock_req.return_value = (403, json.dumps({"message": "Forbidden"}))
    with pytest.raises(PrCommentsError, match="Forbidden"):
        list_paginated_github_items("tok", "https://api.github.com/x")
