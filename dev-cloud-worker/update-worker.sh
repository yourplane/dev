#!/usr/bin/env bash
# Pull latest dev-cloud-worker code and restart the systemd user service.
#
# Usage (on the workstation, as the worker user — typically ubuntu):
#   export CONTROL_PLANE_URL=https://YOUR_CLOUDFRONT/api   # optional if already installed
#   ./update-worker.sh
#
# From an operator machine via SSM:
#   aws ssm send-command --instance-ids i-... --document-name AWS-RunShellScript \
#     --parameters 'commands=["sudo -u ubuntu -H bash -lc \"cd ~/dev/dev-cloud-worker && ./update-worker.sh\""]'
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOME_DEV="$(cd "$SCRIPT_DIR/.." && pwd)"

if [[ -z "${DEV_REPO_BRANCH:-}" ]]; then
  echo "Set DEV_REPO_BRANCH (git branch to pull on the worker)" >&2
  exit 1
fi

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

log() { echo "==> $*"; }

if [[ ! -d "$HOME_DEV/.git" ]]; then
  echo "Repo not found at $HOME_DEV; run bootstrap-environment.sh first" >&2
  exit 1
fi

git config --global --add safe.directory "$HOME_DEV"

log "Pulling $DEV_REPO_BRANCH in $HOME_DEV"
git -C "$HOME_DEV" fetch origin "$DEV_REPO_BRANCH"
git -C "$HOME_DEV" checkout "$DEV_REPO_BRANCH"
git -C "$HOME_DEV" pull --ff-only origin "$DEV_REPO_BRANCH"

export PATH="$HOME/.local/bin:$PATH"
if [[ -f "$HOME_DEV/dev-cloud-infra/.deploy-outputs.json" ]]; then
  CF_URL="$(python3 -c "import json; d=json.load(open('$HOME_DEV/dev-cloud-infra/.deploy-outputs.json')); print(d.get('DevCloudStack',{}).get('CloudFrontUrl',''))" 2>/dev/null || true)"
  if [[ -n "$CF_URL" ]]; then
    export CONTROL_PLANE_URL="${CONTROL_PLANE_URL:-${CF_URL}/api}"
  fi
fi

log "Reinstalling worker"
"$SCRIPT_DIR/install.sh"

prepare_user_systemd
log "Restarting dev-cloud-worker"
systemctl --user restart dev-cloud-worker.service
systemctl --user is-active dev-cloud-worker.service
log "Update complete"
