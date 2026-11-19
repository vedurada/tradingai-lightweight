#!/bin/bash
# One-shot post-open verification for sma9_1min_poll.
#
# Waits until a given IST wall-clock time (default 09:22, i.e. after the first
# two entry-window scans), then samples the unit, log, scan_state heartbeat
# (twice, 70s apart, to show the 60s cadence), trades/open positions and API,
# and appends everything to /tmp/post_open_sma91m_<date>.log.
#
# Usage: ops/post_open_check.sh [HH:MM]
set -u
TARGET_TIME="${1:-09:22}"
OUT="/tmp/post_open_sma91m_$(date +%Y%m%d).log"
SSH="ssh -t -o StrictHostKeyChecking=no -o ConnectTimeout=20 -i /Users/satya/.ssh/oci_key ubuntu@129.159.224.81"

now=$(date +%s)
target=$(date -j -f "%Y-%m-%d %H:%M:%S" "$(date +%Y-%m-%d) ${TARGET_TIME}:00" +%s)
sleep $(( target - now > 0 ? target - now : 0 ))

{
  echo "===== $($SSH 'TZ=Asia/Kolkata date' 2>/dev/null) ====="
  echo "--- unit ---"
  $SSH 'systemctl is-active tradingai-sma9-1min-poll-scanner; systemctl show tradingai-sma9-1min-poll-scanner -p NRestarts -p ActiveEnterTimestamp' 2>/dev/null
  echo "--- log (last 25) ---"
  $SSH 'tail -n 25 /opt/tradingai/logs/live_sma9_1min_poll_scanner.log' 2>/dev/null
  echo "--- scan_state ---"
  $SSH 'sudo sqlite3 /opt/tradingai/database/sma9_1min_poll.db "select value from sma9_1min_poll_scan_state where key=\"live_status\";"' 2>/dev/null | python3 -c '
import sys, json
raw = sys.stdin.read().strip()
try:
    d = json.loads(raw)
except Exception:
    print("RAW:", raw[:400]); raise SystemExit
for k in ("status", "market_open", "last_scan_at", "last_scan_age_seconds",
          "actual_interval_seconds", "poll_seconds", "spot", "atm_strike",
          "expiry", "errors", "today"):
    print(f"  {k}: {d.get(k)}")
for opt in ("CE", "PE"):
    o = (d.get("options") or {}).get(opt) or {}
    print(f"  {opt}: ltp={o.get(\"ltp\")} sma9={o.get(\"sma9\")} "
          f"A={o.get(\"condition_a\")} B={o.get(\"condition_b\")} "
          f"signal={o.get(\"signal\")} position={o.get(\"position\")}")
'
  echo "--- cadence sample 1 -> 2 (70s apart) ---"
  $SSH 'sudo sqlite3 /opt/tradingai/database/sma9_1min_poll.db "select updated_at from sma9_1min_poll_scan_state where key=\"live_status\";"' 2>/dev/null
  sleep 70
  $SSH 'sudo sqlite3 /opt/tradingai/database/sma9_1min_poll.db "select updated_at from sma9_1min_poll_scan_state where key=\"live_status\";"' 2>/dev/null
  echo "--- trades / open positions ---"
  $SSH 'sudo sqlite3 -header /opt/tradingai/database/sma9_1min_poll.db "select trade_id,option_type,entry_price,exit_price,pnl_points,exit_reason,trade_date from sma9_1min_poll_trades order by entry_timestamp desc limit 10; select option_type,trade_id,entry_price,stop_price,hwm,be_locked from sma9_1min_poll_open_positions;"' 2>/dev/null
  echo "--- API ---"
  $SSH 'curl -sk -H "Host: tradingai.in" "https://127.0.0.1/api/sma9-1min-poll/scanner-status" | head -c 900' 2>/dev/null
  echo
  echo "--- page ---"
  $SSH 'curl -sk -o /dev/null -w "%{http_code}\n" -H "Host: tradingai.in" https://127.0.0.1/live/sma9-1min-poll/' 2>/dev/null
} >> "$OUT" 2>&1
echo "done" >> "$OUT"
