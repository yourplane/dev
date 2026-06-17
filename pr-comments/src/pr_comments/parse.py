import re

from pr_comments.errors import PrCommentsError
from pr_comments.models import WorkspaceConfig

_GITHUB_PR = re.compile(
    r"^https?://github\.com/([^/]+)/([^/]+)/pull/(\d+)/?$",
    re.IGNORECASE,
)
_BITBUCKET_PR = re.compile(
    r"^https?://bitbucket\.org/([^/]+)/([^/]+)/pull-requests/(\d+)/?$",
    re.IGNORECASE,
)


def parse_pr_url(pr_url: str) -> WorkspaceConfig:
    url = pr_url.strip()
    m = _GITHUB_PR.match(url)
    if m:
        owner, repo, num = m.group(1), m.group(2), int(m.group(3))
        if repo.endswith(".git"):
            repo = repo[:-4]
        return WorkspaceConfig(
            pr_url=url,
            provider="github",
            owner=owner,
            repo=repo,
            pr_id=num,
        )
    m = _BITBUCKET_PR.match(url)
    if m:
        workspace, repo_slug, pr_id = m.group(1), m.group(2), int(m.group(3))
        return WorkspaceConfig(
            pr_url=url,
            provider="bitbucket",
            owner=workspace,
            repo=repo_slug,
            pr_id=pr_id,
        )
    raise PrCommentsError(
        "Unsupported PR URL. Use GitHub (https://github.com/owner/repo/pull/N) "
        "or Bitbucket Cloud (https://bitbucket.org/workspace/repo/pull-requests/N)."
    )
