#!/usr/bin/env bash
# Lock the SMA9 scanner code.
#
# Result:
#   * every file is owned by root
#   * directories are 0555, shell tools are 0555, other files are 0444
#   * every file and directory is immutable (chattr +i)
#   * a SHA256 manifest is written and locked with the code
#
# Only root can run this.  To make an approved change, run unlock_code.sh
# first, edit/test, then run this script again.
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "ERROR: run with sudo: sudo $0" >&2
  exit 1
fi

ROOT="/opt/tradingai/sma9_scanner"
cd "$ROOT"

# Clear any previous immutability so the manifest can be rebuilt.
chattr -R -i "$ROOT" 2>/dev/null || true

# Remove bytecode caches; the service runs with PYTHONDONTWRITEBYTECODE=1.
find "$ROOT" -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
find "$ROOT" -type f -name '*.pyc' -delete 2>/dev/null || true

# SHA256 manifest over every shipped file except the manifest/lock metadata.
find . -type f \
  ! -name 'MANIFEST.sha256' \
  ! -name 'LOCKED.json' \
  ! -path './.git/*' \
  | LC_ALL=C sort \
  | xargs sha256sum > MANIFEST.sha256

MANIFEST_HASH=$(sha256sum MANIFEST.sha256 | awk '{print $1}')
FILE_COUNT=$(find . -type f ! -name 'MANIFEST.sha256' ! -name 'LOCKED.json' | wc -l)

cat > LOCKED.json <<EOF
{
  "locked_at": "$(date -Is)",
  "locked_by": "lock_code.sh",
  "root": "$ROOT",
  "manifest_sha256": "$MANIFEST_HASH",
  "file_count": $FILE_COUNT,
  "policy": "root-owned, read-only, immutable (chattr +i); service runs as unprivileged user sma9"
}
EOF

# Root ownership + read-only / executable modes.
chown -R root:root "$ROOT"
find "$ROOT" -type d -exec chmod 0555 {} +
find "$ROOT" -type f -name '*.sh' -exec chmod 0555 {} +
find "$ROOT" -type f ! -name '*.sh' -exec chmod 0444 {} +

# Immutable flag: even root must run unlock_code.sh before editing.
chattr -R +i "$ROOT"

echo "LOCKED: $ROOT"
echo "  manifest: $MANIFEST_HASH"
echo "  files:    $FILE_COUNT"
echo "  verify:   sudo $ROOT/ops/verify_integrity.sh"
