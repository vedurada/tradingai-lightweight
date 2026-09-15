#!/usr/bin/env bash
# TradingAI Health Check
# Checks all critical components and returns machine-readable status.
# Exit codes: 0=HEALTHY, 1=DEGRADED, 2=UNHEALTHY
set -uo pipefail

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DB_PATH="${TRADINGAI_DB_PATH:-$APP_DIR/database/tradingai.db}"
API_BASE="${API_BASE:-http://127.0.0.1:8000}"
LOG_FILE="${TRADINGAI_HEALTH_LOG:-$APP_DIR/logs/health.log}"
THRESHOLD_CRITICAL=$((60 * 60 * 3))

mkdir -p "$(dirname "$LOG_FILE")"

log() { echo "$(date -u +"%Y-%m-%dT%H:%M:%SZ") $1" >> "$LOG_FILE"; }

status="HEALTHY"
issues=""

check_api() {
    if curl -sf --max-time 5 "$API_BASE/api/health" > /dev/null 2>&1; then
        log "CHECK api: OK"
    else
        status="UNHEALTHY"
        issues="$issues api=down"
        log "CHECK api: FAIL"
    fi
}

check_api_ready() {
    if curl -sf --max-time 5 "$API_BASE/api/ready" 2>/dev/null | grep -q '"ready".*true\|"ready":true'; then
        log "CHECK api/ready: OK"
    else
        if [ "$status" != "UNHEALTHY" ]; then status="DEGRADED"; fi
        issues="$issues api/ready=unconfirmed"
        log "CHECK api/ready: DEGRADED"
    fi
}

check_database() {
    if [ ! -f "$DB_PATH" ]; then
        status="UNHEALTHY"
        issues="$issues database=missing"
        log "CHECK database: FAIL"
        return
    fi
    local size
    size=$(python3 -c "import os; print(os.path.getsize('$DB_PATH'))" 2>/dev/null || echo "0")
    if [ "$size" = "0" ]; then
        status="UNHEALTHY"
        issues="$issues database=empty"
        log "CHECK database: FAIL"
        return
    fi
    local tables
    tables=$(python3 -c "
import sqlite3
conn = sqlite3.connect('$DB_PATH')
count = conn.execute(\"SELECT COUNT(*) FROM sqlite_master WHERE type='table'\").fetchone()[0]
conn.close()
print(count)
" 2>/dev/null || echo "0")
    if [ "$tables" = "0" ]; then
        status="UNHEALTHY"
        issues="$issues database=empty_schema"
        log "CHECK database: FAIL"
        return
    fi
    log "CHECK database: OK ($tables tables, ${size} bytes)"
}

check_market_data() {
    local code
    code=$(curl -s -o /dev/null -w "%{http_code}" "$API_BASE/api/price/NIFTY" 2>/dev/null || echo "000")
    if [ "$code" = "200" ]; then
        log "CHECK market_data: OK"
    else
        if [ "$status" = "HEALTHY" ]; then status="DEGRADED"; fi
        issues="$issues market_data=unavailable"
        log "CHECK market_data: DEGRADED"
    fi
}

 check_vix() {
    local code
    code=$(curl -s -o /dev/null -w "%{http_code}" "$API_BASE/api/vix" 2>/dev/null || echo "000")
    if [ "$code" = "200" ]; then
        log "CHECK vix: OK"
    else
        if [ "$status" = "HEALTHY" ]; then status="DEGRADED"; fi
        issues="$issues vix=unavailable"
        log "CHECK vix: DEGRADED"
    fi
}

check_nginx() {
    if curl -sf --max-time 5 "http://tradingai.in" > /dev/null 2>&1 || curl -sf --max-time 5 "http://127.0.0.1" > /dev/null 2>&1; then
        log "CHECK nginx: OK"
    else
        if [ "$status" = "HEALTHY" ]; then status="DEGRADED"; fi
        issues="$issues nginx=unreachable"
        log "CHECK nginx: DEGRADED"
    fi
}

check_disk() {
    local usage
    usage=$(df / | tail -1 | awk '{print $5}' | tr -d '%')
    if [ "$usage" -gt 90 ]; then
        status="UNHEALTHY"
        issues="$issues disk=${usage}%"
        log "CHECK disk: FAIL ($usage%)"
    elif [ "$usage" -gt 75 ]; then
        if [ "$status" = "HEALTHY" ]; then status="DEGRADED"; fi
        issues="$issues disk=${usage}%"
        log "CHECK disk: DEGRADED ($usage%)"
    else
        log "CHECK disk: OK ($usage%)"
    fi
}

check_cron() {
    if crontab -l 2>/dev/null | grep -q "tradingai\|data_fetcher\|outlook"; then
        log "CHECK cron: OK"
    else
        if [ "$status" = "HEALTHY" ]; then status="DEGRADED"; fi
        issues="$issues cron=missing"
        log "CHECK cron: DEGRADED"
    fi
}

check_secrets() {
    if [ -f /etc/tradingai/groq.env ]; then
        local perms
        perms=$(stat -c %a /etc/tradingai/groq.env 2>/dev/null || echo "999")
        if [ "$perms" != "600" ] && [ "$perms" != "400" ]; then
            if [ "$status" = "HEALTHY" ]; then status="DEGRADED"; fi
            issues="$issues secrets=world_readable ($perms)"
            log "CHECK secrets: DEGRADED (mode $perms)"
        else
            log "CHECK secrets: OK (mode $perms)"
        fi
    else
        log "CHECK secrets: SKIP (file not found)"
    fi
}

check_api_health_detail() {
    local body
    body=$(curl -s --max-time 5 "$API_BASE/api/health" 2>/dev/null || echo "{}")
    local health_status
    health_status=$(echo "$body" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('status','unknown'))" 2>/dev/null || echo "unknown")
    if [ "$health_status" = "ok" ]; then
        log "CHECK api_health_detail: OK"
    else
        if [ "$status" = "HEALTHY" ]; then status="DEGRADED"; fi
        issues="$issues api_health=$health_status"
        log "CHECK api_health_detail: DEGRADED"
    fi
}

check_api
check_api_ready
check_database
check_market_data
 check_vix
check_nginx
check_disk
check_cron
check_secrets
check_api_health_detail

timestamp=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

if [ "$status" = "HEALTHY" ]; then
    exit_code=0
elif [ "$status" = "DEGRADED" ]; then
    exit_code=1
else
    exit_code=2
fi

cat <<EOF
{"status":"$status","timestamp":"$timestamp","issues":"$issues"}
EOF

log "HEALTH CHECK: $status ($issues)"
exit $exit_code