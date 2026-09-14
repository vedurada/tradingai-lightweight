#!/bin/bash
# Pre-commit hook: verify no model files modified
set -e
MODIFIED=$(git diff --name-only --cached 2>/dev/null | grep -E "backend/(regime|strategies|indicators|options|outlook|scenarios|ai_outlook|backtest)\.py" || true)
if [ -n "$MODIFIED" ]; then
    echo "FAIL: model file modification detected:"
    echo "$MODIFIED"
    exit 1
fi
echo "PASS: no model files modified"
