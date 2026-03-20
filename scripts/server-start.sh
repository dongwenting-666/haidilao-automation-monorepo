#!/usr/bin/env bash
# =============================================================================
# server-start.sh — Haidilao automation server launcher with crash alerting
#
# Managed by launchd (com.haidilao.server). launchd handles restart via
# KeepAlive. This script's job is to:
#   1. Start the server and wait for it to exit
#   2. On abnormal exit, send a Lark alert + wake OpenClaw via cron API
#      so the agent can investigate, restart if needed, and report back
#      to Hongming on Telegram
#
# Crash flow:
#   server crashes (exit != 0)
#       → send_crash_alert() fires
#           → Lark text to 'hongming' chat
#           → OpenClaw cron one-shot agentTurn (isolated) to wake agent
#       → script exits with original exit code
#       → launchd sees non-zero exit + KeepAlive → restarts after ThrottleInterval
# =============================================================================

set -euo pipefail

REPO_ROOT="/Users/hongming-claw/haidilao-automation-monorepo"
OPENCLAW_GATEWAY="http://127.0.0.1:18789"

# ---------------------------------------------------------------------------
# Logging — stdout only; launchd routes it to server.log via StandardOutPath
# ---------------------------------------------------------------------------
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [server-start] $*"
}

log_err() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [server-start] ERROR: $*" >&2
}

# ---------------------------------------------------------------------------
# Crash alert — Lark text + OpenClaw agentTurn wake
# ---------------------------------------------------------------------------
send_crash_alert() {
    local exit_code="$1"
    local timestamp
    timestamp=$(date '+%Y-%m-%d %H:%M:%S %Z')

    log "Server exited with code $exit_code — sending crash alert"

    # 1. Lark alert via Python (credentials from env set by launchd plist)
    /Users/hongming-claw/.local/bin/uv run \
        --project "$REPO_ROOT/server" \
        python -c "
import os, sys
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
            'launchd 正在自动重启服务器。\n'
            'OpenClaw 已收到通知，正在调查中。'
        )
        with LarkClient(app_id=app_id, app_secret=app_secret) as c:
            c.send_text(msg, chat_id=chat_id)
        print('Lark alert sent')
    else:
        print('Lark credentials or chat alias not configured, skipping', file=sys.stderr)
except Exception as e:
    print(f'Lark alert failed: {e}', file=sys.stderr)
" || log_err "Lark alert script failed (non-fatal)"

    # 2. Wake OpenClaw agent via one-shot cron job (agentTurn in isolated session)
    local alert_message="🔴 SYSTEM ALERT: Haidilao automation server crashed at $timestamp (exit code $exit_code). Repo: $REPO_ROOT. Please: (1) check the last 50 lines of server.log at $REPO_ROOT/server.log for the error, (2) verify launchd restarted the server successfully via 'launchctl list com.haidilao.server' and 'curl http://localhost:8000/api/runs', (3) if the server is not healthy, investigate and fix the root cause, (4) report back to Hongming on Telegram with what happened and the current status."

    /opt/homebrew/bin/openclaw cron add \
        --name "server-crash-$(date +%s)" \
        --at "1m" \
        --session isolated \
        --message "$alert_message" \
        --announce \
        --timeout-seconds 300 \
        --delete-after-run \
        && log "OpenClaw cron wake scheduled" \
        || log_err "OpenClaw cron wake failed (non-fatal)"

    log "Crash alert complete"
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
log "========================================="
log "Starting Haidilao automation server"
log "Repo:   $REPO_ROOT"
log "uv:     $(/Users/hongming-claw/.local/bin/uv --version 2>/dev/null || echo 'unknown')"
log "PID:    $$"
log "========================================="

cd "$REPO_ROOT"

# Run the server — capture exit code without triggering set -e
set +e
/Users/hongming-claw/.local/bin/uv run --project server python -m server
SERVER_EXIT=$?
set -e

log "Server process exited with code $SERVER_EXIT"

if [ "$SERVER_EXIT" -eq 0 ]; then
    log "Clean shutdown (code 0) — no crash alert"
else
    log_err "Abnormal exit (code $SERVER_EXIT) — alerting"
    send_crash_alert "$SERVER_EXIT"
fi

log "server-start.sh exiting with code $SERVER_EXIT"
exit $SERVER_EXIT
