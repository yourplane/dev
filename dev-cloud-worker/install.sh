#!/usr/bin/env bash
# Install dev-cloud-worker as a systemd user service.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
WORK_DIR="$(cd "$REPO_ROOT/.." && pwd)"

CONTROL_PLANE_URL="${CONTROL_PLANE_URL:-}"
DEV_TASKS_ROOT="${DEV_TASKS_ROOT:-$HOME/tasks}"
DEV_CLOUD_DISPLAY_NAME="${DEV_CLOUD_DISPLAY_NAME:-}"

if [[ -z "$CONTROL_PLANE_URL" ]]; then
  echo "Set CONTROL_PLANE_URL to your CloudFront /api base (e.g. https://xxx.cloudfront.net/api)" >&2
  exit 1
fi

CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/dev-cloud"
mkdir -p "$CONFIG_DIR"
if [[ -n "$DEV_CLOUD_DISPLAY_NAME" ]]; then
  echo "$DEV_CLOUD_DISPLAY_NAME" > "$CONFIG_DIR/display_name"
fi

cd "$WORK_DIR"
uv pip install -e dev-sdk -e dev-cloud-control -e dev-cloud-worker

UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
mkdir -p "$UNIT_DIR"

UV_BIN="$(command -v uv)"

cat > "$UNIT_DIR/dev-cloud-worker.service" <<EOF
[Unit]
Description=Dev Cloud Environment Worker
After=network-online.target

[Service]
Type=simple
WorkingDirectory=$WORK_DIR
Environment=CONTROL_PLANE_URL=$CONTROL_PLANE_URL
Environment=DEV_TASKS_ROOT=$DEV_TASKS_ROOT
ExecStart=$UV_BIN run dev-cloud-worker
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now dev-cloud-worker.service
echo "dev-cloud-worker installed and started."
