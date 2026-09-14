#!/bin/bash
# Pre-commit hook: check for print in non-test files
set -e
FOUND=$(rg -n "print\(" backend/ config/ ops/ deploy-vm.sh 2>/dev/null | rg -v "test_" || true)
if [ -n "$FOUND" ]; then
    echo "FAIL: print() found in non-test file:"
    echo "$FOUND"
    exit 1
fi
echo "PASS: no print in non-test files"
