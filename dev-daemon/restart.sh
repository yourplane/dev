#!/usr/bin/env bash
# Restart the dev stack (backend + frontend).
# Uses systemd user service when installed; otherwise stops local listeners and runs start.sh.
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
SERVICE_FILE="$UNIT_DIR/dev-daemon.service"
RESTART_LOG="${TMPDIR:-/tmp}/dev-daemon-restart.log"

usage() {
  echo "Usage: $0"
  echo ""
  echo "Restarts the dev daemon (dev-server + dev-frontend)."
  echo "If dev-daemon/install.sh was used, stops the systemd user service, clears"
  echo "ports 8000/5173, then starts again (does not block on a full frontend rebuild"
  echo "when DEV_DAEMON_SKIP_BUILD=1 is set)."
  echo "Otherwise stops processes on ports 8000 and 5173, then runs start.sh in the foreground."
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if [[ ! -d "$REPO_ROOT/dev-server" ]] || [[ ! -d "$REPO_ROOT/dev-frontend" ]]; then
  echo "restart.sh: repo root not found (expected dev-server and dev-frontend under $REPO_ROOT)" >&2
  exit 1
fi

stop_port() {
  local port="$1"
  if command -v fuser >/dev/null 2>&1; then
    fuser -k "${port}/tcp" 2>/dev/null || true
    return
  fi
  if command -v lsof >/dev/null 2>&1; then
    local pids
    pids="$(lsof -ti tcp:"$port" 2>/dev/null || true)"
    if [[ -n "$pids" ]]; then
      kill $pids 2>/dev/null || true
    fi
  fi
}

systemd_user_available() {
  [[ -f "$SERVICE_FILE" ]] \
    && command -v systemctl >/dev/null 2>&1 \
    && systemctl --user show-environment >/dev/null 2>&1
}

restart_systemd_service() {
  systemctl --user stop dev-daemon.service 2>/dev/null || true
  stop_port 8000
  stop_port 5173
  sleep 0.5
  systemctl --user start dev-daemon.service
}

start_stack_in_background() {
  local delay="${1:-0}"
  if [[ "$delay" != "0" ]]; then
    echo "Scheduling dev stack restart in ${delay}s..."
  else
    echo "Starting dev stack in background..."
  fi
  (
    [[ "$delay" != "0" ]] && sleep "$delay"
    stop_port 8000
    stop_port 5173
    sleep 0.5
    exec "$SCRIPT_DIR/start.sh"
  ) >>"$RESTART_LOG" 2>&1 &
  echo "Restart scheduled. UI may be briefly unavailable."
  echo "Logs: $RESTART_LOG"
}

if systemd_user_available; then
  # When invoked from dev-server bash (stdout is not a tty), defer so the caller can
  # finish before we stop the backend on port 8000.
  if [[ ! -t 1 ]]; then
    echo "Scheduling dev-daemon restart in 2s (deferred; safe for in-app bash)..."
    (
      sleep 2
      restart_systemd_service
    ) >>"$RESTART_LOG" 2>&1 &
    echo "Restart scheduled. UI may be briefly unavailable."
    echo "Logs: $RESTART_LOG"
    exit 0
  fi
  restart_systemd_service
  echo "Restarted dev-daemon.service. UI: http://localhost:5173"
  exit 0
fi

# When invoked from deploy.sh or dev-server bash (non-interactive / background restart).
if [[ "${DEV_DAEMON_RESTART_BACKGROUND:-}" == "1" ]]; then
  start_stack_in_background 0
  exit 0
fi

# When invoked from dev-server bash (stdout is not a tty), defer stop/start so this
# shell can exit before we kill the backend on port 8000.
if [[ ! -t 1 ]]; then
  start_stack_in_background 2
  exit 0
fi

echo "Stopping listeners on 8000 and 5173..."
stop_port 8000
stop_port 5173
sleep 0.5

exec "$SCRIPT_DIR/start.sh"
