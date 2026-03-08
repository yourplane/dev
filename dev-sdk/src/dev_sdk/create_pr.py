"""Create pull request: validate task, git helpers, GitHub API."""

from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

from dev_sdk.comms import comms_dir
from dev_sdk.exceptions import DevSdkError

GITHUB_APP_SECRET_NAME = "github-desk"


class CreatePrError(DevSdkError):
    """Base for create-pr errors."""


def validate_task_root(task_root: Path) -> None:
    """Ensure directory is a task root (has comms/). Raises CreatePrError if not."""
    if not task_root.exists() or not task_root.is_dir():
        raise CreatePrError(f"Task directory not found: {task_root}")
    cdir = comms_dir(task_root)
    if not cdir.exists() or not cdir.is_dir():
        raise CreatePrError(
            f"Not a task root (no comms directory): {task_root}. Run from a task root or use --task."
        )


def find_single_git_repo_under(task_root: Path) -> Path:
    """Find the single git repository under task root (direct subdirs). Raises CreatePrError if 0 or 2+."""
    repo_roots: set[Path] = set()
    for child in task_root.iterdir():
        if not child.is_dir() or child.name.startswith("."):
            continue
        try:
            r = subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                cwd=child,
                capture_output=True,
                text=True,
                check=True,
            )
            root = Path(r.stdout.strip()).resolve()
            repo_roots.add(root)
        except (subprocess.CalledProcessError, OSError):
            pass
    if len(repo_roots) == 0:
        raise CreatePrError(
            "No git repository found under task root. Ensure the cloned repo is a direct subdirectory."
        )
    if len(repo_roots) > 1:
        raise CreatePrError(
            "Multiple git repositories found under task root. Run from a task with a single cloned repo."
        )
    return repo_roots.pop()


def git_output(repo_root: Path, *args: str) -> str:
    """Run git in repo_root and return stripped stdout. Raises CalledProcessError on failure."""
    result = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def current_branch(repo_root: Path) -> str:
    return git_output(repo_root, "rev-parse", "--abbrev-ref", "HEAD")


def ensure_not_main(repo_root: Path) -> None:
    """Raises CreatePrError if current branch is main."""
    branch = current_branch(repo_root)
    if branch == "main":
        raise CreatePrError("Create PR from a feature branch, not main.")


def ensure_clean_tree(repo_root: Path) -> None:
    """Raises CreatePrError if there are uncommitted changes."""
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    out = (result.stdout or "").strip()
    if out:
        raise CreatePrError("Uncommitted changes; commit or stash before creating a PR.")


