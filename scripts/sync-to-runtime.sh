#!/usr/bin/env bash
set -euo pipefail

SOURCE_REPO="/Users/mu/Documents/GitHub/haidilao-automation-monorepo"
RUNTIME_REPO="/Users/mu/haidilao-automation-monorepo"

if ! command -v rsync >/dev/null 2>&1; then
    echo "rsync is required but not installed" >&2
    exit 1
fi

mkdir -p "$RUNTIME_REPO"

rsync -a --delete \
  --exclude ".git/" \
  --exclude ".venv/" \
  --exclude ".pytest_cache/" \
  --exclude ".mypy_cache/" \
  --exclude "__pycache__/" \
  --exclude ".coverage" \
  --exclude "logs/" \
  --exclude "output/" \
  --exclude "docker/postgres_data/" \
  --exclude "docker/pgadmin_data/" \
  --exclude "docker/minio_data/" \
  "$SOURCE_REPO/" "$RUNTIME_REPO/"

if [ -f "$SOURCE_REPO/.env" ]; then
    cp "$SOURCE_REPO/.env" "$RUNTIME_REPO/.env"
fi

echo "Synced:"
echo "  from: $SOURCE_REPO"
echo "  to:   $RUNTIME_REPO"
echo
echo "Restart service if needed:"
echo "  launchctl kickstart -k gui/$(id -u)/com.haidilao.server"
