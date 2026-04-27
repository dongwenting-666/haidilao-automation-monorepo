#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

"$SCRIPT_DIR/sync-to-runtime.sh"

launchctl kickstart -k "gui/$(id -u)/com.haidilao.server"

echo
echo "Runtime deployed and com.haidilao.server restarted."
