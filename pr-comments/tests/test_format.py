"""Tests for Markdown formatting."""

from pr_comments.format import format_comments_markdown
from pr_comments.models import CommentItem


def test_format_github_review_comment() -> None:
    item = CommentItem(
        kind="review",
        key="review:10",
        payload={
            "user": {"login": "alice"},
            "created_at": "2024-01-01T00:00:00Z",
            "html_url": "https://github.com/a/b/pull/1#issuecomment",
            "path": "src/main.py",
            "line": 12,
            "body": "Please fix this",
        },
    )
    md = format_comments_markdown("https://github.com/a/b/pull/1", 1, [item])
    assert "review:10" in md
    assert "alice" in md
    assert "Please fix this" in md
    assert "[//]: # (pr_comment_key: review:10)" in md


def test_format_bitbucket_inline_comment() -> None:
    item = CommentItem(
        kind="inline",
        key="bb:inline:5",
        payload={
            "user": {"display_name": "Bob"},
            "created_on": "2024-02-01T12:00:00+00:00",
            "content": {"raw": "nit"},
            "inline": {"path": "README.md", "to": 3},
            "links": {"html": {"href": "https://bitbucket.org/w/r/pull-requests/1#comment-5"}},
        },
    )
    md = format_comments_markdown(
        "https://bitbucket.org/w/r/pull-requests/1", 1, [item]
    )
    assert "bb:inline:5" in md
    assert "Bob" in md
    assert "README.md" in md
