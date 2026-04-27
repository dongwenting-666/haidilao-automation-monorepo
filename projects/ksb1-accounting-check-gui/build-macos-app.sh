#!/bin/zsh
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(cd -- "$SCRIPT_DIR/../.." && pwd)

cd "$REPO_ROOT"
uv run --package ksb1-accounting-check-gui python -m PyInstaller \
  "$SCRIPT_DIR/ksb1_gui.spec" \
  --noconfirm \
  --clean
