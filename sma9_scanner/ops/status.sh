#!/usr/bin/env bash
# One-shot health/status view for the locked SMA9 scanner.
set -uo pipefail

echo "=== service ==="
systemctl --no-pager --full status tradingai-sma9-scanner.service 2>/dev/null | sed -n '1,12p' || true
echo
echo "=== lock ==="
lsattr /opt/tradingai/sma9_scanner/app/live_sma9_scanner.py 2>/dev/null || true
stat -c '%U:%G %a %n' /opt/tradingai/sma9_scanner/app/live_sma9_scanner.py 2>/dev/null || true
echo
echo "=== integrity ==="
/opt/tradingai/sma9_scanner/ops/verify_integrity.sh || true
echo
echo "=== open positions ==="
sqlite3 -header -column /opt/tradingai/database/sma9.db \
  "SELECT option_type,trade_id,entry_price,entry_candle_start,entry_candle_end FROM sma9_open_positions;" 2>/dev/null || true
echo
echo "=== recent live trades ==="
sqlite3 -header -column /opt/tradingai/database/sma9.db \
  "SELECT trade_id,option_type,entry_timestamp,entry_price,exit_timestamp,exit_price,pnl_points,exit_reason FROM sma9_trades WHERE dataset='LIVE' ORDER BY entry_timestamp DESC LIMIT 10;" 2>/dev/null || true
