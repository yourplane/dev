#!/usr/bin/env bash
# Deploy a git branch to a local dev checkout and restart the daemon.
#
# Typical usage from a task workspace:
#   ./dev-daemon/deploy.sh /path/to/source/repo task/my-feature
#
# Defaults: target ~/dev, branch task/merge-from-main, source = repo containing this script.
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_REPO="$(cd "$SCRIPT_DIR/.." && pwd)"
TARGET="${DEV_DEPLOY_TARGET:-$HOME/dev}"
BRANCH="${1:-task/merge-from-main}"
SOURCE="${2:-$SOURCE_REPO}"

usage() {
  echo "Usage: $0 [branch] [source-repo-path]"
  echo ""
  echo "Fast-forward TARGET ($TARGET) to branch from SOURCE, rebuild, and restart."
  echo "Environment: DEV_DEPLOY_TARGET overrides the deploy destination directory."
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if [[ ! -d "$TARGET/dev-server" || ! -d "$TARGET/dev-frontend" ]]; then
  echo "deploy.sh: target not found (expected dev-server and dev-frontend under $TARGET)" >&2
  exit 1
fi

if [[ ! -d "$SOURCE/.git" ]]; then
  echo "deploy.sh: source is not a git repo: $SOURCE" >&2
  exit 1
fi

UV_CMD="${DEV_DAEMON_UV:-uv}"
NPM_CMD="${DEV_DAEMON_NPM:-npm}"
export PATH="${HOME:?}/.local/bin:/usr/local/bin:$PATH"

echo "Deploying $BRANCH from $SOURCE -> $TARGET"
(
  cd "$TARGET"
  git fetch "$SOURCE" "$BRANCH"
  git checkout "$BRANCH" 2>/dev/null || git checkout -B "$BRANCH" FETCH_HEAD
  git merge --ff-only FETCH_HEAD
)

echo "Syncing Python dependencies..."
(
  cd "$TARGET"
  "$UV_CMD" sync --extra dev
)

echo "Building frontend..."
(
  cd "$TARGET/dev-frontend"
  "$NPM_CMD" install --no-audit --no-fund
  "$NPM_CMD" run build
)

export DEV_DAEMON_SKIP_BUILD=1
if command -v systemctl >/dev/null 2>&1 && [[ -f "${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/dev-daemon.service" ]]; then
  systemctl --user set-environment DEV_DAEMON_SKIP_BUILD=1
fi

echo "Restarting dev daemon..."
"$TARGET/dev-daemon/restart.sh"

echo "Deploy complete. UI: http://localhost:5173"
