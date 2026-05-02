# dev-server

FastAPI server for dev task management: create, list, archive.

## Endpoints

- `GET /tasks` — list active task names
- `GET /repos` — list repo shorthands (from `~/.config/dev/repos.json`), for use by the frontend
- `POST /tasks` — create a task (body: `title`, `repo` URL or shorthand, optional `comment`, optional `task_name`). Returns **200** with `Content-Type: application/x-ndjson`: one JSON object per line — `{"type":"progress","message":"…"}` (same strings as CLI `dev task create` / `TaskManager.start_task` `on_progress`), then `{"type":"complete","task_name":"…","task_dir":"…"}` on success, or `{"type":"error","detail":"…","status":…}` on failure.
- `POST /tasks/{task_name}/archive` — archive a task
- `GET /archive` — list archived tasks newest-first (supports `limit` and `offset` query params; response includes `total` and `next_offset`)
- `POST /archive/{archived_name}/unarchive` — move archived task back to active (restore)
- `POST /archive/{archived_name}/copy` — create a new task from an archived task (same name and comms, new agent chat, no logs). Optional body: `{ "task_name": "override-name" }`. Returns 201 with `task_name`, `task_dir`; 409 if a task with that name already exists.
- `GET /tasks/{task_name}/comms` — list comms filenames for a task (index order)
- `POST /tasks/{task_name}/comms` — append a user comment (body: `content`); returns `{ "filename": "…" }` (201)
- `GET /tasks/{task_name}/comms/{filename}` — raw content of one comms file (plain text)
- `DELETE /tasks/{task_name}/comms/{filename}` — remove a comms file and its index entry. Returns 204 when allowed. Returns 400 when agent logs exist and the comm is not strictly after the last agent log event.
- `GET /tasks/{task_name}/feed` — list feed entries (comms + agent logs) sorted by creation date
- `GET /tasks/{task_name}/logs/{filename}` — raw content of one agent log file (plain text)
- `GET /tasks/{task_name}/logs/stream` — stream the **active** log file via Server-Sent Events (404 if no command is running)
- `GET /tasks/{task_name}/commands` — command status: `active`, `command`, and when active, `active_log_filename` (agent log file being written; null while a shell command runs) and `active_bash_comms_filename` (the `*-user-bash.md` file currently receiving streamed output; null for agent commands)
- `POST /tasks/{task_name}/commands` — start a command (body: `command`: `plan-implement`, `implement`, `do`, or `bash`; optional `prompt` — required for `do` and `bash`, where `bash` runs `prompt` as `bash -c` with cwd set to the task directory). Returns 409 if any command (including bash) is already running for the task.
- `POST /tasks/{task_name}/commands/cancel` — cancel the active command (agent or bash)
- `POST /tasks/{task_name}/create-pr` — create a pull request
- `GET /tasks/{task_name}/drafts/comment` — comment textarea draft (plain text); `PUT` with body `{"content":"..."}` saves or clears (empty removes)
- `GET /tasks/{task_name}/drafts/bash` — bash-input draft (plain text), separate from comment; `PUT` same shape

CORS is enabled for `http://localhost:5173` and `http://127.0.0.1:5173` so the dev-frontend (Vite dev server) can call the API.

## Configuration

- `DEV_TASKS_DIR` — root directory for tasks (default: `~/tasks`). Repo shorthand is resolved from `~/.config/dev/repos.json` (same as the dev CLI).
- `DEV_BASH_MAX_OUTPUT_BYTES` — max captured stdout/stderr bytes for task shell commands (default: `2000000`). When exceeded, the process is killed and the comms transcript notes truncation.
- `DEV_BASH_TIMEOUT_SEC` — max runtime in seconds for task shell commands (default: `3600`). Use `0` to disable the timeout.
- `DEV_BASH_NO_STDBUF` — set to `1`/`true`/`yes` to skip wrapping shell commands with `stdbuf -oL -eL`. Default behavior uses `stdbuf` (GNU coreutils) so stdout/stderr are **line-buffered** when attached to a pipe; otherwise many programs only flush when the buffer fills, so live comms streaming appears frozen until the command ends.

### Task shell commands (`bash`)

The UI can run arbitrary shell in the task directory. While the command runs, the server creates an indexed comms file (`*-user-bash.md`), writes a short delimiter-wrapped **input** block (`__DEV_BASH_INPUT__` / `__DEV_BASH_INPUT_END__`, full multi-line prompt inside), then streams stdout/stderr after it, then appends a footer (`---`, exit code or cancellation). Older transcripts used a single `$ command` first line only. `GET .../commands` exposes `active_bash_comms_filename` so the UI can poll `GET .../comms/{filename}` for live output. Live updates depend on child processes flushing stdout (see `DEV_BASH_NO_STDBUF`). Treat dev-server and task directories as a **trusted boundary**: anyone who can reach the API can run code as the server user in that tree.

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

## Logs

The server logs to **stdout/stderr** in the terminal where uvicorn runs; there is no default log file. If you start the full stack with **systemd** (`dev-daemon`), use `journalctl --user -u dev-daemon.service -f`. For **dev-sdk** debug logs (e.g. from CLI code paths), see [dev-sdk/README.md](../dev-sdk/README.md#debugging) (`~/.local/share/dev/sdk-debug.log`, or `DEV_SDK_LOG`).
