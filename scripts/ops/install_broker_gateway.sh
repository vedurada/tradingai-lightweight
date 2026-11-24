#!/usr/bin/env bash
# Install or refresh the TradingAI broker gateway.
# This does not modify scanner code or restart scanners.
set -euo pipefail

REPO_ROOT="${1:-$(cd "$(dirname "$0")/../.." && pwd)}"
SRC="$REPO_ROOT/broker_gateway"
ROOT="/opt/tradingai"
DEST="$ROOT/broker_gateway"

[[ -d "$SRC" ]] || { echo "ERROR: missing $SRC" >&2; exit 1; }
[[ $EUID -eq 0 ]] || { echo "ERROR: run with sudo" >&2; exit 1; }

install -d -m 755 -o root -g root "$DEST"
cp -a "$SRC"/. "$DEST"/
# The daemon runs as root and imports modules from this tree. It must not be
# owner-writable by an unprivileged account (local privilege escalation).
chown -R root:root "$DEST"
find "$DEST" -type d -exec chmod 755 {} +
find "$DEST" -type f -exec chmod 644 {} +
chmod 755 "$DEST/daemon.py" "$DEST/cli.py"

install -d -m 755 -o root -g root "$DEST/config"
install -d -m 750 -o root -g ubuntu "$DEST/cache"

# The canonical mapping ships in the repo (broker_gateway/config/scanners.json)
# and is copied above. Never silently fall back to an empty mapping: that would
# send the live scanner to a stale default broker.
if [[ ! -f "$DEST/config/scanners.json" ]]; then
    echo "ERROR: missing canonical broker mapping $SRC/config/scanners.json" >&2
    exit 1
fi
chmod 644 "$DEST/config/scanners.json"

PURELIB="$(python3 -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')"
printf 'import sys; sys.path.insert(0, "%s/compat"); sys.path.append("%s")\n' "$DEST" "$ROOT" > "$PURELIB/broker_gateway.pth"
chmod 644 "$PURELIB/broker_gateway.pth"

install -o root -g root -m 700 "$DEST/cli.py" /usr/local/sbin/broker-gateway
install -o root -g root -m 644 "$DEST/ops/tradingai-broker-gateway.service" \
    /etc/systemd/system/tradingai-broker-gateway.service

systemctl daemon-reload
systemctl enable tradingai-broker-gateway.service >/dev/null
systemctl restart tradingai-broker-gateway.service

echo "Installed broker gateway $DEST"
echo "Scanner code was not changed. Restart a scanner only after selecting its broker:"
echo "  sudo broker-gateway use --scanner sma9_atr --broker mstock"
echo "  sudo systemctl restart tradingai-sma9-atr-scanner"
