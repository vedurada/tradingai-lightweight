#!/usr/bin/env bash
# TradingAI Test Script
# Runs the complete test suite and reports results.
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$APP_DIR"

echo "=== TradingAI Test Suite ==="
echo "Python: $(python3 --version)"
echo "Working dir: $(pwd)"
echo ""

echo "--- Full test suite ---"
start_time=$(date +%s)
if python3 -m pytest tests/ -v --tb=short 2>&1; then
    result="PASS"
else
    result="FAIL"
fi
end_time=$(date +%s)
duration=$((end_time - start_time))

echo ""
echo "=== Result: $result ($duration seconds) ==="

if [ "$result" = "FAIL" ]; then
    exit 1
fi