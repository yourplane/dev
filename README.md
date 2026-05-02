# dev

CLI for managing AI developer tasks with Cursor agent integration. Tasks live under `~/tasks` (or `DEV_TASKS_DIR`).

This repo is a uv workspace: **dev-sdk** (shared logic), **dev-cli** (the `dev` command), and **dev-server** (FastAPI task API). The repo root is not an installable package. **dev-frontend** is a separate Node (Vite + React) app under `dev-frontend/` for the web UI; see `dev-frontend/README.md` for run instructions.

## Install

From the repo root:

**With uv (recommended):**

```bash
cd /path/to/dev
uv sync
.venv/bin/dev --help
```

**With pip:**

```bash
cd /path/to/dev
pip install -e dev-sdk -e dev-cli
dev --help
```

For testing (from repo root; use the uv venv so workspace packages are available):

```bash
uv sync --extra dev
.venv/bin/python -m pytest dev-sdk/tests -v
.venv/bin/python -m pytest dev-cli/tests -v
```

## Usage

Create a new task (creates a subdirectory, task file, agent chat, launch script, and clones the repo):

```bash
dev create "My task title" --repo https://github.com/user/repo.git --description "Implement feature X and add tests."
```

Options:

- `--repo` / `-r`: Git repository URL or a shorthand (e.g. `desk`) from your config (required).
- `--description` / `-d`: Task description/goal (required).
- `--tasks-dir`: Override tasks root (default: `~/tasks`). Can set `DEV_TASKS_DIR` instead.

**Repo shorthand:** You can use a short name instead of a full URL if you add it to the config:

```bash
dev repos add desk https://github.com/maxrademacher/desk.git
dev create "My task" --repo desk --description "Do the thing."
```

Config is stored in `~/.config/dev/repos.json`. List shorthands with `dev repos list`.

The command:

1. Creates `~/tasks/<slug>/` from the task title.
2. Writes `task.md` with the title and description.
3. Runs `cursor agent create-chat`, saves the chat ID, and writes `launch-agent.sh` to resume that chat.
4. Clones the repo into `~/tasks/<slug>/`; the subdirectory name is the repo name from the URL.

Resume the agent for a task:

```bash
~/tasks/<task-slug>/launch-agent.sh
```

List tasks (excludes `~/tasks/.archive` and hidden dirs):

```bash
dev list
```

Archive a task (moves it to `~/tasks/.archive` with a unique name: `<task-name>-<date>-<random>`, e.g. `my-task-feb-27-a1b2c3`):

```bash
dev archive <task-name>
```

## Web UI (dev-frontend)

To use the web UI for listing, creating, and archiving tasks:

1. Start dev-server: `uv run --project dev-server uvicorn dev_server.main:app --reload --host 127.0.0.1`
2. From `dev-frontend/`: `npm install && npm run dev`
3. Open http://localhost:5173 (or the URL printed by Vite).

See `dev-frontend/README.md` for details.

### Daemon (background stacks)

Start backend + frontend in the **background** (multiple instances supported; each gets unique backend and frontend ports):

```bash
cd /path/to/dev   # workspace root with dev-server and dev-frontend

uv sync
.venv/bin/dev daemon start
.venv/bin/dev daemon list
.venv/bin/dev daemon stop --repo-root .
```

Use `--backend-port` / `--frontend-port` to pin ports. Auto-selected ports avoid common dev ranges (see `dev_sdk.daemon`). `dev daemon list` shows the `dev` CLI path, `uv`, `npm`, and URLs.

See `dev-daemon/README.md` for systemd-style **`ExecStart`** notes (replacing the removed shell scripts).

## Logs (troubleshooting)

- **dev-sdk:** Debug logs from the `dev_sdk` logger go to `~/.local/share/dev/sdk-debug.log` by default. Set `DEV_SDK_LOG` to use a different path. See [dev-sdk/README.md](dev-sdk/README.md#debugging).
- **dev-server:** Uvicorn/FastAPI write to **stdout/stderr** of the process (the terminal where you start the server; see [Web UI (dev-frontend)](#web-ui-dev-frontend)). With **`dev daemon start`**, logs are under `~/.local/share/dev/daemon/logs/<instance-id>/` (override via `XDG_DATA_HOME`). For a custom systemd unit, use `journalctl --user -u <unit> -f`.

## Development

Run tests:

```bash
tox
```

Test a single Python version:

```bash
tox -e py311
```
