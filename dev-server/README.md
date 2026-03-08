# dev-server

FastAPI server for dev task management: create, list, archive.

## Endpoints

- `GET /tasks` — list active task names
- `POST /tasks` — create a task (body: `title`, `repo` URL or shorthand, optional `comment`, optional `task_name`)
- `POST /tasks/{task_name}/archive` — archive a task

## Configuration

- `DEV_TASKS_DIR` — root directory for tasks (default: `~/tasks`). Repo shorthand is resolved from `~/.config/dev/repos.json` (same as the dev CLI).

## Run

From the repo root (dev workspace):

```bash
uv run --project dev-server uvicorn dev_server.main:app --reload
```

Or with the dev-server directory as cwd:

```bash
cd dev-server && uv run uvicorn dev_server.main:app --reload
```
