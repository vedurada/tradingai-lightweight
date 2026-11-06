#!/usr/bin/env bash
# Unlock the SMA9 scanner code for an approved maintenance change.
#
# After editing/testing, ALWAYS re-run ops/lock_code.sh.
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "ERROR: run with sudo: sudo $0" >&2
  exit 1
fi

ROOT="/opt/tradingai/sma9_scanner"

chattr -R -i "$ROOT" 2>/dev/null || true
chown -R root:root "$ROOT"
find "$ROOT" -type d -exec chmod 0755 {} +
find "$ROOT" -type f -name '*.sh' -exec chmod 0755 {} +
find "$ROOT" -type f ! -name '*.sh' -exec chmod 0644 {} +

echo "UNLOCKED: $ROOT"
echo "Files are root-owned. Edit with sudo (or chown temporarily), then run:"
echo "  sudo $ROOT/ops/lock_code.sh"
