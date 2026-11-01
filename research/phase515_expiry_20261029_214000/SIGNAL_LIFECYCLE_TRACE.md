# Phase 5.15 — Signal Lifecycle Trace

## Complete Path

```
1. Candle completion (market_candles_5m, is_complete=1)
   └── timestamp = candle start time (e.g., 09:15:00)
   └── candle covers [09:15, 09:20)
   └── ingested_at = when collector persisted it

2. Signal detection (scalp_engine._scan_signals)
   └── Requires 3 consecutive 5m candles with same-direction H/L/C
   └── Signal fires on 3rd confirming candle
   └── Signal candle timestamp = 3rd candle's open time
   └── Signal candle completes 5 min later

3. Signal availability
   └── After 3rd candle completes (signal_time + 5 min)
   └── In live: after collector ingests the candle (~9s median)
   └── In backtest: instant (all candles available)

4. Entry price resolution
   └── Entry candle = signal candle + 1 (next 5-min candle)
   └── Entry price = entry candle's open
   └── In live: from provider (forming candle) or DB (completed candle)
   └── In backtest: historical candle open

5. Entry guard (_entry_time_guard)
   └── Checks: now > entry_time + 5 min → expired
   └── Does NOT check: signal age, session date, future-dated
   └── Does NOT check: overnight carry

6. Trade creation (try_create_trade)
   └── Mode C: one open position per instrument
   └── Deterministic trade_id (SHA-1 of link_key)
   └── INSERT INTO paper_trades (PK = trade_id)

7. Expiry (mark_expired)
   └── Sets status = 'EXPIRED' in scalp_signals
   └── Only called when entry guard returns 'expired'

8. Session reset
   └── No automatic session reset
   └── Mode C persists across sessions (open positions remain)
   └── Signal status persists in scalp_signals table
```

## Timestamp Semantics

| Field | Meaning | Example |
|-------|---------|---------|
| signal_time | 3rd confirming candle's open | 2026-07-07T15:25:00 |
| signal candle end | signal_time + 5 min | 2026-07-07T15:30:00 |
| entry_time | Next candle's open | 2026-07-08T09:15:00 |
| entry candle end | entry_time + 5 min | 2026-07-08T09:20:00 |
| exit_time | Exit candle's timestamp | 2026-07-08T09:15:00 |

## Entry Guard Callers

1. `paper_scalp_live.py:run_once()` — calls `_entry_time_guard(entry_time_s, now)` for each signal
2. No other callers found

## Entry Guard Checks

| Check | Implemented | Notes |
|-------|------------|-------|
| Missing entry time | YES | Returns 'failed', 'missing_entry_time' |
| Bad format | YES | Returns 'failed', 'bad_entry_time' |
| Timezone handling | YES | Naive assumed IST |
| Entry window (5 min) | YES | now > entry_time + 5 min → 'expired' |
| Signal age | NO | Not checked |
| Session date | NO | Not checked |
| Future-dated signal | NO | Not checked |
| Signal candle completion | NO | Assumed completed |
| Overnight carry | NO | Not checked (entry_time is today's candle) |

## mark_expired Behavior

- Sets status = 'EXPIRED' in scalp_signals table
- Only called when entry guard returns 'expired'
- Does not prevent re-processing (signal remains in DB)
- Does not clean up or archive expired signals
