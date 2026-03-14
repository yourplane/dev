"""Dev CLI entry point."""

import logging
import os
from pathlib import Path

import click

from dev.commands import (
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

DEFAULT_SDK_LOG = Path.home() / ".local" / "share" / "dev" / "sdk-debug.log"


def _setup_sdk_debug_log() -> None:
    """Enable dev_sdk logger at DEBUG and add a file handler (once per process)."""
    logger = logging.getLogger("dev_sdk")
    if logger.handlers:
        return
    log_path = Path(os.environ.get("DEV_SDK_LOG", str(DEFAULT_SDK_LOG)))
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logger.setLevel(logging.DEBUG)
    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)


@click.group()
@click.version_option(version="0.1.0")
def main() -> None:
    """Dev CLI - manage AI developer tasks with Cursor agent integration."""
    _setup_sdk_debug_log()


main.add_command(start_task)
main.add_command(launch_interact)
main.add_command(list_tasks)
main.add_command(archive_task)
main.add_command(plan_implement_group)
main.add_command(plan_test_cmd)
main.add_command(implement_cmd)
main.add_command(test_cmd)
main.add_command(create_pr)
main.add_command(comms_group)
main.add_command(repos_group)
