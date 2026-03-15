#!/usr/bin/env bash
# Install systemd user service so the dev daemon runs on startup (at login).
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
SERVICE_FILE="$UNIT_DIR/dev-daemon.service"

START_NOW=
while [[ $# -gt 0 ]]; do
  case "$1" in
    --now)
      START_NOW=1
      shift
      ;;
    -h|--help)
      echo "Usage: $0 [--now]"
      echo ""
      echo "Installs a systemd user service so the dev daemon (backend + frontend)"
      echo "starts when you log in. Repo root: $REPO_ROOT"
      echo ""
      echo "  --now    Start the service immediately (default: enable only, start at next login)"
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      exit 1
      ;;
  esac
done

if [[ ! -d "$REPO_ROOT/dev-server" ]] || [[ ! -d "$REPO_ROOT/dev-frontend" ]]; then
  echo "install.sh: repo root not found (expected dev-server and dev-frontend under $REPO_ROOT)" >&2
  exit 1
fi

mkdir -p "$UNIT_DIR"

cat > "$SERVICE_FILE" << EOF
[Unit]
Description=Dev stack (backend + frontend)
After=network.target

[Service]
Type=simple
WorkingDirectory=$REPO_ROOT
ExecStart=$REPO_ROOT/dev-daemon/start.sh
Restart=on-failure
RestartSec=5

Environment=HOME=%h
Environment=PATH=$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin

[Install]
WantedBy=default.target
EOF

echo "Wrote $SERVICE_FILE"
systemctl --user daemon-reload
systemctl --user enable dev-daemon.service
echo "Enabled dev-daemon.service (starts at login)."

if [[ -n "$START_NOW" ]]; then
  systemctl --user start dev-daemon.service
  echo "Started dev-daemon.service. UI: http://localhost:5173"
fi

echo ""
echo "Useful commands:"
echo "  Start now:    systemctl --user start dev-daemon.service"
echo "  Stop:         systemctl --user stop dev-daemon.service"
echo "  View logs:    journalctl --user -u dev-daemon.service -f"
echo "  Disable:      systemctl --user disable dev-daemon.service"
