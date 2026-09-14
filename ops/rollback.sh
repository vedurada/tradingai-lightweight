#!/bin/bash
# B.3 Fast rollback: checkout previous commit, reinstall, restart, verify
set -euo pipefail

echo "=== B.3 Fast Rollback ==="

PREV_COMMIT=$(git rev-parse HEAD~1)
echo "Rolling back to $PREV_COMMIT"
git checkout "$PREV_COMMIT" 2>/dev/null || git checkout "$PREV_COMMIT"
pip install -r requirements.txt 2>/dev/null || true
systemctl restart tradingai-api 2>/dev/null || true
sleep 5

if curl -sf http://127.0.0.1:8000/api/health 2>/dev/null | grep -q '"status": "ok"'; then
    echo "ROLLBACK OK: API healthy after rollback to $PREV_COMMIT"
else
    echo "ROLLBACK FAILED: API not healthy after rollback"
    echo "Restoring $PREV_COMMIT..."
    git checkout main 2>/dev/null || git checkout main
    systemctl restart tradingai-api 2>/dev/null || true
    exit 1
fi
