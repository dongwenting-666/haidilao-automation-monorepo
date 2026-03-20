#!/usr/bin/env bash
# =============================================================================
# server-start.sh — Haidilao automation server launcher with crash alerting
#
# Managed by launchd (com.haidilao.server). launchd handles restart via
# KeepAlive=true. This script's job is to:
#   1. Start the server
#   2. On abnormal exit, send a Lark alert + wake OpenClaw so the agent
#      can investigate, restart, and report back on Telegram.
#
# Crash flow:
#   server crashes (exit != 0)
#       → send_crash_alert() fires
#           → Lark text to 'hongming' chat
#           → POST /hooks/agent to OpenClaw gateway (wakes the agent)
#       → script exits → launchd restarts via KeepAlive
# =============================================================================

set -euo pipefail

REPO_ROOT="/Users/hongming-claw/haidilao-automation-monorepo"
LOG_FILE="$REPO_ROOT/server.log"
OPENCLAW_GATEWAY="http://127.0.0.1:18789"

# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [server-start] $*" | tee -a "$LOG_FILE"
}

log_err() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [server-start] ERROR: $*" | tee -a "$LOG_FILE" >&2
}

# ---------------------------------------------------------------------------
# Crash alert — sends to Lark + wakes OpenClaw agent
# ---------------------------------------------------------------------------
send_crash_alert() {
    local exit_code="$1"
    local timestamp
    timestamp=$(date '+%Y-%m-%d %H:%M:%S %Z')

    log "Server exited with code $exit_code — sending crash alert"

    # Lark alert (best-effort, don't let this block launchd restart)
    /Users/hongming-claw/.local/bin/uv run \
        --project "$REPO_ROOT/server" \
        python -c "
import os, sys
sys.path.insert(0, '$REPO_ROOT/server/src')
os.chdir('$REPO_ROOT')

try:
    from dotenv import load_dotenv
    load_dotenv('$REPO_ROOT/.env')
    from lark_client import LarkClient, chat_id_for
    app_id = os.environ.get('LARK_APP_ID', '')
    app_secret = os.environ.get('LARK_APP_SECRET', '')
    chat_id = chat_id_for('hongming')
    if app_id and app_secret and chat_id:
        msg = (
            '🔴 海底捞自动化服务器崩溃\n\n'
            '时间: $timestamp\n'
            '退出码: $exit_code\n\n'
            'launchd 正在自动重启，OpenClaw 已收到通知并正在调查。'
        )
        with LarkClient(app_id=app_id, app_secret=app_secret) as c:
            c.send_text(msg, chat_id=chat_id)
        print('Lark alert sent')
    else:
        print('Lark not configured, skipping')
except Exception as e:
    print(f'Lark alert failed: {e}', file=sys.stderr)
" 2>>"$LOG_FILE" || true

    # Wake OpenClaw agent (best-effort)
    curl -s -X POST "$OPENCLAW_GATEWAY/hooks/agent" \
        -H "Content-Type: application/json" \
        -d "{
            \"message\": \"🔴 SYSTEM ALERT: Haidilao automation server crashed at $timestamp (exit code $exit_code). Please check server.log at $LOG_FILE, diagnose the cause, attempt restart via launchd, verify the server is healthy, then report back to Hongming on Telegram with what happened and what you did.\",
            \"wakeMode\": \"now\"
        }" >>"$LOG_FILE" 2>&1 || true

    log "Crash alert sent (Lark + OpenClaw)"
}

# ---------------------------------------------------------------------------
# Health-check after startup — confirm port 8000 is responding
# ---------------------------------------------------------------------------
wait_for_healthy() {
    local max_attempts=30
    local attempt=0
    local delay=2

    log "Waiting for server to become healthy on :8000..."
    while [ $attempt -lt $max_attempts ]; do
        if curl -sf http://localhost:8000/api/runs >/dev/null 2>&1; then
            log "Server healthy after $((attempt * delay))s"
            return 0
        fi
        attempt=$((attempt + 1))
        sleep $delay
    done

    log_err "Server did not become healthy within $((max_attempts * delay))s"
    return 1
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
log "========================================="
log "Starting Haidilao automation server"
log "Repo: $REPO_ROOT"
log "uv:   $(/Users/hongming-claw/.local/bin/uv --version 2>/dev/null || echo 'unknown')"
log "========================================="

cd "$REPO_ROOT"

# Run the server — capture exit code without triggering set -e
set +e
/Users/hongming-claw/.local/bin/uv run --project server python -m server
SERVER_EXIT=$?
set -e

if [ $SERVER_EXIT -eq 0 ]; then
    log "Server exited cleanly (code 0) — likely intentional shutdown, no alert"
else
    log_err "Server exited with code $SERVER_EXIT"
    send_crash_alert "$SERVER_EXIT"
fi

log "server-start.sh done (exit $SERVER_EXIT)"
exit $SERVER_EXIT
