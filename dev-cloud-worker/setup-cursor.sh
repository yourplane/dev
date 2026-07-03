#!/usr/bin/env bash
# Install Cursor Agent CLI on a workstation if missing.
set -euo pipefail

export PATH="$HOME/.local/bin:$PATH"

if command -v agent >/dev/null 2>&1 || command -v cursor-agent >/dev/null 2>&1; then
  echo "Cursor CLI already installed: $(command -v agent || command -v cursor-agent)"
  agent --version 2>/dev/null || cursor-agent --version 2>/dev/null || true
  exit 0
fi

if ! command -v curl >/dev/null 2>&1; then
  echo "curl is required to install Cursor CLI" >&2
  exit 1
fi

echo "Installing Cursor Agent CLI..."
curl https://cursor.com/install -fsS | bash
export PATH="$HOME/.local/bin:$PATH"

if ! command -v agent >/dev/null 2>&1; then
  echo "Cursor CLI install finished but 'agent' not found in PATH" >&2
  exit 1
fi

agent --version
echo "Cursor CLI ready."
