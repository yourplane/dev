from dataclasses import dataclass
from typing import Any, Literal


Provider = Literal["github", "bitbucket"]


@dataclass(frozen=True)
class WorkspaceConfig:
    pr_url: str
    provider: Provider
    # GitHub: owner, repo, pr_number
    # Bitbucket: workspace, repo_slug, pr_id
    owner: str
    repo: str
    pr_id: int


@dataclass(frozen=True)
class CommentItem:
    kind: str
    key: str
    payload: dict[str, Any]
