#!/usr/bin/env bash
# TradingAI deploy health gate — readiness first, then full health.
# B6.9: /api/ready (process alive, DB readable) is checked first with a short
# budget; only then the data-aware /api/health gate. Runs ON the VM as a
# script file (avoids SSH inline-quoting fragility).
# Exit 0 = healthy, 1 = still unhealthy after all attempts (prints last body).
set -uo pipefail
BASE="${1:-http://127.0.0.1:8000}"
TRIES="${2:-12}"
SLEEP_S="${3:-5}"
READY=""
for ((i = 1; i <= 3; i++)); do
    sleep 2
    READY=$(curl -sf --max-time 10 "$BASE/api/ready" 2>/dev/null || echo "")
    if echo "$READY" | grep -q '"ready": *true\|"ready":true'; then
        echo "READINESS PASS on attempt $i"
        break
    fi
    echo "READINESS attempt $i/3: response_len=${#READY}" >&2
done
if ! echo "$READY" | grep -q '"ready": *true\|"ready":true'; then
    echo "READINESS FAILED — process not ready, skipping health gate" >&2
    echo "$READY"
    exit 1
fi
HEALTH=""
for ((i = 1; i <= TRIES; i++)); do
    sleep "$SLEEP_S"
    HEALTH=$(curl -sf --max-time 10 "$BASE/api/health" 2>/dev/null || echo "")
    if echo "$HEALTH" | grep -q '"status": "ok"\|"status":"ok"'; then
        echo "HEALTH GATE PASS on attempt $i"
        exit 0
    fi
    echo "HEALTH GATE attempt $i/${TRIES}: response_len=${#HEALTH}" >&2
done
echo "HEALTH GATE FAILED after ${TRIES} attempts" >&2
echo "$HEALTH"
exit 1
