#!/usr/bin/env bash
# security-scan.sh — Scan nginx access.log for suspicious activity in the last hour
# Usage: ./scripts/security-scan.sh
# Add to cron: 0 * * * * /Users/hongming-claw/haidilao-automation-monorepo/scripts/security-scan.sh >> /tmp/security-scan.log 2>&1

set -euo pipefail

ACCESS_LOG="/opt/homebrew/var/log/nginx/access.log"
THRESHOLD_AUTH_ERRORS=10     # IPs with >10 401/403 responses in the last hour
THRESHOLD_TRAVERSAL=5        # path traversal attempts in the last hour
THRESHOLD_404_PROBE=20       # 404s from same IP suggesting scanning

# ── Get last hour's log lines ────────────────────────────────────────────────
# nginx log format: IP - user [DD/Mon/YYYY:HH:MM:SS +ZZZZ] "METHOD path HTTP/x.x" status ...
HOUR_AGO=$(date -v-1H "+%d/%b/%Y:%H" 2>/dev/null || date -d "1 hour ago" "+%d/%b/%Y:%H")
RECENT_LINES=$(grep "$HOUR_AGO" "$ACCESS_LOG" 2>/dev/null || true)

if [[ -z "$RECENT_LINES" ]]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] No log lines found for the last hour (pattern: $HOUR_AGO)"
    exit 0
fi

echo "════════════════════════════════════════════════════════════════"
echo " Haidilao Security Scan — $(date '+%Y-%m-%d %H:%M:%S')"
echo " Log window: last hour (~${HOUR_AGO}:xx)"
echo "════════════════════════════════════════════════════════════════"

# ── 1. Unique IPs with 401/403 responses ─────────────────────────────────────
echo ""
echo "── Auth failures (401/403 per IP) ──────────────────────────────"
AUTH_FAILURES=$(echo "$RECENT_LINES" | grep -E '" (401|403) ' | awk '{print $1}' | sort | uniq -c | sort -rn)
if [[ -z "$AUTH_FAILURES" ]]; then
    echo "  None"
else
    FLAGGED=0
    while IFS= read -r line; do
        COUNT=$(echo "$line" | awk '{print $1}')
        IP=$(echo "$line" | awk '{print $2}')
        if (( COUNT > THRESHOLD_AUTH_ERRORS )); then
            echo "  ⚠️  SUSPICIOUS: $IP — $COUNT failures (threshold: $THRESHOLD_AUTH_ERRORS)"
            FLAGGED=$((FLAGGED + 1))
        else
            echo "       $IP — $COUNT failures"
        fi
    done <<< "$AUTH_FAILURES"
    if (( FLAGGED > 0 )); then
        echo "  → $FLAGGED IP(s) exceeded threshold"
    fi
fi

# ── 2. Path traversal attempts ───────────────────────────────────────────────
echo ""
echo "── Path traversal attempts ──────────────────────────────────────"
TRAVERSAL=$(echo "$RECENT_LINES" | grep -iE '(\.\./|%2e%2e|%252e|\.\.%2f|%2f\.\.)' | wc -l | tr -d ' ')
if (( TRAVERSAL >= THRESHOLD_TRAVERSAL )); then
    echo "  ⚠️  $TRAVERSAL traversal attempt(s) detected (threshold: $THRESHOLD_TRAVERSAL)"
    echo "$RECENT_LINES" | grep -iE '(\.\./|%2e%2e|%252e|\.\.%2f|%2f\.\.)' | awk '{print "    " $1 " → " $7}' | head -20
else
    echo "  $TRAVERSAL traversal attempt(s) (below threshold of $THRESHOLD_TRAVERSAL)"
fi

# ── 3. IPs probing non-existent paths (404s) ─────────────────────────────────
echo ""
echo "── Heavy 404 probing (same IP) ──────────────────────────────────"
PROBE_404=$(echo "$RECENT_LINES" | grep -E '" 404 ' | awk '{print $1}' | sort | uniq -c | sort -rn)
if [[ -z "$PROBE_404" ]]; then
    echo "  None"
else
    FLAGGED=0
    while IFS= read -r line; do
        COUNT=$(echo "$line" | awk '{print $1}')
        IP=$(echo "$line" | awk '{print $2}')
        if (( COUNT > THRESHOLD_404_PROBE )); then
            echo "  ⚠️  SUSPICIOUS: $IP — $COUNT 404s (threshold: $THRESHOLD_404_PROBE)"
            # Show which paths they hit
            echo "$RECENT_LINES" | grep -E '" 404 ' | grep "^$IP " | awk '{print "      " $7}' | sort | uniq -c | sort -rn | head -10
            FLAGGED=$((FLAGGED + 1))
        else
            echo "       $IP — $COUNT 404s"
        fi
    done <<< "$PROBE_404"
    if (( FLAGGED > 0 )); then
        echo "  → $FLAGGED IP(s) exceeded threshold"
    fi
fi

# ── 4. Top user agents (spot bots/scanners) ───────────────────────────────────
echo ""
echo "── Suspicious/scanner user agents ──────────────────────────────"
echo "$RECENT_LINES" | grep -iE '(zgrab|masscan|shodan|sqlmap|nikto|nmap|nuclei|curl/|python-requests|go-http-client|dirbuster|gobuster|wfuzz|hydra|metasploit)' \
    | awk -F'"' '{print $6}' | sort | uniq -c | sort -rn | head -10 \
    | while IFS= read -r line; do echo "  $line"; done
[[ -z "$(echo "$RECENT_LINES" | grep -iE '(zgrab|masscan|shodan|sqlmap|nikto|nmap|nuclei|curl/|python-requests|go-http-client|dirbuster|gobuster|wfuzz|hydra|metasploit)' 2>/dev/null)" ]] && echo "  None detected"

# ── Summary ──────────────────────────────────────────────────────────────────
echo ""
echo "── Summary ──────────────────────────────────────────────────────"
TOTAL=$(echo "$RECENT_LINES" | wc -l | tr -d ' ')
echo "  Total requests last hour: $TOTAL"
echo "  401+403 responses:        $(echo "$RECENT_LINES" | grep -cE '" (401|403) ' || true)"
echo "  404 responses:            $(echo "$RECENT_LINES" | grep -cE '" 404 ' || true)"
echo "  Traversal attempts:       $TRAVERSAL"
echo "════════════════════════════════════════════════════════════════"
