#!/usr/bin/env bash
# Package Node.js stream Lambda for CDK.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
INFRA_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$INFRA_DIR/.." && pwd)"
STREAM_DIR="$REPO_ROOT/dev-cloud-stream"
DIST="$INFRA_DIR/dist/stream-lambda"

rm -rf "$DIST"
mkdir -p "$DIST"
cp "$STREAM_DIR/index.mjs" "$DIST/"
cp "$STREAM_DIR/package.json" "$DIST/"

(
  cd "$DIST"
  npm install --omit=dev --no-audit --no-fund
)

echo "Stream Lambda bundle at $DIST"
