# Phase 5.19 — Daily Trade Limit Design (Not Implemented)

## Configuration (Proposed)
```json
{
  "MAX_OPEN_POSITIONS_PER_INSTRUMENT": 1,
  "MAX_TRADES_PER_INSTRUMENT_PER_DAY": null,
  "DAILY_LIMIT_ENABLED": false
}
```

## Counting Unit
- Per instrument, per trading session (IST date)
- Counts: completed trades (status = CLOSED) + open trades (status = ACTIVE/OPEN)
- Does NOT count: rejected, expired, duplicate, or failed-entry signals

## Behavior
- Disabled (null): no limit (current baseline, 63 trades/3 days)
- 1/day: first signal per instrument per day (~6 trades/3 days)
- Mode C preserved: one open position per instrument

## Restart/Cache Recovery
- On restart: count existing trades for today from paper_trades
- Counter recovered from DB, not in-memory
- No race condition: DB is source of truth

## Race Condition Prevention
- Check has_open_position() before creating trade
- Check daily count before creating trade
- Both checks in same transaction (atomic)

## Historical Re-evaluation
- Daily limit 1/day: ~6 trades (estimated, not verified from ledger)
- Not a production default (requires explicit approval)

## Policy Note
- Daily limit is an ADDITIONAL constraint, not a replacement for Mode C
- Exit monitor must continue managing open positions regardless of daily limit
