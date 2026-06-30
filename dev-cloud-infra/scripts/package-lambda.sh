#!/usr/bin/env bash
# Package Lambda deployment bundle for CDK.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DIST="$ROOT/dist/lambda"
rm -rf "$DIST"
mkdir -p "$DIST"
uv pip install \
  --target "$DIST" \
  -e "$ROOT/dev-sdk" \
  -e "$ROOT/dev-cloud-control"
cp -r "$ROOT/dev-cloud-control/src/dev_cloud_control" "$DIST/"
echo "Lambda bundle at $DIST"
