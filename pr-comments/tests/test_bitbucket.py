"""Tests for Bitbucket provider HTTP helpers."""

import json
from unittest.mock import MagicMock, patch

import pytest

from pr_comments.errors import PrCommentsError
from pr_comments.providers.bitbucket import (
    fetch_bitbucket_comments,
    list_paginated_bitbucket_items,
)


@patch("pr_comments.providers.bitbucket._bitbucket_request")
def test_list_paginated_bitbucket_items(mock_req: MagicMock) -> None:
    mock_req.side_effect = [
        (
            200,
            json.dumps(
                {
                    "values": [{"id": 1}],
                    "next": "https://api.bitbucket.org/2.0/next",
                }
            ),
        ),
        (200, json.dumps({"values": [{"id": 2}]})),
    ]
    items = list_paginated_bitbucket_items("u", "pw", "https://api.bitbucket.org/start")
    assert [i["id"] for i in items] == [1, 2]


@patch("pr_comments.providers.bitbucket.list_paginated_bitbucket_items")
def test_fetch_bitbucket_comments(mock_list: MagicMock) -> None:
    mock_list.return_value = [
        {"id": 1, "content": {"raw": "general"}},
        {"id": 2, "content": {"raw": "inline"}, "inline": {"path": "a.py", "to": 1}},
    ]
    items = fetch_bitbucket_comments("u", "pw", "ws", "repo", 3)
    assert items[0]["key"] == "bb:general:1"
    assert items[1]["key"] == "bb:inline:2"


@patch("pr_comments.providers.bitbucket._bitbucket_request")
def test_bitbucket_api_error(mock_req: MagicMock) -> None:
    mock_req.return_value = (401, json.dumps({"error": {"message": "Unauthorized"}}))
    with pytest.raises(PrCommentsError, match="Unauthorized"):
        list_paginated_bitbucket_items("u", "bad", "https://api.bitbucket.org/start")