def ensure_branch_pushed_and_tracking(repo_root: Path) -> None:
    """Push current branch to origin and set upstream if needed. Raises CreatePrError on push failure."""
    branch = current_branch(repo_root)
    try:
        git_output(repo_root, "rev-parse", "--abbrev-ref", "@{u}")
        has_upstream = True
    except subprocess.CalledProcessError:
        has_upstream = False

    if not has_upstream:
        proc = subprocess.run(
            ["git", "push", "-u", "origin", branch],
            cwd=repo_root,
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            raise CreatePrError(
                f"Failed to push branch: {proc.stderr or proc.stdout or 'unknown error'}"
            )
        return

    local = git_output(repo_root, "rev-parse", "HEAD")
    remote = git_output(repo_root, "rev-parse", "@{u}")
    if local != remote:
        proc = subprocess.run(
            ["git", "push"],
            cwd=repo_root,
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            raise CreatePrError(
                f"Failed to push: {proc.stderr or proc.stdout or 'unknown error'}"
            )


def _base64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def get_github_app_installation_token(
    app_id: str, installation_id: str, private_key_pem: str
) -> str:
    """Obtain an installation access token with pull_requests write using JWT. Raises on failure."""
    now = int(time.time())
    payload = {"iat": now, "exp": now + 600, "iss": app_id}
    header_b64 = _base64url_encode(b'{"alg":"RS256","typ":"JWT"}')
    payload_b64 = _base64url_encode(json.dumps(payload, separators=(",", ":")).encode())
    signing_input = f"{header_b64}.{payload_b64}"

    with tempfile.NamedTemporaryFile(mode="w", suffix=".pem", delete=False) as f:
        f.write(private_key_pem)
        key_path = f.name
    try:
        proc = subprocess.run(
            ["openssl", "dgst", "-sha256", "-sign", key_path],
            input=signing_input.encode(),
            capture_output=True,
            timeout=10,
        )
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.decode() or "openssl sign failed")
        sig_b64 = _base64url_encode(proc.stdout)
    finally:
        os.unlink(key_path)

    jwt = f"{signing_input}.{sig_b64}"
    url = f"https://api.github.com/app/installations/{installation_id}/access_tokens"
    data = json.dumps({
        "permissions": {"pull_requests": "write", "contents": "read"}
    }).encode()
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {jwt}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        out = json.loads(resp.read().decode())
    token = out.get("token")
    if not token:
        raise RuntimeError("GitHub did not return an access token")
    return token


def get_github_token_from_aws(secret_name: str = GITHUB_APP_SECRET_NAME) -> str:
    """
    Obtain GitHub token from AWS Secrets Manager (GitHub App credentials).
    Raises CreatePrError or RuntimeError on failure.
    """
    aws_args = [
        "aws", "secretsmanager", "get-secret-value",
        "--secret-id", secret_name,
    ]
    if os.environ.get("AWS_REGION"):
        aws_args.extend(["--region", os.environ["AWS_REGION"]])
    if os.environ.get("AWS_PROFILE"):
        aws_args.extend(["--profile", os.environ["AWS_PROFILE"]])

    proc = subprocess.run(aws_args, capture_output=True, text=True, timeout=30)
    if proc.returncode != 0:
        raise CreatePrError(
            f"Failed to get secret {secret_name!r}: {proc.stderr or proc.stdout}"
        )

    try:
        secret_json = json.loads(proc.stdout)
        secret_str = secret_json.get("SecretString")
        if not secret_str:
            raise CreatePrError("Secret has no SecretString.")
        data = json.loads(secret_str) if isinstance(secret_str, str) else secret_str
    except (json.JSONDecodeError, TypeError) as e:
        raise CreatePrError(f"Invalid secret JSON: {e}")

    app_id = data.get("app_id") or data.get("appId")
    installation_id = data.get("installation_id") or data.get("installationId")
    key_content = data.get("private_key") or data.get("key")
    if not app_id or not installation_id or not key_content:
        raise CreatePrError(
            "Secret must contain app_id, installation_id, and private_key (or key)."
        )
    app_id = str(app_id).strip()
    installation_id = str(installation_id).strip()
    if not isinstance(key_content, str):
        raise CreatePrError("Secret private_key must be a string.")
    private_key_pem = key_content.strip()

    try:
        return get_github_app_installation_token(app_id, installation_id, private_key_pem)
    except (urllib.error.HTTPError, OSError, RuntimeError) as e:
        raise CreatePrError(f"Failed to get GitHub App installation token: {e}") from e


def parse_owner_repo(remote_url: str) -> tuple[str, str]:
    """Parse origin URL into (owner, repo). Supports HTTPS and git@. Raises ValueError if not GitHub."""
    m = re.match(r"https?://(?:[^@/]+@)?github\.com[/:]([^/]+)/([^/]+?)(?:\.git)?/?$", remote_url)
    if m:
        return m.group(1), m.group(2)
    m = re.match(r"git@github\.com:([^/]+)/([^/]+?)(?:\.git)?/?$", remote_url)
    if m:
        return m.group(1), m.group(2)
    raise ValueError(f"Cannot parse GitHub owner/repo from remote URL: {remote_url!r}")


def pr_body_from_commits(repo_root: Path) -> str:
    """Format commit messages for main..HEAD as PR body (subject + body per commit)."""
    base = "origin/main"
    try:
        git_output(repo_root, "rev-parse", "origin/main")
    except subprocess.CalledProcessError:
        base = "main"
    result = subprocess.run(
        ["git", "log", f"{base}..HEAD", "--reverse", "--format=---%n%s%n%b"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return ""
    raw = result.stdout.strip()
    if not raw:
        return ""
    parts = [p.strip() for p in raw.split("---") if p.strip()]
    return "\n\n---\n\n".join(parts)


def github_request(
    token: str,
    method: str,
    url: str,
    data: bytes | None = None,
) -> tuple[int, str]:
    """Send request to GitHub API. Returns (status_code, response_body)."""
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as e:
        body = e.read().decode() if e.fp else ""
        return e.code, body


def create_pull_request_api(
    token: str, owner: str, repo: str, head: str, title: str, body: str
) -> tuple[int, str]:
    """POST to GitHub API. Returns (status_code, response_body)."""
    url = f"https://api.github.com/repos/{owner}/{repo}/pulls"
    payload = {"base": "main", "head": head, "title": title, "body": body or None}
    data = json.dumps(payload).encode("utf-8")
    return github_request(token, "POST", url, data=data)


def create_pull_request(
    task_root: Path,
    *,
    allow_dirty: bool = False,
    get_token: Callable[[], str] | None = None,
) -> dict:
    """
    Validate task root, find repo, ensure branch/clean/push, create PR via GitHub API.
    Returns the PR payload dict (html_url, number, title, etc.).
    get_token: if provided, used to obtain the token; else get_github_token_from_aws() is used.
    Raises CreatePrError, ValueError, OSError on failure.
    """
    validate_task_root(task_root)
    repo_root = find_single_git_repo_under(task_root)
    ensure_not_main(repo_root)
    if not allow_dirty:
        ensure_clean_tree(repo_root)
    ensure_branch_pushed_and_tracking(repo_root)

    token = (get_token or get_github_token_from_aws)()

    remote_url = git_output(repo_root, "remote", "get-url", "origin")
    owner, repo = parse_owner_repo(remote_url)
    head = current_branch(repo_root)
    title = task_root.name
    body = pr_body_from_commits(repo_root)

    status, resp_body = create_pull_request_api(token, owner, repo, head, title, body)
    if status != 201:
        try:
            data = json.loads(resp_body)
            msg = data.get("message", resp_body)
            raise CreatePrError(f"GitHub API error: {msg}")
        except json.JSONDecodeError:
            raise CreatePrError(f"GitHub API error: {resp_body}")

    return json.loads(resp_body)
