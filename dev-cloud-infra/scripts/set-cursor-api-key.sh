#!/usr/bin/env bash
# Set the shared Cursor personal API key in Secrets Manager (after CDK deploy).
#
# Usage:
#   ./scripts/set-cursor-api-key.sh
#   ./scripts/set-cursor-api-key.sh 'key_abc123...'
#
# Reads from CURSOR_API_KEY env if no argument. Prompts securely if neither is set.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUTPUTS_FILE="$SCRIPT_DIR/../.deploy-outputs.json"
REGION="${AWS_REGION:-us-east-1}"
SECRET_NAME="${CURSOR_API_KEY_SECRET_NAME:-dev-cloud/cursor-api-key}"

if [[ -f "$OUTPUTS_FILE" ]]; then
  NAME_FROM_OUTPUTS="$(python3 - "$OUTPUTS_FILE" <<'PY'
import json, sys
raw = json.load(open(sys.argv[1], encoding="utf-8"))
data = raw.get("DevCloudStack", raw)
print(data.get("CursorApiKeySecretName", ""))
PY
)"
  if [[ -n "$NAME_FROM_OUTPUTS" ]]; then
    SECRET_NAME="$NAME_FROM_OUTPUTS"
  fi
fi

KEY="${1:-${CURSOR_API_KEY:-}}"
if [[ -z "$KEY" ]]; then
  read -r -s -p "Paste Cursor personal API key: " KEY
  echo
fi
if [[ -z "$KEY" ]]; then
  echo "No API key provided" >&2
  exit 1
fi

aws secretsmanager put-secret-value \
  --region "$REGION" \
  --secret-id "$SECRET_NAME" \
  --secret-string "$KEY"

echo "Cursor API key updated in secret: $SECRET_NAME"
