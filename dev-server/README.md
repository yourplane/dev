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
