# Phase 5.8 — Trade Limit Design

## Current Baseline (Mode C)

| Aspect | Value |
|--------|-------|
| Rule | One open position per instrument at a time |
| Enforcement | `has_open_position()` in `paper_scalp_live.py` |
| Trade count (3 days) | 63 (40 NIFTY + 23 BANKNIFTY) |
| Blocked signals | 36 (Mode C: position already open) |
| Win rate | 57.14% |
| Net points | +713.94 |

## Daily Limit Design

### Configuration (Proposed, Not Implemented)

```json
{
  "MAX_OPEN_POSITIONS_PER_INSTRUMENT": 1,
  "MAX_TRADES_PER_INSTRUMENT_PER_DAY": null,
  "DAILY_LIMIT_ENABLED": false
}
```

### Behavior Matrix

| Setting | Trades Created | Notes |
|---------|---------------|-------|
| Daily limit disabled (null) | 63 (all signals) | Current baseline |
| Daily limit 1/day | ~6 (estimate) | First signal per instrument per day |
| Daily limit 2/day | ~12 (estimate) | First 2 signals per instrument per day |
| Daily limit 3/day | ~18 (estimate) | First 3 signals per instrument per day |

### Historical Simulation (Daily Limit 1/Day)

**Selection rule:** For each instrument and each day, select the FIRST signal (by signal_time). All subsequent signals on that instrument/day are blocked.

**Calculation:** The Phase 5.1 ledger shows 63 trades over 3 days (Oct 27-29, 2026). With daily limit 1/day:
- Maximum possible: 3 days × 2 instruments = 6
- Actual: depends on which signals are first per day

**Status: UNVERIFIED.** The exact count cannot be recalculated from the available ledger. The Phase 5.1 report does not contain per-day, per-instrument signal timestamps in machine-readable format. The estimate of ~6 trades is based on the maximum possible (6) and the assumption that every instrument has at least one signal per day.

### Critical Constraints

1. **Daily limit applies to NEW trade creation only** — exit monitor must continue managing existing open positions regardless of daily limit status.
2. **Mode C (concurrent position) is preserved** — daily limit is an ADDITIONAL constraint, not a replacement.
3. **Counter recovery on restart** — daily count must be recovered from `paper_trades` table (count trades for today).
4. **Default: disabled** — requires explicit opt-in via configuration.

### Implementation Notes (Future Deployment)

1. Add `daily_trade_locks` table check in `paper_scalp_live.py` before `try_create_trade()`
2. Read `MAX_TRADES_PER_INSTRUMENT_PER_DAY` from settings or env var
3. Default: disabled (current behavior)
4. Counter recovery: on restart, count existing trades for today from `paper_trades`
