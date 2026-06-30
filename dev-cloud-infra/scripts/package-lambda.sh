#!/usr/bin/env bash
# Package Lambda deployment bundle for CDK.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
INFRA_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$INFRA_DIR/.." && pwd)"
DIST="$INFRA_DIR/dist/lambda"
rm -rf "$DIST"
mkdir -p "$DIST"
uv pip install \
  --target "$DIST" \
  -e "$REPO_ROOT/dev-sdk" \
  -e "$REPO_ROOT/dev-cloud-control"
cp -r "$REPO_ROOT/dev-cloud-control/src/dev_cloud_control" "$DIST/"
echo "Lambda bundle at $DIST"
