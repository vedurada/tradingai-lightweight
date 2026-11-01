# Phase 5.5 — No-Lookahead and Entry-Candle Audit

## Entry-Candle Handling Comparison

| Aspect | Backtest | Live Paper Engine |
|--------|----------|-------------------|
| Signal detection | Requires 3 completed candles (candles[i-2], i-1, i) | Same |
| Entry candle | candles[i+1] (next candle) | Same (or computed as signal+5min if not in DB) |
| Entry price | candles[i+1].open (historical) | Provider forming candle open (live) |
| First eligible candle for stop/target | Entry candle (idx+1) | Entry candle (idx+1) |
| Exit timestamp | First candle where stop/target hit | Same |
| Exit price | Stop or target level | Same |

## Lookahead Safeguards

| Check | Result | Evidence |
|-------|--------|----------|
| Signal uses only completed candles | PASS | `_scan_signals()` iterates completed candle triples |
| No future candle data used | PASS | Entry uses `candles[idx+1]['open']` — next candle, not current |
| Entry candle not required for signal detection | PASS | Phase 3.5 added last-candle detection |
| Entry price from live provider at decision time | PASS | `_get_entry_price_from_provider()` queries yfinance |
| Stale data rejected | PASS | `validate_candle()` rejects stale (>20 min) candles |
| No retrospective fills | PASS | Entry price = historical candle open (verified all 10 signals) |

## Candle Gap and Timezone Handling

| Check | Result | Evidence |
|-------|--------|----------|
| Timezone consistency | PASS | All timestamps use Asia/Kolkata (+05:30) |
| Midnight boundary | PASS | `timestamp[:10]` correctly extracts date portion |
| Missing candle gaps | NOT TESTED | No test verifies missing candles don't produce false signals |
| Forming candle exclusion | PASS | `is_complete=1` filter in market_candles_5m |

## Prefix-Invariance

| Check | Result | Evidence |
|-------|--------|----------|
| Signals at time t identical with/without future candles | PASS | 9/9 look-ahead tests pass (Phase 5.2) |
| Triple-scan signals prefix-invariant | PASS | Verified in Phase 5.2 Test 7 |
| Last-candle detection position-dependent | EXPECTED | Live-only feature, inherently position-dependent |
