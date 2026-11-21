#!/usr/bin/env bash
# Pre-market token check for BOTH brokers the scanners can select.
# Read-only: never exchanges tokens, never restarts services, never prints
# secrets. Runs as root from tradingai-token-check.service at 08:45 IST.
set -uo pipefail

LOG="/opt/tradingai/logs/token_check.log"
STATUS="/opt/tradingai/logs/token_status.txt"
ts=$(date '+%Y-%m-%d %H:%M:%S %Z')

mkdir -p /opt/tradingai/logs

# The effective broker for all scanners and the API is mStock. Check it first:
# a valid Zerodha token is irrelevant while the fleet is mapped to mStock.
mstock_out=$(/usr/local/sbin/broker-gateway probe --broker mstock 2>&1)
mstock_rc=$?
if [[ $mstock_rc -eq 0 ]]; then
  MSTOCK="MSTOCK_VALID"
else
  MSTOCK="MSTOCK_INVALID — run: sudo /usr/local/sbin/mstock_session.py --mode totp"
fi

# Zerodha remains the default mapping and is needed if a scanner is switched.
zerodha_out=$(/opt/tradingai/refresh_token.sh --check 2>&1)
zerodha_rc=$?
if [[ $zerodha_rc -eq 0 ]]; then
  ZERODHA="ZERODHA_VALID"
else
  ZERODHA="ZERODHA_INVALID — run: sudo /opt/tradingai/refresh_token.sh <REQUEST_TOKEN>"
fi

{
  printf '%s %s | %s\n' "$ts" "$MSTOCK" "$ZERODHA"
  if [[ $mstock_rc -ne 0 ]]; then
    printf '%s\n' "$mstock_out" | tail -5
  fi
  if [[ $zerodha_rc -ne 0 ]]; then
    printf '%s\n' "$zerodha_out" | tail -5
  fi
} | tee -a "$LOG" > "$STATUS"

# Overall RC is driven by the effective broker only; the token-check service is
# informational and ignores it, but keeping it meaningful helps manual runs.
[[ $mstock_rc -eq 0 ]]
