"""Create a pull request to main from the current feature branch."""

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

import click

from dev_sdk.comms import comms_dir


def _resolve_task_root(task_path: Path | None) -> Path:
    """Resolve task root: given path if provided, else current working directory."""
    return (task_path or Path.cwd()).resolve()


def _validate_task_root(task_root: Path) -> None:
    """Ensure directory is a task root (has comms/). Exit with error if not."""
    if not task_root.exists() or not task_root.is_dir():
        click.echo(f"Task directory not found: {task_root}", err=True)
        raise SystemExit(1)
    cdir = comms_dir(task_root)
    if not cdir.exists() or not cdir.is_dir():
        click.echo(
            f"Not a task root (no comms directory): {task_root}. "
            "Run from a task root or use --task.",
            err=True,
        )
        raise SystemExit(1)


def _find_single_git_repo_under(task_root: Path) -> Path:
    """Find the single git repository under task root (direct subdirs). Error if 0 or 2+."""
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
        click.echo(
            "No git repository found under task root. "
            "Ensure the cloned repo is a direct subdirectory.",
            err=True,
        )
        raise SystemExit(1)
    if len(repo_roots) > 1:
        click.echo(
            "Multiple git repositories found under task root. "
            "Run from a task with a single cloned repo.",
            err=True,
        )
        raise SystemExit(1)
    return repo_roots.pop()


def _git_output(repo_root: Path, *args: str) -> str:
    """Run git in repo_root and return stripped stdout. Raises on failure."""
    result = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _current_branch(repo_root: Path) -> str:
    return _git_output(repo_root, "rev-parse", "--abbrev-ref", "HEAD")


def _ensure_not_main(repo_root: Path) -> None:
    branch = _current_branch(repo_root)
    if branch == "main":
        click.echo("Create PR from a feature branch, not main.", err=True)
        raise SystemExit(1)


def _ensure_clean_tree(repo_root: Path) -> None:
    out = _git_output(repo_root, "status", "--porcelain")
    if out:
        click.echo(
            "Uncommitted changes; commit or stash before creating a PR.",
            err=True,
        )
        raise SystemExit(1)


