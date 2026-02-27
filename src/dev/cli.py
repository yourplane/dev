"""Dev CLI entry point."""

import click

from dev.commands import archive_task, list_tasks, start_task


@click.group()
@click.version_option(version="0.1.0")
def main() -> None:
    """Dev CLI - manage AI developer tasks with Cursor agent integration."""
    pass


main.add_command(start_task)
main.add_command(list_tasks)
main.add_command(archive_task)
