#!/bin/bash
# Pre-commit hook: check for bare except in non-test files
set -e
FOUND=$(rg -n "except\s*:" backend/ config/ ops/ deploy-vm.sh 2>/dev/null | rg -v "except Exception|except \(|except as|except:\s*#|except:\s*$" || true)
if [ -n "$FOUND" ]; then
    echo "FAIL: bare except found:"
    echo "$FOUND"
    exit 1
fi
echo "PASS: no bare except in non-test files"
