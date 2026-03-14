# dev-frontend

Web UI for dev task management: list tasks, create a task, archive a task. Talks to **dev-server**.

In development, all traffic goes through the frontend port: the Vite dev server proxies `/api` to the backend. Only the frontend port (default 5173) is exposed; the backend runs on 127.0.0.1:8000 and is not directly reachable from the network.

## Setup

1. Install dependencies:

   ```bash
   cd dev-frontend
   npm install
   ```

2. (Optional) Override the API base URL. By default the app uses `/api` (same origin), which Vite proxies to the backend. To talk to the backend directly (e.g. a different host/port), copy `.env.example` to `.env` and set `VITE_DEV_SERVER_URL`.

## Run

Start the backend (from repo root), bound to loopback:

```bash
uv run --project dev-server uvicorn dev_server.main:app --reload --host 127.0.0.1
```

Start the frontend:

```bash
cd dev-frontend
npm run dev
```

Open http://localhost:5173. All API calls go through the frontend origin via the proxy. You can list tasks, create a task (title, repo shorthand or custom URL, optional description, optional task name), and archive tasks. Repo shorthands are configured via the CLI (`dev repos add <name> <url>`) and stored in `~/.config/dev/repos.json`; the create form fetches them from `GET /repos`.

## Build

```bash
npm run build
```

Output is in `dist/`. Serve with any static host or mount under dev-server if desired.

## Lint

```bash
npm run lint
```

Uses ESLint with TypeScript and React hooks rules. **Convention:** In each component, declare all `useCallback`/`useMemo` that are used in `useEffect` above those effects to avoid "Cannot access before initialization" errors.

## Test

```bash
npm run test
```

Runs Vitest. Smoke tests render the app and task comms view to catch runtime errors (e.g. hook order).
