"""Tests for PR comment key deduplication."""

from pathlib import Path

from pr_comments.dedupe import collect_existing_keys, workspace_has_pulled_comments


def test_collect_keys_from_markdown_reference(tmp_path: Path) -> None:
    (tmp_path / "001-pr-comments.md").write_text(
        "body\n[//]: # (pr_comment_key: review:1)\n",
        encoding="utf-8",
    )
    (tmp_path / "002-agent-pr-comments.md").write_text(
        "legacy\n<!-- pr_comment_key: issue:2 -->\n",
        encoding="utf-8",
    )
    keys = collect_existing_keys(tmp_path)
    assert keys == {"review:1", "issue:2"}


def test_collect_bitbucket_keys(tmp_path: Path) -> None:
    (tmp_path / "001-pr-comments.md").write_text(
        "[//]: # (pr_comment_key: bb:inline:99)\n",
        encoding="utf-8",
    )
    assert "bb:inline:99" in collect_existing_keys(tmp_path)


def test_workspace_has_pulled_comments(tmp_path: Path) -> None:
    assert not workspace_has_pulled_comments(tmp_path)
    (tmp_path / "001-pr-comments.md").write_text("x", encoding="utf-8")
    assert workspace_has_pulled_comments(tmp_path)
