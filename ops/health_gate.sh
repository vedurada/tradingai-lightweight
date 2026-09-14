#!/usr/bin/env bash
# TradingAI deploy health gate — polls /api/health until status ok.
# Runs ON the VM as a script file (avoids SSH inline-quoting fragility).
# Exit 0 = healthy, 1 = still unhealthy after all attempts (prints last body).
set -uo pipefail
API="${1:-http://127.0.0.1:8000/api/health}"
TRIES="${2:-12}"
SLEEP_S="${3:-5}"
HEALTH=""
for ((i = 1; i <= TRIES; i++)); do
    sleep "$SLEEP_S"
    HEALTH=$(curl -sf --max-time 10 "$API" 2>/dev/null || echo "")
    if echo "$HEALTH" | grep -q '"status": "ok"\|"status":"ok"'; then
        echo "HEALTH GATE PASS on attempt $i"
        exit 0
    fi
    echo "HEALTH GATE attempt $i/${TRIES}: response_len=${#HEALTH}" >&2
done
echo "HEALTH GATE FAILED after ${TRIES} attempts" >&2
echo "$HEALTH"
exit 1
