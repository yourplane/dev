"""Commands to maintain repo shorthand config (thin wrapper over dev_sdk)."""

import click

from dev_sdk.repo_config import load_repos, save_repos


@click.group("repos")
def repos_group() -> None:
    """Manage repo shorthand -> URL mapping (used by dev create --repo <shorthand>)."""
    pass


@repos_group.command("list")
def repos_list() -> None:
    """List configured repo shorthands and their URLs."""
    repos = load_repos()
    if not repos:
        click.echo("No repo shorthands configured. Add with: dev repos add <shorthand> <url>")
        return
    for name, url in sorted(repos.items()):
        click.echo(f"  {name} -> {url}")


@repos_group.command("add")
@click.argument("shorthand", type=str)
@click.argument("url", type=str)
def repos_add(shorthand: str, url: str) -> None:
    """Add a shorthand for a repo URL (e.g. dev repos add desk https://github.com/maxrademacher/desk.git)."""
    repos = load_repos()
    repos[shorthand] = url
    save_repos(repos)
    click.echo(f"Added {shorthand} -> {url}")
