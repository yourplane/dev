"""Create a pull request (thin CLI wrapper over dev_sdk)."""

import json
from pathlib import Path

import click

from dev_sdk.create_pr import (
    CreatePrError,
    create_pull_request,
    get_github_token_from_aws,
    github_request,
)


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
    task_root = (task_path or Path.cwd()).resolve()

    def get_token() -> str:
        token = get_github_token_from_aws()
        if debug:
            click.echo(f"Token: obtained (length={len(token)}, prefix={token[:4]!r}...)", err=True)
        return token

    try:
        pr = create_pull_request(
            task_root,
            allow_dirty=allow_dirty,
            get_token=get_token,
        )
    except CreatePrError as e:
        click.echo(str(e), err=True)
        raise SystemExit(1)
    except ValueError as e:
        click.echo(str(e), err=True)
        raise SystemExit(1)

    click.echo(pr["html_url"])
    click.echo(f"#{pr['number']}: {pr['title']}")
