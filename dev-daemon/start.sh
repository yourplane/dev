#!/usr/bin/env bash
# Start dev backend and frontend in the foreground. Ctrl+C stops both.
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
FRONTEND_DIR="$REPO_ROOT/dev-frontend"

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
  exec uv run --project dev-server uvicorn dev_server.main:app --reload --host 127.0.0.1
) &
BACKEND_PID=$!

# Give backend a moment to bind before starting frontend
sleep 2

echo "Starting dev-frontend (Vite) on http://localhost:5173..."
(
  cd "$FRONTEND_DIR"
  exec npm run dev
)
