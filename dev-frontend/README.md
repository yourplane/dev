# dev-frontend

Web UI for dev task management: list tasks, create a task, archive a task. Talks to **dev-server**.

## Setup

1. Install dependencies:

   ```bash
   cd dev-frontend
   npm install
   ```

2. (Optional) Set the dev-server API URL. Default is `http://localhost:8000`. Copy `.env.example` to `.env` and edit if needed:

   ```bash
   cp .env.example .env
   ```

## Run

With dev-server running (from repo root):

```bash
uv run --project dev-server uvicorn dev_server.main:app --reload
```

Start the frontend:

```bash
cd dev-frontend
npm run dev
```

Open http://localhost:5173. You can list tasks, create a task (title, repo shorthand or custom URL, optional description, optional task name), and archive tasks. Repo shorthands are configured via the CLI (`dev repos add <name> <url>`) and stored in `~/.config/dev/repos.json`; the create form fetches them from `GET /repos`.

## Build

```bash
npm run build
```

Output is in `dist/`. Serve with any static host or mount under dev-server if desired.
