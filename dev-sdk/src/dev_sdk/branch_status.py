"""Ahead/behind branch status via GitHub Compare API."""

from __future__ import annotations

import json
import urllib.parse
from pathlib import Path
from typing import TypedDict

from dev_sdk.bots_config import secret_name_for_owner
from dev_sdk.create_pr import (
    CreatePRError,
    _current_branch,
    _find_single_git_repo_under,
    _get_github_token,
    _get_github_token_boto,
    _github_request,
    _owner_repo_from_repo_root,
    _secret_name_for_github_owner,
    _validate_task_root,
)


class BranchStatus(TypedDict):
    ahead: int
    behind: int


def _compare_branches_api(
    token: str, owner: str, repo: str, base: str, head: str
) -> tuple[int, str]:
    base_enc = urllib.parse.quote(base, safe="")
    head_enc = urllib.parse.quote(head, safe="")
    url = f"https://api.github.com/repos/{owner}/{repo}/compare/{base_enc}...{head_enc}"
    return _github_request(token, "GET", url)


def _parse_branch_status(status_code: int, body: str) -> BranchStatus | None:
    if status_code != 200:
        return None
    try:
        data = json.loads(body)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    try:
        return BranchStatus(
            ahead=int(data.get("ahead_by", 0)),
            behind=int(data.get("behind_by", 0)),
        )
    except (TypeError, ValueError):
        return None


def get_branch_status_from_metadata(
    *,
    owner: str,
    repo: str,
    branch: str,
    bots: list[dict[str, str]],
    base: str = "main",
    get_token=None,
) -> BranchStatus | None:
    """Compare branch to base on GitHub. Returns None when compare is unavailable."""
    if branch == base:
        return BranchStatus(ahead=0, behind=0)
    try:
        secret_name = secret_name_for_owner(bots, owner)
    except ValueError:
        return None
    token_fn = get_token or _get_github_token_boto
    try:
        token = token_fn(secret_name)
    except CreatePRError:
        return None
    status_code, resp_body = _compare_branches_api(token, owner, repo, base, branch)
    return _parse_branch_status(status_code, resp_body)


def get_branch_status_from_task(task_root: Path, *, base: str = "main") -> BranchStatus | None:
    """Compare the task clone's current branch to base on GitHub. Returns None when unavailable."""
    task_root = task_root.resolve()
    try:
        _validate_task_root(task_root)
        repo_root = _find_single_git_repo_under(task_root)
        branch = _current_branch(repo_root)
        if branch == base:
            return BranchStatus(ahead=0, behind=0)
        owner, repo = _owner_repo_from_repo_root(repo_root)
        secret_name = _secret_name_for_github_owner(owner)
        token = _get_github_token(secret_name)
    except CreatePRError:
        return None
    status_code, resp_body = _compare_branches_api(token, owner, repo, base, branch)
    return _parse_branch_status(status_code, resp_body)
