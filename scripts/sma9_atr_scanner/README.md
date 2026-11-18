# SMA9 ATR-Stop Scanner (standalone)

A paper-trading scanner that is a **fully isolated copy** of the SMA9 ATM
option scanner, with one change: the initial stop loss is scaled to the
option premium's own volatility instead of a fixed 5% of premium.

* Directory: `/opt/tradingai/sma9_atr_scanner`
* Database: `/opt/tradingai/database/sma9_atr.db`
* Service: `tradingai-sma9-atr-scanner.service`
* Log: `/opt/tradingai/logs/live_sma9_atr_scanner.log`
* Strategy id: `sma9_atr`
* Tables: `sma9_atr_trades`, `sma9_atr_open_positions`, `sma9_atr_scan_state`

It does not read, write, or restart any existing scanner. Paper only: no
orders are placed.

## Entry (identical to SMA9)

At a 5-minute candle boundary, for each of ATM CE and ATM PE:

* A) previous completed candle CLOSE > SMA9
* B) current forming candle OPEN > SMA9

Both must hold. Entry is a paper BUY at the live LTP.

## Exit

1. **ATR-scaled initial stop** (the only behavioural change)

   ```
   atr      = mean True Range of the option premium over 14 completed 5m candles
   distance = clamp(0.70 * atr, 5% * entry, 30% * entry)
   stop     = entry - distance
   ```

   When LTP <= stop, the trade is closed at the **actual live LTP**, not at
   the theoretical stop price. If ATR is unavailable (a contract with less
   than 15 completed candles), the stop falls back to 10% of entry and
   `stop_source = 'fallback_pct'`.

2. **Trailing stop** (unchanged): +5 activates breakeven, then ratchets at
   peak - 5; a one-time breakeven lock at +6 moves the stop to entry + 2.

3. No time-based exit; positions are held until the ATR stop or the trail.

## Why

The fixed 5% stop shrinks in absolute points as premium decays, while ATM
option noise stays roughly constant (~11-15 points). On 0-DTE days the stop
was 2.3 points against ~14 points of 5m noise, producing a 68% stop-out rate
and 39 of 65 trades inside losing streaks. Scaling the stop to premium ATR
keeps it outside the noise band on cheap contracts while staying close to
the old 5% distance on expensive ones.

## Run

```
sudo systemctl status tradingai-sma9-atr-scanner
sudo journalctl -u tradingai-sma9-atr-scanner -n 50
tail -f /opt/tradingai/logs/live_sma9_atr_scanner.log
```

## Pre-open verification

Two read-only checks can be run before the market opens:

```
# Simulated 09:15-09:26 session with a fake clock/feed, temp DB only
python3 scripts/sma9_atr_scanner/ops/dryrun_market_open.py

# Real Kite path: instruments -> expiry -> ATM contracts -> quotes ->
# candles -> SMA9 -> ATR stop preview (writes nothing)
python3 scripts/sma9_atr_scanner/ops/real_feed_check.py
```

The scanner is enabled at boot and `Restart=always`. It is also in the
`ALL_UNITS` restart list in `/opt/tradingai/refresh_token.sh`, so the daily
Zerodha token refresh restarts it with the new token, exactly like the other
scanners. The token is read once at process start, so a token refresh without
a restart would leave the process on the expired token.

## Report

The day-wise report (`/api/performance/daily`) includes this scanner under
the key `sma9_atr` from its first live trading day (2026-11-19).
