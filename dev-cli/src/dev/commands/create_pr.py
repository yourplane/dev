"""Create a pull request to main from the current feature branch."""

from pathlib import Path

import click

from dev_sdk.create_pr import CreatePRError, create_pull_request


def _resolve_task_root(task_path: Path | None) -> Path:
    """Resolve task root: given path if provided, else current working directory."""
    return (task_path or Path.cwd()).resolve()


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
    Token: resolves the AWS secret name for this repo's GitHub owner from
    ~/.config/git-auth/bots.json, fetches GitHub App credentials from AWS Secrets
    Manager, and obtains an installation token with pull_requests write.
    """
    task_root = _resolve_task_root(task_path)
    try:
        pr_url = create_pull_request(task_root, allow_dirty=allow_dirty)
    except CreatePRError as e:
        click.echo(str(e), err=True)
        raise SystemExit(1)
    click.echo(pr_url)
    # Also print short form for CLI users
    if "/pull/" in pr_url:
        num = pr_url.split("/pull/")[-1].split("/")[0].split("?")[0]
        click.echo(f"#{num}: {task_root.name}")
