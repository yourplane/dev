"""CLI for pulling PR comments."""

from pathlib import Path

import click

from pr_comments.errors import PrCommentsError
from pr_comments.pull import init_workspace, pull_comments


@click.group()
def main() -> None:
    """Pull PR review comments from GitHub or Bitbucket Cloud."""


@main.command("init")
@click.argument("pr_url")
@click.option(
    "--work-dir",
    type=click.Path(path_type=Path),
    default=".",
    help="Workspace directory (default: current directory).",
)
def init_cmd(pr_url: str, work_dir: Path) -> None:
    """Save a PR URL to the workspace for incremental comment pulls."""
    try:
        cfg = init_workspace(work_dir.resolve(), pr_url)
    except PrCommentsError as e:
        raise click.ClickException(str(e)) from e
    click.echo(f"Initialized workspace for {cfg.provider} PR: {cfg.pr_url}")


@main.command("pull")
@click.option(
    "--work-dir",
    type=click.Path(path_type=Path),
    default=".",
    help="Workspace directory (default: current directory).",
)
@click.option("--token", default=None, help="API token (GitHub PAT or Bitbucket app password).")
@click.option(
    "--username",
    default=None,
    help="Bitbucket username (or set BITBUCKET_USERNAME).",
)
def pull_cmd(work_dir: Path, token: str | None, username: str | None) -> None:
    """Fetch new PR comments and save them to the workspace."""
    try:
        result = pull_comments(work_dir.resolve(), token=token, username=username)
    except PrCommentsError as e:
        raise click.ClickException(str(e)) from e
    if result.new_count == 0:
        click.echo("No new PR comments.")
        return
    click.echo(
        f"{result.new_count} new comment(s) → {result.output_filename}"
    )


if __name__ == "__main__":
    main()
