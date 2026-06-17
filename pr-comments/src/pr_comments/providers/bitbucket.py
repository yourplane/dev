import base64
import json
import urllib.error
import urllib.request

from pr_comments.errors import PrCommentsError


def _bitbucket_request(
    username: str, app_password: str, method: str, url: str
) -> tuple[int, str]:
    creds = base64.b64encode(f"{username}:{app_password}".encode()).decode("ascii")
    headers = {
        "Authorization": f"Basic {creds}",
        "Accept": "application/json",
    }
    req = urllib.request.Request(url, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as e:
        body = e.read().decode() if e.fp else ""
        return e.code, body


def list_paginated_bitbucket_items(
    username: str, app_password: str, url: str
) -> list[dict]:
    all_items: list[dict] = []
    next_url: str | None = url
    while next_url:
        status, body = _bitbucket_request(username, app_password, "GET", next_url)
        if status != 200:
            try:
                data = json.loads(body)
                msg = data.get("error", {}).get("message", body)
            except (ValueError, TypeError, AttributeError):
                msg = body or f"HTTP {status}"
            raise PrCommentsError(msg)
        payload = json.loads(body)
        if not isinstance(payload, dict):
            raise PrCommentsError("Bitbucket API error: expected paginated object")
        values = payload.get("values")
        if isinstance(values, list):
            all_items.extend(v for v in values if isinstance(v, dict))
        next_link = payload.get("next")
        next_url = next_link if isinstance(next_link, str) and next_link else None
    return all_items


def fetch_bitbucket_comments(
    username: str,
    app_password: str,
    workspace: str,
    repo_slug: str,
    pr_id: int,
) -> list[dict]:
    url = (
        f"https://api.bitbucket.org/2.0/repositories/{workspace}/{repo_slug}"
        f"/pullrequests/{pr_id}/comments?pagelen=100"
    )
    items: list[dict] = []
    for payload in list_paginated_bitbucket_items(username, app_password, url):
        cid = payload.get("id")
        if not isinstance(cid, int):
            continue
        inline = payload.get("inline")
        if isinstance(inline, dict) and inline:
            kind = "inline"
            key = f"bb:inline:{cid}"
        else:
            kind = "general"
            key = f"bb:general:{cid}"
        items.append({"kind": kind, "key": key, "payload": payload})
    return items
