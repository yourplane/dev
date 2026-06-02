import json
import urllib.error
import urllib.request

from pr_comments.errors import PrCommentsError


def github_request(token: str, method: str, url: str) -> tuple[int, str]:
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    req = urllib.request.Request(url, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as e:
        body = e.read().decode() if e.fp else ""
        return e.code, body


def list_paginated_github_items(token: str, url: str) -> list[dict]:
    all_items: list[dict] = []
    page = 1
    while True:
        sep = "&" if "?" in url else "?"
        page_url = f"{url}{sep}per_page=100&page={page}"
        status, body = github_request(token, "GET", page_url)
        if status != 200:
            try:
                data = json.loads(body)
                msg = data.get("message", body)
            except (ValueError, TypeError):
                msg = body or f"HTTP {status}"
            raise PrCommentsError(msg)
        payload = json.loads(body)
        if not isinstance(payload, list):
            raise PrCommentsError(
                f"GitHub API error: expected list, got {type(payload).__name__}"
            )
        if not payload:
            break
        all_items.extend(p for p in payload if isinstance(p, dict))
        page += 1
    return all_items


def fetch_github_comments(
    token: str, owner: str, repo: str, pr_number: int
) -> list[dict]:
    review_url = (
        f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}/comments"
    )
    issue_url = (
        f"https://api.github.com/repos/{owner}/{repo}/issues/{pr_number}/comments"
    )
    items: list[dict] = []
    for kind, url in (("review", review_url), ("issue", issue_url)):
        for payload in list_paginated_github_items(token, url):
            cid = payload.get("id")
            if not isinstance(cid, int):
                continue
            key = f"{kind}:{cid}"
            items.append({"kind": kind, "key": key, "payload": payload})
    return items
