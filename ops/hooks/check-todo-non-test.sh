#!/bin/bash
# Pre-commit hook: check for TODO in non-test files
set -e
FOUND=$(rg -n "TODO:" backend/ config/ ops/ deploy-vm.sh 2>/dev/null | rg -v "test_" || true)
if [ -n "$FOUND" ]; then
    echo "FAIL: TODO found in non-test file:"
    echo "$FOUND"
    exit 1
fi
echo "PASS: no TODO in non-test files"