def _ensure_branch_pushed_and_tracking(repo_root: Path) -> None:
    """Push current branch to origin and set upstream if needed; exit on push failure."""
    branch = _current_branch(repo_root)
    try:
        _git_output(repo_root, "rev-parse", "--abbrev-ref", "@{u}")
        has_upstream = True
    except subprocess.CalledProcessError:
        has_upstream = False

    if not has_upstream:
        click.echo(f"Pushing branch {branch!r} and setting upstream to origin/{branch}.")
        proc = subprocess.run(
            ["git", "push", "-u", "origin", branch],
            cwd=repo_root,
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            click.echo(
                f"Failed to push branch: {proc.stderr or proc.stdout or 'unknown error'}",
                err=True,
            )
            raise SystemExit(1)
        return

    local = _git_output(repo_root, "rev-parse", "HEAD")
    remote = _git_output(repo_root, "rev-parse", "@{u}")
    if local != remote:
        click.echo(f"Pushing branch {branch!r} to origin.")
        proc = subprocess.run(
            ["git", "push"],
            cwd=repo_root,
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            click.echo(
                f"Failed to push: {proc.stderr or proc.stdout or 'unknown error'}",
                err=True,
            )
            raise SystemExit(1)


def _base64url_encode(data: bytes) -> str:
    """Base64url encode without padding."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _get_github_app_installation_token(
    app_id: str, installation_id: str, private_key_pem: str
) -> str:
    """Obtain an installation access token with pull_requests write using JWT."""
    now = int(time.time())
    payload = {"iat": now, "exp": now + 600, "iss": app_id}
    header_b64 = _base64url_encode(b'{"alg":"RS256","typ":"JWT"}')
    payload_b64 = _base64url_encode(json.dumps(payload, separators=(",", ":")).encode())
    signing_input = f"{header_b64}.{payload_b64}"

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".pem", delete=False
    ) as f:
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
        "permissions": {
            "pull_requests": "write",
            "contents": "read",  # required so API can read branch refs
        }
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


GITHUB_APP_SECRET_NAME = "github-desk"


def _get_github_token() -> str:
    """
    Obtain GitHub token from AWS Secrets Manager (GitHub App credentials).
    Fetches secret github-desk (app_id, installation_id, private_key), obtains
    an installation access token with pull_requests write.
    """
    aws_args = [
        "aws", "secretsmanager", "get-secret-value",
        "--secret-id", GITHUB_APP_SECRET_NAME,
    ]
    if os.environ.get("AWS_REGION"):
        aws_args.extend(["--region", os.environ["AWS_REGION"]])
    if os.environ.get("AWS_PROFILE"):
        aws_args.extend(["--profile", os.environ["AWS_PROFILE"]])

    proc = subprocess.run(aws_args, capture_output=True, text=True, timeout=30)
    if proc.returncode != 0:
        click.echo(
            f"Failed to get secret {GITHUB_APP_SECRET_NAME!r}: {proc.stderr or proc.stdout}",
            err=True,
        )
        raise SystemExit(1)

    try:
        secret_json = json.loads(proc.stdout)
        secret_str = secret_json.get("SecretString")
        if not secret_str:
            click.echo("Secret has no SecretString.", err=True)
            raise SystemExit(1)
        data = json.loads(secret_str) if isinstance(secret_str, str) else secret_str
    except (json.JSONDecodeError, TypeError) as e:
        click.echo(f"Invalid secret JSON: {e}", err=True)
        raise SystemExit(1)

    app_id = data.get("app_id") or data.get("appId")
    installation_id = data.get("installation_id") or data.get("installationId")
    key_content = data.get("private_key") or data.get("key")
    if not app_id or not installation_id or not key_content:
        click.echo(
            "Secret must contain app_id, installation_id, and private_key (or key).",
            err=True,
        )
        raise SystemExit(1)

    app_id = str(app_id).strip()
    installation_id = str(installation_id).strip()
    if isinstance(key_content, str):
        private_key_pem = key_content.strip()
    else:
        click.echo("Secret private_key must be a string.", err=True)
        raise SystemExit(1)

    try:
        return _get_github_app_installation_token(
            app_id, installation_id, private_key_pem
        )
    except (urllib.error.HTTPError, OSError, RuntimeError) as e:
        click.echo(f"Failed to get GitHub App installation token: {e}", err=True)
        raise SystemExit(1)


def _parse_owner_repo(remote_url: str) -> tuple[str, str]:
    """Parse origin URL into (owner, repo). Supports HTTPS and git@."""
    # https://github.com/owner/repo.git or https://github.com/owner/repo
    m = re.match(r"https?://(?:[^@/]+@)?github\.com[/:]([^/]+)/([^/]+?)(?:\.git)?/?$", remote_url)
    if m:
        return m.group(1), m.group(2)
    # git@github.com:owner/repo.git
    m = re.match(r"git@github\.com:([^/]+)/([^/]+?)(?:\.git)?/?$", remote_url)
    if m:
        return m.group(1), m.group(2)
    raise ValueError(f"Cannot parse GitHub owner/repo from remote URL: {remote_url!r}")


def _pr_body_from_commits(repo_root: Path) -> str:
    """Format commit messages for main..HEAD as PR body (subject + body per commit)."""
    base = "origin/main"
    try:
        _git_output(repo_root, "rev-parse", "origin/main")
    except subprocess.CalledProcessError:
        base = "main"
    result = subprocess.run(
        [
            "git", "log", f"{base}..HEAD", "--reverse",
            "--format=---%n%s%n%b",
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return ""
    raw = result.stdout.strip()
    if not raw:
        return ""
    # Normalize: ensure one newline after ---, trim each block
    parts = [p.strip() for p in raw.split("---") if p.strip()]
    return "\n\n---\n\n".join(parts)


def _github_request(
    token: str,
    method: str,
    url: str,
    data: bytes | None = None,
    debug: bool = False,
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


def _create_pull_request(
    token: str, owner: str, repo: str, head: str, title: str, body: str
) -> tuple[int, str]:
    """POST to GitHub API. Returns (status_code, response_body)."""
    url = f"https://api.github.com/repos/{owner}/{repo}/pulls"
    payload = {
        "base": "main",
        "head": head,
        "title": title,
        "body": body or None,
    }
    data = json.dumps(payload).encode("utf-8")
    return _github_request(token, "POST", url, data=data)


def _debug_echo(debug: bool, msg: str) -> None:
    if debug:
        click.echo(msg, err=True)


@click.command("create-pr")
@click.option(
    "--task",
    "-t",
    "task_path",
    type=click.Path(path_type=Path),
    default=None,
    help="Path to task root. If not set, use current working directory.",
)
@click.option(
    "--debug",
    is_flag=True,
    help="Print request details and full API responses to stderr (no token value).",
)
@click.option(
    "--allow-dirty",
    is_flag=True,
    help="Create PR even if there are uncommitted changes.",
)
def create_pr(
    task_path: Path | None, debug: bool = False, allow_dirty: bool = False
) -> None:
    """Create a pull request to main from the current feature branch.

    Run from the task root (or use --task). Requires: current branch is not main,
    and working tree is clean (unless --allow-dirty). If the branch has no
    upstream or is not in sync with the remote, runs git push (with -u when
    setting upstream) automatically. PR title is the task name; PR body is
    built from commit messages not on main.
    Token: fetches GitHub App credentials from AWS Secrets Manager (secret name
    github-desk) and obtains an installation token with pull_requests write.
    """
    task_root = _resolve_task_root(task_path)
    _validate_task_root(task_root)
    repo_root = _find_single_git_repo_under(task_root)

    _ensure_not_main(repo_root)
    if not allow_dirty:
        _ensure_clean_tree(repo_root)
    _ensure_branch_pushed_and_tracking(repo_root)

    token = _get_github_token()
    _debug_echo(debug, f"Token: obtained (length={len(token)}, prefix={token[:4]!r}...)")

    remote_url = _git_output(repo_root, "remote", "get-url", "origin")
    try:
        owner, repo = _parse_owner_repo(remote_url)
    except ValueError as e:
        click.echo(str(e), err=True)
        raise SystemExit(1)

    _debug_echo(debug, f"Repo: {owner}/{repo}")

    # Optional: verify token works for API (GET repo)
    if debug:
        url = f"https://api.github.com/repos/{owner}/{repo}"
        _debug_echo(debug, f"GET {url}")
        get_status, get_body = _github_request(token, "GET", url)
        _debug_echo(debug, f"GET response: {get_status}")
        if get_status != 200:
            _debug_echo(debug, f"GET body: {get_body}")

    head = _current_branch(repo_root)
    title = task_root.name
    body = _pr_body_from_commits(repo_root)

    _debug_echo(debug, f"POST /repos/{owner}/{repo}/pulls")
    _debug_echo(debug, f"  base=main head={head} title={title!r} body_len={len(body)}")

    try:
        status, resp_body = _create_pull_request(token, owner, repo, head, title, body)
    except OSError as e:
        click.echo(f"Request failed: {e}", err=True)
        raise SystemExit(1)

    if status != 201:
        _debug_echo(debug, f"Response status: {status}")
        _debug_echo(debug, f"Response body: {resp_body}")
        try:
            data = json.loads(resp_body)
            msg = data.get("message", resp_body)
            docs = data.get("documentation_url", "")
            errors = data.get("errors", [])
            click.echo(f"GitHub API error: {msg}", err=True)
            if docs:
                click.echo(f"Docs: {docs}", err=True)
            if errors:
                for err in errors:
                    if isinstance(err, dict):
                        click.echo(f"  - {err.get('message', err)}", err=True)
                    else:
                        click.echo(f"  - {err}", err=True)
            if status == 403 and "integration" in msg.lower():
                click.echo(
                    "The token may lack permission to create pull requests. "
                    "For a GitHub App, set Repository permissions → Pull requests → Read and write.",
                    err=True,
                )
        except (ValueError, TypeError):
            click.echo(f"GitHub API error: {resp_body}", err=True)
        raise SystemExit(1)

    pr = json.loads(resp_body)
    click.echo(pr["html_url"])
    click.echo(f"#{pr['number']}: {pr['title']}")
