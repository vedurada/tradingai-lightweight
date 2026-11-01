# Phase 5.6A — Trade Limit Policy Tests

## Current Mode C (Baseline)

| Aspect | Value |
|--------|-------|
| Rule | One open position per instrument at a time |
| Enforcement | `has_open_position()` in `paper_scalp_live.py` |
| Trade count (3 days) | 63 (40 NIFTY + 23 BANKNIFTY) |
| Blocked signals | 36 (Mode C: position already open) |
| Win rate | 57.14% |
| Net points | +713.94 |

## Proposed Daily Limit Design

### Configuration

```json
{
  "MAX_OPEN_POSITIONS_PER_INSTRUMENT": 1,
  "MAX_TRADES_PER_INSTRUMENT_PER_DAY": 1,
  "DAILY_LIMIT_ENABLED": true
}
```

### Behavior

| Setting | Trades Created | Notes |
|---------|---------------|-------|
| Daily limit disabled | 63 (all signals) | Current Mode C behavior |
| Daily limit 1/day | ~6 (1 per instrument per day) | First signal per instrument per day |
| Daily limit 2/day | ~12 | First 2 signals per instrument per day |
| Daily limit 3/day | ~18 | First 3 signals per instrument per day |

### Daily Limit 1/Day Historical Simulation

**Selection rule:** For each instrument and each day, select the FIRST signal (by signal_time). All subsequent signals on that instrument/day are blocked.

**Calculation from Phase 5.1 ledger (63 trades):**

The Phase 5.1 ledger shows 63 trades over 3 days (Oct 27–29, 2026). With daily limit 1/day:
- Maximum possible trades: 3 days × 2 instruments = 6
- Actual trades would be: first signal per instrument per day = at most 6
- The exact number depends on which signals would be selected (first per day) and whether those signals resulted in trades

**NOTE:** The exact count of 6 trades with daily limit 1/day is NOT verified from the ledger. The ledger does not contain per-day, per-instrument signal timestamps in a machine-readable format. This is an estimate based on the maximum possible (6) and the assumption that every instrument has at least one signal per day.

### Test Cases

| Test ID | Scenario | Expected | Actual | Result |
|---------|----------|----------|--------|--------|
| TL1 | Daily limit disabled | All signals become trades | 63 trades | PASS (design) |
| TL2 | Daily limit 1/day | First signal per instrument/day | ~6 trades (estimate) | PASS (design) |
| TL3 | Daily limit 2/day | First 2 signals per instrument/day | ~12 trades (estimate) | PASS (design) |
| TL4 | Daily limit 3/day | First 3 signals per instrument/day | ~18 trades (estimate) | PASS (design) |
| TL5 | Repeated signals on same day | Only first N created | N trades | PASS (design) |
| TL6 | Repeated scheduler execution | No duplicate trades | 1 trade per signal | PASS (design) |
| TL7 | Restart behavior | Daily counter recovered from DB | Counter matches DB | PASS (design) |
| TL8 | Exit monitor not blocked | Existing trades managed | Exits processed | PASS (design) |

### Critical Constraint

**A daily limit must NOT prevent the exit monitor from managing existing open positions.**

The daily limit only applies to NEW trade creation. The `monitor()` function in `PaperTradeEngine` must continue to check all ACTIVE/OPEN trades for stop/target hits regardless of daily limit status.

### Mode C Baseline Preserved

The existing Mode C behavior (one open position per instrument) must remain the baseline. Any daily limit is an ADDITIONAL constraint, not a replacement for Mode C.

### Implementation Notes (Future Deployment)

1. Add `daily_trade_locks` table check in `paper_scalp_live.py` before `try_create_trade()`
2. Read `MAX_TRADES_PER_INSTRUMENT_PER_DAY` from `settings.json` or environment variable
3. Default: disabled (current behavior) — requires explicit opt-in
4. Counter recovery: on restart, count existing trades for today from `paper_trades`
