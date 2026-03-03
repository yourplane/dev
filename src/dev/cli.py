"""Dev CLI entry point."""

import click

from dev.commands import (
    activate_path,
    archive_task,
    comms_group,
    launch_interact,
    list_tasks,
    plan_group,
    repos_group,
    start_task,
)


@click.group()
@click.version_option(version="0.1.0")
def main() -> None:
    """Dev CLI - manage AI developer tasks with Cursor agent integration."""
    pass


main.add_command(start_task)
main.add_command(launch_interact)
main.add_command(list_tasks)
main.add_command(archive_task)
main.add_command(activate_path)
main.add_command(plan_group)
main.add_command(comms_group)
main.add_command(repos_group)
