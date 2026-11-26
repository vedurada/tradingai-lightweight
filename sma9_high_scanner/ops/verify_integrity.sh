#!/usr/bin/env bash
# Verify that the SMA9 HIGH scanner code still matches its locked SHA256 manifest.
# Read-only; safe to run as any user.
set -uo pipefail

ROOT="/opt/tradingai/sma9_high_scanner"
cd "$ROOT" 2>/dev/null || {
  echo "SMA9 HIGH INTEGRITY FAILURE: missing $ROOT"
  exit 1
}

if [[ ! -f MANIFEST.sha256 ]]; then
  echo "SMA9 HIGH INTEGRITY FAILURE: MANIFEST.sha256 missing"
  exit 1
fi

if sha256sum -c --quiet MANIFEST.sha256; then
  echo "SMA9 HIGH integrity OK $(date -Is)"
  exit 0
fi

echo "SMA9 HIGH INTEGRITY FAILURE $(date -Is)"
exit 1
