#!/usr/bin/env bash
# Bootstrap a desk workstation as a dev-cloud environment worker.
#
# Fresh install: removes any prior ~/dev clone and worker service, clones dev,
# installs the worker, enables systemd user linger, and registers with the
# control plane using DEV_CLOUD_DISPLAY_NAME (default: dev-environment).
#
# Usage (on the workstation, as the target user — typically ubuntu):
#   export CONTROL_PLANE_URL=https://YOUR_CLOUDFRONT/api
#   export DEV_REPO_BRANCH=task/cloud-dev   # optional
#   ./bootstrap-environment.sh
#
# From a operator machine via SSM:
#   aws ssm send-command --instance-ids i-... --document-name AWS-RunShellScript \
#     --parameters commands=["sudo -u ubuntu -H bash -s"] \
#     --cli-input-json file://payload.json
set -euo pipefail

CONTROL_PLANE_URL="${CONTROL_PLANE_URL:-}"
DEV_CLOUD_DISPLAY_NAME="${DEV_CLOUD_DISPLAY_NAME:-dev-environment}"
DEV_REPO_URL="${DEV_REPO_URL:-https://github.com/yourplane/dev.git}"
DEV_REPO_BRANCH="${DEV_REPO_BRANCH:-task/cloud-dev}"
DEV_TASKS_ROOT="${DEV_TASKS_ROOT:-$HOME/tasks}"
HOME_DEV="${HOME_DEV:-$HOME/dev}"

if [[ -z "$CONTROL_PLANE_URL" ]]; then
  echo "Set CONTROL_PLANE_URL (e.g. https://xxx.cloudfront.net/api)" >&2
  exit 1
fi

log() { echo "==> $*"; }

prepare_user_systemd() {
  local uid
  uid="$(id -u)"
  export XDG_RUNTIME_DIR="/run/user/${uid}"
  export DBUS_SESSION_BUS_ADDRESS="unix:path=${XDG_RUNTIME_DIR}/bus"
  if [[ ! -S "${XDG_RUNTIME_DIR}/bus" ]] && command -v sudo >/dev/null; then
    sudo loginctl enable-linger "$(whoami)" 2>/dev/null || true
    sudo systemctl start "user@${uid}.service" 2>/dev/null || true
  fi
}

log "Enabling systemd user linger for $(whoami)"
if command -v loginctl >/dev/null; then
  if loginctl enable-linger "$(whoami)" 2>/dev/null; then
    :
  elif command -v sudo >/dev/null; then
    sudo loginctl enable-linger "$(whoami)"
  else
    echo "Warning: could not enable linger; worker may stop when you log out" >&2
  fi
fi
prepare_user_systemd

log "Stopping any existing dev-cloud-worker service"
systemctl --user stop dev-cloud-worker.service 2>/dev/null || true
systemctl --user disable dev-cloud-worker.service 2>/dev/null || true
rm -f "${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/dev-cloud-worker.service"
systemctl --user daemon-reload 2>/dev/null || true

log "Fresh clone: removing $HOME_DEV (preserving environment registration)"
rm -rf "$HOME_DEV"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/dev-cloud"
ENV_ID_BACKUP=""
DISPLAY_NAME_BACKUP=""
if [[ -f "$CONFIG_DIR/environment_id" ]]; then
  ENV_ID_BACKUP="$(cat "$CONFIG_DIR/environment_id")"
fi
if [[ -f "$CONFIG_DIR/display_name" ]]; then
  DISPLAY_NAME_BACKUP="$(cat "$CONFIG_DIR/display_name")"
fi
rm -rf "$CONFIG_DIR"
mkdir -p "$CONFIG_DIR"
if [[ -n "$ENV_ID_BACKUP" ]]; then
  echo "$ENV_ID_BACKUP" > "$CONFIG_DIR/environment_id"
  log "Preserved environment_id=$ENV_ID_BACKUP"
fi
if [[ -n "$DISPLAY_NAME_BACKUP" ]]; then
  echo "$DISPLAY_NAME_BACKUP" > "$CONFIG_DIR/display_name"
fi

if ! command -v git >/dev/null; then
  echo "git is required" >&2
  exit 1
fi

if ! command -v uv >/dev/null; then
  log "Installing uv"
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi
export PATH="$HOME/.local/bin:$PATH"

log "Cloning $DEV_REPO_URL (branch $DEV_REPO_BRANCH) to $HOME_DEV"
git clone --branch "$DEV_REPO_BRANCH" --depth 1 "$DEV_REPO_URL" "$HOME_DEV"

mkdir -p "$DEV_TASKS_ROOT"

export CONTROL_PLANE_URL
export DEV_CLOUD_DISPLAY_NAME
export DEV_TASKS_ROOT

log "Installing dev-cloud-worker"
"$HOME_DEV/dev-cloud-worker/install.sh"

log "Worker status"
prepare_user_systemd
systemctl --user status dev-cloud-worker.service --no-pager || true

log "Bootstrap complete (display_name=$DEV_CLOUD_DISPLAY_NAME)"
