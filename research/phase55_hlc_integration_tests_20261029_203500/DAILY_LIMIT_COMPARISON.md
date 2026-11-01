# Phase 5.5 — Daily Limit and Position Policy Comparison

## Current Mode C (Baseline)

| Aspect | Value |
|--------|-------|
| Rule | One open position per instrument at a time |
| Enforcement | `has_open_position()` in `paper_scalp_live.py` |
| Trade count (3 days) | 63 (40 NIFTY + 23 BANKNIFTY) |
| Blocked signals | 36 (Mode C: position already open) |
| Win rate | 57.14% |
| Net points | +713.94 |

## Proposed Daily Limit (Not Implemented)

| Aspect | Value |
|--------|-------|
| Rule | Maximum N trades per instrument per day |
| Enforcement | Would check `daily_trade_locks` before creating trade |
| Trade count (1/day, 3 days) | ~6 (1 per instrument per day) |
| Blocked signals | ~57 additional (36 Mode C + ~21 daily limit) |

## Comparison

| Policy | Trades | Win Rate | Points | Notes |
|--------|--------|----------|--------|-------|
| Mode C (current) | 63 | 57.14% | 713.94 | Baseline |
| Daily limit 1/day | ~6 | TBD | TBD | Not reproduced from ledger |
| Daily limit disabled | 99 | TBD | TBD | All signals become trades |

## Note

The "approximately 6 trades" estimate for daily limit 1/day is NOT verified. The Phase 5.1 ledger shows 63 trades with Mode C (one open position at a time). With a daily limit of 1, the count would be at most 6 (one per instrument per day, 3 days × 2 instruments), but the actual number depends on which signals would be selected (first per day) and their outcomes.

Historical three-day results are too small to establish robust strategy performance.
