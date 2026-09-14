#!/bin/bash
# TradingAI Rollback Script
# Rollback to the previous commit and restart the API.
# Usage: ./ops/rollback.sh
#
# Fast rollback (< 2 minutes). Keeps last 3 commits reachable.

set -euo pipefail

echo "=== TradingAI Rollback ==="

# Verify we have a previous commit to rollback to
PREV_COMMIT=$(git rev-parse HEAD~1 2>/dev/null || echo "")
if [ -z "$PREV_COMMIT" ]; then
    echo "ERROR: No previous commit found. Cannot rollback."
    exit 1
fi

echo "Current commit: $(git rev-parse --short HEAD)"
echo "Rolling back to: $PREV_COMMIT"

# Rollback code
git checkout "$PREV_COMMIT" -- .

# Reinstall dependencies
echo "Reinstalling dependencies..."
pip3 install -r ops/requirements.txt

# Restart API
echo "Restarting API..."
sudo systemctl restart tradingai-api

# Wait for API to come up
sleep 5

# Verify health
echo "Verifying health..."
HEALTH=$(curl -sf http://127.0.0.1:8000/api/health 2>/dev/null || echo "")
if echo "$HEALTH" | grep -q '"status": "ok"'; then
    echo "=== Rollback successful ==="
    echo "Rolled back to: $PREV_COMMIT"
    echo "API is healthy"
else
    echo "=== Rollback FAILED ==="
    echo "API health check failed. Manual investigation required."
    echo "Current health response: $HEALTH"
    exit 1
fi
