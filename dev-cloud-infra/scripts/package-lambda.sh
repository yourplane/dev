#!/usr/bin/env bash
# Package Lambda deployment bundle for CDK.
#
# Copies package source trees into the bundle (Lambda cannot use editable .pth installs).
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
INFRA_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$INFRA_DIR/.." && pwd)"
DIST="$INFRA_DIR/dist/lambda"

rm -rf "$DIST"
mkdir -p "$DIST"

cp -r "$REPO_ROOT/dev-sdk/src/dev_sdk" "$DIST/dev_sdk"
cp -r "$REPO_ROOT/dev-cloud-control/src/dev_cloud_control" "$DIST/dev_cloud_control"

uv pip install \
  --target "$DIST" \
  --no-cache-dir \
  boto3 "pydantic>=2.0"

# Verify imports resolve inside the bundle only.
PYTHONPATH="$DIST" python3 -c "import dev_sdk, dev_cloud_control.lambda_entry; print('ok')"

echo "Lambda bundle at $DIST"
