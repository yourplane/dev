"""`dev daemon` — background dev-server + dev-frontend instances."""

from __future__ import annotations

import json
from pathlib import Path

import click

from dev_sdk.daemon import (
    DaemonError,
    human_status,
    iter_daemon_records,
    list_daemons_json,
    normalize_daemon_id,
    start_daemon,
    stop_daemon,
)


@click.group("daemon")
def daemon_group() -> None:
    """Start, stop, and list background dev-server + dev-frontend stacks."""


@daemon_group.command("start")
@click.option(
    "--repo-root",
    type=click.Path(file_okay=False, dir_okay=True, path_type=Path),
    default=None,
    help="Dev workspace root (contains dev-server and dev-frontend). Default: current directory.",
)
@click.option(
    "--backend-port",
    type=int,
    default=None,
    help="Backend port (default: auto-selected uncommon port).",
)
@click.option(
    "--frontend-port",
    type=int,
    default=None,
    help="Frontend port (default: auto from SDK range).",
)
@click.option(
    "--tasks-dir",
    type=click.Path(file_okay=False, dir_okay=True, path_type=Path),
    default=None,
    help="Tasks root for the API (sets DEV_TASKS_DIR). Default: server default (~tasks).",
)
def daemon_start(
    repo_root: Path | None,
    backend_port: int | None,
    frontend_port: int | None,
    tasks_dir: Path | None,
) -> None:
    """Start backend and frontend in the background and exit immediately."""
    try:
        rec = start_daemon(
            repo_root,
            backend_port=backend_port,
            frontend_port=frontend_port,
            tasks_dir=tasks_dir,
        )
    except DaemonError as e:
        click.echo(str(e), err=True)
        raise SystemExit(1) from e

    click.echo(f"Daemon {rec.id}")
    click.echo(f"  Repo:      {rec.repo_root}")
    click.echo(f"  Frontend:  http://127.0.0.1:{rec.frontend_port}/")
    click.echo(f"  Backend:   http://127.0.0.1:{rec.backend_port}/")
    click.echo(f"  Dev CLI:   {rec.dev_cli_path}")
    click.echo(f"  Logs:      {rec.backend_log} , {rec.frontend_log}")


@daemon_group.command("stop")
@click.option("--id", "daemon_id", type=str, default=None, help="Daemon instance UUID.")
@click.option(
    "--repo-root",
    type=click.Path(file_okay=False, dir_okay=True, path_type=Path),
    default=None,
    help="Stop the most recently started daemon for this repo root.",
)
@click.option("--all", "stop_all", is_flag=True, help="Stop every tracked daemon and remove state files.")
def daemon_stop(daemon_id: str | None, repo_root: Path | None, stop_all: bool) -> None:
    """Stop a daemon and remove its state file."""
    flags = sum(bool(x) for x in (daemon_id, repo_root is not None, stop_all))
    if flags != 1:
        click.echo("Specify exactly one of --id, --repo-root, or --all.", err=True)
        raise SystemExit(1)
    try:
        if daemon_id:
            nid = normalize_daemon_id(daemon_id)
            stopped = stop_daemon(nid)
        elif stop_all:
            stopped = stop_daemon(stop_all=True)
        else:
            stopped = stop_daemon(repo_root=repo_root)
    except DaemonError as e:
        click.echo(str(e), err=True)
        raise SystemExit(1) from e

    for i in stopped:
        click.echo(f"Stopped {i}")


@daemon_group.command("list")
@click.option("--json", "as_json", is_flag=True, help="Print machine-readable JSON.")
def daemon_list(as_json: bool) -> None:
    """List known daemon instances and whether their processes are running."""
    if as_json:
        click.echo(json.dumps(list_daemons_json(), indent=2))
        return

    rows = iter_daemon_records()
    if not rows:
        click.echo("No daemon instances.")
        return

    for st in rows:
        r = st.record
        click.echo(f"{r.id}")
        click.echo(f"  status:    {human_status(st)}")
        click.echo(f"  repo:      {r.repo_root}")
        click.echo(f"  frontend:  http://127.0.0.1:{r.frontend_port}/")
        click.echo(f"  backend:   http://127.0.0.1:{r.backend_port}/")
        click.echo(f"  dev CLI:   {r.dev_cli_path}")
        click.echo(f"  uv:        {r.uv_path}")
        click.echo(f"  npm:       {r.npm_path}")
        click.echo("")
