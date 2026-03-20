#!/usr/bin/env bash
# =============================================================================
# server-start.sh — Haidilao automation server launcher with crash alerting
#
# Managed by launchd (com.haidilao.server). launchd handles restart via
# KeepAlive. This script:
#   1. Detects whether this is a fresh start or a crash recovery (via flag file)
#   2. On crash recovery: waits for the server to become healthy, then sends
#      a ✅ "server recovered" message to Lark + notifies the OpenClaw agent
#   3. On crash: sends 🔴 Lark alert + wakes OpenClaw agent to investigate
#      and report back on TUI
#
# Full crash flow:
#   server crashes (exit != 0)
#     → send_crash_alert(): Lark 🔴 to hongming + OpenClaw cron agentTurn
#     → writes CRASH_FLAG_FILE
#     → script exits with original code
#     → launchd restarts after ThrottleInterval (30s)
#     → next run detects flag → waits for healthy → send_recovery_notice()
#     → agent reports back on TUI with diagnosis
# =============================================================================

set -euo pipefail

REPO_ROOT="/Users/hongming-claw/haidilao-automation-monorepo"
CRASH_FLAG_FILE="/tmp/haidilao-server-crashed.flag"

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
# Send a Lark text message to the hongming chat
# ---------------------------------------------------------------------------
lark_send() {
    local message="$1"
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
        with LarkClient(app_id=app_id, app_secret=app_secret) as c:
            c.send_text($(python3 -c "import json,sys; print(json.dumps(sys.argv[1]))" "$message"), chat_id=chat_id)
        print('Lark message sent')
    else:
        print('Lark not configured, skipping', file=sys.stderr)
except Exception as e:
    print(f'Lark send failed: {e}', file=sys.stderr)
" 2>>"$REPO_ROOT/server.log" || true
}

# ---------------------------------------------------------------------------
# Wait for the server to become healthy on :8000
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
# Recovery notice — sent on first healthy boot after a crash
# ---------------------------------------------------------------------------
send_recovery_notice() {
    local crash_info
    crash_info=$(cat "$CRASH_FLAG_FILE" 2>/dev/null || echo "unknown crash")
    local timestamp
    timestamp=$(date '+%Y-%m-%d %H:%M:%S %Z')

    log "Server recovered — sending recovery notice"

    # 1. Lark recovery message
    lark_send "✅ 海底捞自动化服务器已恢复

时间: $timestamp
原崩溃: $crash_info

服务器已重启并通过健康检查。OpenClaw 正在调查崩溃原因并将在 TUI 中报告。"

    # 2. Wake agent in isolated session — instruct it to investigate and report on TUI
    local recovery_message="✅ RECOVERY: Haidilao automation server has recovered at $timestamp after crash ($crash_info). IMPORTANT RULES: (1) Do NOT trigger any runs, commands, or automation. Do NOT call any API endpoints. Read-only investigation only. (2) Run ONLY this command to read the logs: exec command='tail -100 $REPO_ROOT/server.log' — nothing else. (3) Write a 2-4 sentence plain-language report: what caused the crash, current status, any action needed. (4) Send the report to Lark by running: exec command='cd $REPO_ROOT && uv run --project server python scripts/lark-notify.py hongming \"YOUR REPORT\"' — substitute your actual report. (5) Post the same report here on TUI. If you need Hongming's input, say so on TUI."

    /opt/homebrew/bin/openclaw cron add \
        --name "server-recovery-$(date +%s)" \
        --at "1m" \
        --session isolated \
        --message "$recovery_message" \
        --announce \
        --timeout-seconds 180 \
        --delete-after-run \
        && log "OpenClaw recovery cron scheduled" \
        || log_err "OpenClaw recovery cron failed (non-fatal)"

    # Clean up crash flag
    rm -f "$CRASH_FLAG_FILE"
    log "Crash flag removed"
}

# ---------------------------------------------------------------------------
# Crash alert — Lark 🔴 + OpenClaw agent wake for investigation
# ---------------------------------------------------------------------------
send_crash_alert() {
    local exit_code="$1"
    local timestamp
    timestamp=$(date '+%Y-%m-%d %H:%M:%S %Z')

    log "Server exited with code $exit_code — sending crash alert"

    # Write crash flag so next boot knows it's a recovery
    echo "exit_code=$exit_code at=$timestamp" > "$CRASH_FLAG_FILE"

    # 1. Lark 🔴 alert
    lark_send "🔴 海底捞自动化服务器崩溃

时间: $timestamp
退出码: $exit_code

launchd 正在自动重启服务器（30秒后）。
服务器恢复后将发送通知，OpenClaw 将在 TUI 中报告调查结果。"

    # 2. Wake OpenClaw agent to investigate (reports back on TUI)
    local alert_message="🔴 SYSTEM ALERT: Haidilao automation server crashed at $timestamp (exit code $exit_code). IMPORTANT: Do NOT trigger any runs, automation, or API calls. ONLY run: exec command='tail -100 $REPO_ROOT/server.log' to read the logs. Identify the crash cause. A second alert will fire after recovery — that is when you send the report to Lark and TUI."

    /opt/homebrew/bin/openclaw cron add \
        --name "server-crash-$(date +%s)" \
        --at "1m" \
        --session isolated \
        --message "$alert_message" \
        --announce \
        --timeout-seconds 180 \
        --delete-after-run \
        && log "OpenClaw crash investigation cron scheduled" \
        || log_err "OpenClaw crash cron failed (non-fatal)"

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

# Detect crash recovery
if [ -f "$CRASH_FLAG_FILE" ]; then
    log "⚠️  Crash flag detected — this is a recovery restart"
    log "Crash info: $(cat "$CRASH_FLAG_FILE")"
    IS_RECOVERY=1
else
    IS_RECOVERY=0
fi
log "========================================="

cd "$REPO_ROOT"

# Run the server — capture exit code without triggering set -e
set +e
/Users/hongming-claw/.local/bin/uv run --project server python -m server &
SERVER_PID=$!

# If this is a recovery restart, wait for healthy then notify
if [ "$IS_RECOVERY" -eq 1 ]; then
    # Give server a moment to start binding
    sleep 3
    if wait_for_healthy; then
        send_recovery_notice
    else
        log_err "Server failed to become healthy after crash recovery"
        lark_send "⚠️ 海底捞服务器重启后未能通过健康检查，请手动检查。"
    fi
fi

# Wait for server to exit
wait $SERVER_PID
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
