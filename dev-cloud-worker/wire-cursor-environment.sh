#!/usr/bin/env bash
# Wire Cursor API key from Secrets Manager onto this workstation's worker service.
# Requires: IAM permission secretsmanager:GetSecretValue on dev-cloud/cursor-api-key,
#           secret value already set in AWS Console / CLI.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CURSOR_API_KEY_SECRET_NAME="${CURSOR_API_KEY_SECRET_NAME:-dev-cloud/cursor-api-key}"
AWS_REGION="${AWS_REGION:-us-east-1}"

"$SCRIPT_DIR/setup-cursor.sh"

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

UNIT="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/dev-cloud-worker.service"
if [[ ! -f "$UNIT" ]]; then
  echo "dev-cloud-worker.service not installed; run install.sh first" >&2
  exit 1
fi

# Verify secret is readable (worker loads it at runtime; this fails fast if IAM/key missing).
aws secretsmanager get-secret-value \
  --region "$AWS_REGION" \
  --secret-id "$CURSOR_API_KEY_SECRET_NAME" \
  --query SecretString \
  --output text >/dev/null

# Ensure systemd unit passes secret name and PATH for cursor CLI.
if ! grep -q 'CURSOR_API_KEY_SECRET_NAME=' "$UNIT"; then
  sed -i "/^Environment=DEV_TASKS_ROOT=/a Environment=CURSOR_API_KEY_SECRET_NAME=$CURSOR_API_KEY_SECRET_NAME" "$UNIT"
fi
if ! grep -q '^Environment=AWS_REGION=' "$UNIT"; then
  sed -i "/^Environment=CURSOR_API_KEY_SECRET_NAME=/a Environment=AWS_REGION=$AWS_REGION" "$UNIT"
fi
if ! grep -q '^Environment=PATH=' "$UNIT"; then
  sed -i "/^Environment=AWS_REGION=/a Environment=PATH=$HOME/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" "$UNIT"
fi

prepare_user_systemd
systemctl --user daemon-reload
systemctl --user restart dev-cloud-worker.service
sleep 2
systemctl --user is-active dev-cloud-worker.service
echo "Cursor wired (secret=$CURSOR_API_KEY_SECRET_NAME). Worker restarted."
