#!/usr/bin/env bash
# Pre-market mStock connectivity check for the isolated sma9_live service.
# Read-only: never exchanges tokens, never restarts services, never prints
# secrets. Runs as root from tradingai-token-check.service at 08:45 IST.
set -uo pipefail

LOG="/opt/tradingai/logs/token_check.log"
STATUS="/opt/tradingai/logs/token_status.txt"
ts=$(date '+%Y-%m-%d %H:%M:%S %Z')

mkdir -p /opt/tradingai/logs

mstock_out=$(/usr/local/sbin/broker-gateway probe --broker mstock 2>&1)
mstock_rc=$?
if [[ $mstock_rc -eq 0 ]]; then
  MSTOCK="MSTOCK_VALID"
else
  MSTOCK="MSTOCK_INVALID — run: sudo /usr/local/sbin/mstock_session.py --mode totp"
fi

{
  printf '%s %s\n' "$ts" "$MSTOCK"
  if [[ $mstock_rc -ne 0 ]]; then
    printf '%s\n' "$mstock_out" | tail -5
  fi
} | tee -a "$LOG" > "$STATUS"

[[ $mstock_rc -eq 0 ]]
