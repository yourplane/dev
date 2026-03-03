"""Create a pull request to main from the current feature branch."""

import json
import re
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

import click

from dev.comms import comms_dir


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


def _ensure_pushed_and_in_sync(repo_root: Path) -> None:
    """Ensure current branch has upstream and HEAD == @{u}."""
    try:
        _git_output(repo_root, "rev-parse", "--abbrev-ref", "@{u}")
    except subprocess.CalledProcessError:
        click.echo(
            "Branch has no upstream. Push the branch and set upstream, then try again.",
            err=True,
        )
        raise SystemExit(1)
    local = _git_output(repo_root, "rev-parse", "HEAD")
    remote = _git_output(repo_root, "rev-parse", "@{u}")
    if local != remote:
        click.echo(
            "Branch is not in sync with remote; push and try again.",
            err=True,
        )
        raise SystemExit(1)


def _get_github_token() -> str:
    """Obtain GitHub token via git credential fill (same as git uses)."""
    proc = subprocess.run(
        ["git", "credential", "fill"],
        input="protocol=https\nhost=github.com\n",
        capture_output=True,
        text=True,
        timeout=10,
    )
    if proc.returncode != 0:
        click.echo(
            "Could not get GitHub token; ensure git credential helper is configured for github.com.",
            err=True,
        )
        raise SystemExit(1)
    for line in proc.stdout.splitlines():
        if line.startswith("password="):
            return line.removeprefix("password=").strip()
    click.echo(
        "Could not get GitHub token; credential helper did not return a password.",
        err=True,
        )
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


def _create_pull_request(
    token: str, owner: str, repo: str, head: str, title: str, body: str
) -> dict:
    """POST to GitHub API; return response JSON."""
    url = f"https://api.github.com/repos/{owner}/{repo}/pulls"
    data = json.dumps({
        "base": "main",
        "head": head,
        "title": title,
        "body": body or None,
    }).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode())


@click.command("create-pr")
@click.option(
    "--task",
    "-t",
    "task_path",
    type=click.Path(path_type=Path),
    default=None,
    help="Path to task root. If not set, use current working directory.",
)
def create_pr(task_path: Path | None) -> None:
    """Create a pull request to main from the current feature branch.

    Run from the task root (or use --task). Requires: current branch is not main,
    working tree is clean, and the branch is pushed and in sync with the remote.
    PR title is the task name; PR body is built from commit messages not on main.
    Uses the same GitHub token as git (git credential helper for github.com).
    """
    task_root = _resolve_task_root(task_path)
    _validate_task_root(task_root)
    repo_root = _find_single_git_repo_under(task_root)

    _ensure_not_main(repo_root)
    _ensure_clean_tree(repo_root)
    _ensure_pushed_and_in_sync(repo_root)

    token = _get_github_token()
    remote_url = _git_output(repo_root, "remote", "get-url", "origin")
    try:
        owner, repo = _parse_owner_repo(remote_url)
    except ValueError as e:
        click.echo(str(e), err=True)
        raise SystemExit(1)

    head = _current_branch(repo_root)
    title = task_root.name
    body = _pr_body_from_commits(repo_root)

    try:
        pr = _create_pull_request(token, owner, repo, head, title, body)
    except urllib.error.HTTPError as e:
        msg = e.read().decode() if e.fp else str(e)
        click.echo(f"GitHub API error: {msg}", err=True)
        raise SystemExit(1)
    except OSError as e:
        click.echo(f"Request failed: {e}", err=True)
        raise SystemExit(1)

    click.echo(pr["html_url"])
    click.echo(f"#{pr['number']}: {pr['title']}")
