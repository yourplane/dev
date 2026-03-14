"""Dev CLI entry point."""

import logging
import os
from pathlib import Path

import click

from dev.commands import (
    activate_path,
    archive_task,
    comms_group,
    create_pr,
    implement_cmd,
    launch_interact,
    list_tasks,
    plan_implement_group,
    plan_test_cmd,
    repos_group,
    start_task,
    test_cmd,
)

DEFAULT_SDK_LOG = Path.home() / ".config" / "dev" / "sdk-debug.log"


def _setup_sdk_debug_log() -> Path:
    """Enable dev_sdk logger at DEBUG and add a file handler. Returns the log file path."""
    log_path = Path(os.environ.get("DEV_SDK_LOG", str(DEFAULT_SDK_LOG)))
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("dev_sdk")
    logger.setLevel(logging.DEBUG)
    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    return log_path


@click.group()
@click.option(
    "--debug",
    is_flag=True,
    envvar="DEV_DEBUG",
    help="Enable SDK debug logging to a file (default: ~/.config/dev/sdk-debug.log).",
)
@click.version_option(version="0.1.0")
@click.pass_context
def main(ctx: click.Context, debug: bool) -> None:
    """Dev CLI - manage AI developer tasks with Cursor agent integration."""
    if debug:
        log_path = _setup_sdk_debug_log()
        click.echo(f"SDK debug log: {log_path}", err=True)


main.add_command(start_task)
main.add_command(launch_interact)
main.add_command(list_tasks)
main.add_command(archive_task)
main.add_command(activate_path)
main.add_command(plan_implement_group)
main.add_command(plan_test_cmd)
main.add_command(implement_cmd)
main.add_command(test_cmd)
main.add_command(create_pr)
main.add_command(comms_group)
main.add_command(repos_group)
