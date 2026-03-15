#!/usr/bin/env bash
# Start dev backend and frontend in the foreground. Ctrl+C stops both.
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
FRONTEND_DIR="$REPO_ROOT/dev-frontend"

# When run under systemd, install.sh passes DEV_DAEMON_UV and DEV_DAEMON_NPM (full paths)
export PATH="${HOME:?}/.local/bin:/usr/local/bin:$PATH"
UV_CMD="${DEV_DAEMON_UV:-uv}"
NPM_CMD="${DEV_DAEMON_NPM:-npm}"

if [[ ! -d "$REPO_ROOT/dev-server" ]] || [[ ! -d "$FRONTEND_DIR" ]]; then
  echo "dev-daemon: repo root not found (expected dev-server and dev-frontend under $REPO_ROOT)" >&2
  exit 1
fi

cleanup() {
  if [[ -n "$BACKEND_PID" ]] && kill -0 "$BACKEND_PID" 2>/dev/null; then
    kill "$BACKEND_PID" 2>/dev/null || true
    wait "$BACKEND_PID" 2>/dev/null || true
  fi
  exit "${1:-0}"
}

trap 'cleanup 130' INT
trap 'cleanup 143' TERM
trap 'cleanup $?' EXIT

echo "Starting dev-server (backend) on 127.0.0.1:8000..."
(
  cd "$REPO_ROOT"
  exec "$UV_CMD" run --project dev-server uvicorn dev_server.main:app --reload --host 127.0.0.1
) &
BACKEND_PID=$!

# Wait for backend to be ready (so frontend proxy can reach it)
BACKEND_URL="http://127.0.0.1:8000/"
echo "Waiting for backend to be ready..."
if command -v curl >/dev/null 2>&1; then
  for _ in {1..60}; do
    if curl -sf -o /dev/null "$BACKEND_URL" 2>/dev/null; then
      break
    fi
    if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
      echo "Backend process exited before becoming ready." >&2
      exit 1
    fi
    sleep 0.5
  done
  if ! curl -sf -o /dev/null "$BACKEND_URL" 2>/dev/null; then
    echo "Backend did not become ready in time (30s). Check logs above." >&2
    cleanup 1
  fi
else
  echo "Warning: curl not found; waiting 5s for backend." >&2
  sleep 5
fi

echo "Starting dev-frontend (Vite) on http://localhost:5173..."
(
  cd "$FRONTEND_DIR"
  exec "$NPM_CMD" run dev
)
