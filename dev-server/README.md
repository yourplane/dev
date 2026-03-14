# dev-server

FastAPI server for dev task management: create, list, archive.

## Endpoints

- `GET /tasks` — list active task names
- `GET /repos` — list repo shorthands (from `~/.config/dev/repos.json`), for use by the frontend
- `POST /tasks` — create a task (body: `title`, `repo` URL or shorthand, optional `comment`, optional `task_name`)
- `POST /tasks/{task_name}/archive` — archive a task
- `GET /tasks/{task_name}/comms` — list comms filenames for a task (index order)
- `POST /tasks/{task_name}/comms` — append a user comment (body: `content`); returns `{ "filename": "…" }` (201)
- `GET /tasks/{task_name}/comms/{filename}` — raw content of one comms file (plain text)
- `GET /tasks/{task_name}/feed` — list feed entries (comms + agent logs) sorted by creation date
- `GET /tasks/{task_name}/logs/{filename}` — raw content of one agent log file (plain text)
- `GET /tasks/{task_name}/logs/stream` — stream the **active** log file via Server-Sent Events (404 if no command is running)
- `GET /tasks/{task_name}/commands` — command status: `active`, `command`, and when active, `active_log_filename` (log file being written)
- `POST /tasks/{task_name}/commands` — start a command (body: `command`, e.g. `plan-implement` or `implement`)
- `POST /tasks/{task_name}/create-pr` — create a pull request

CORS is enabled for `http://localhost:5173` and `http://127.0.0.1:5173` so the dev-frontend (Vite dev server) can call the API.

## Configuration

- `DEV_TASKS_DIR` — root directory for tasks (default: `~/tasks`). Repo shorthand is resolved from `~/.config/dev/repos.json` (same as the dev CLI).

## Run

For single-port dev, the frontend (Vite) proxies `/api` to this server; only the frontend port is exposed. Bind the backend to loopback so it is not reachable from the network:

From the repo root (dev workspace):

```bash
uv run --project dev-server uvicorn dev_server.main:app --reload --host 127.0.0.1
```

Or with the dev-server directory as cwd:

```bash
cd dev-server && uv run uvicorn dev_server.main:app --reload --host 127.0.0.1
```
