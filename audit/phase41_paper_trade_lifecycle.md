# Phase 41 — Paper Trade Lifecycle Documentation
Generated: 2026-09-17

## Overview

The Paper Trade Engine (`backend/paper_trade_engine.py`) manages the complete
paper trade lifecycle: qualification, entry, exit, PnL calculation, and event logging.

## Trade Record Schema

Each paper trade stores 22+ immutable fields:

| Field | Description | Set At |
|-------|-------------|--------|
| trade_id | Unique ID (PT-timestamp-random) | Creation |
| instrument | e.g., NIFTY | Creation |
| outlook_id | AI outlook reference | Creation |
| evidence_id | Evidence reference | Creation |
| direction | BULLISH/BEARISH/NEUTRAL | Creation |
| strategy | Strategy name | Creation |
| status | Lifecycle status | Lifecycle |
| setup_fingerprint | Unique setup identifier | Creation |
| qualification_timestamp | When qualification occurred | Creation |
| entry_condition | Entry description | Creation |
| invalidation | Exit conditions | Creation |
| entry_timestamp | Entry time | Entry |
| entry_price | Entry price | Entry |
| exit_timestamp | Exit time | Exit |
| exit_price | Exit price | Exit |
| stop | Stop loss level | Creation |
| target | Target level | Creation |
| quantity | Number of units | Creation |
| risk_reward | Risk/reward ratio | Creation |
| pnl | Profit/loss | Exit |
| pnl_percent | PnL percentage | Exit |
| holding_minutes | Time held | Exit |
| outcome | TARGET/STOP/EXPIRED | Exit |
| exit_reason | Exit reason | Exit |
| data_quality | Data quality flag | Creation |
| engine_version | Engine version | Creation |
| option_legs_json | Option leg details | Creation |

## Lifecycle Stages

1. **DETECTED**: Trade setup identified
2. **TRIGGERED**: Qualification passed, trigger conditions met
3. **CONFIRMATION**: Entry conditions verified
4. **ENTRY_WINDOW**: Valid entry period active
5. **ACTIVE**: Trade is live
6. **COMPLETE**: Trade exited (target/stop/expired)

## Protections

### Active Trade Prevention

- One API key cannot have multiple OPEN trades simultaneously
- Checks DB for OPEN + WAITING_ENTRY trades
- Blocks new entry if active trade exists

### Duplicate Setup Prevention

- Setup fingerprint: `instrument|direction|strategy|entry_condition|outlook_id`
- If a trade with same fingerprint exists → REJECTED as DUPLICATE
- In replay: Each candle has unique outlook_id → no duplicates detected

### Deterministic Trade IDs

- Format: PT-{timestamp}-{random6}
- Deterministic and reproducible

## Entry Process

1. Qualification passed (trade_status = TRADE)
2. `trigger_entry(trade_id, price, timestamp)` called
3. Entry stored with: price, timestamp, stop, target, quantity
4. Status changes: TRIGGERED → CONFIRMATION → ENTRY_WINDOW → ACTIVE

## Exit Process

1. `trigger_exit(trade_id, reason, price, timestamp)` called
2. Exit reasons: TARGET_HIT, STOP_LOSS, MANUAL, SESSION_CLOSE, EXPIRED
3. PnL calculated: (exit_price - entry_price) * quantity
4. For BEARISH trades: PnL negated (short position)
5. Outcome determined: TARGET/STOP/EXPIRED based on exit_reason

## PnL Calculation

```
Base PnL = (exit_price - entry_price) * quantity
For BEARISH direction: PnL = -Base PnL
For BULLISH direction: PnL = Base PnL
```

## Cost Model (not applied in replay)

- Brokerage: ₹20/side
- Slippage: 0.5 bps
- Exchange fee: 0.03%
- GST: 18% on brokerage+slippage
- Stamp: 0.003%

Note: Paper trades in replay do NOT apply transaction costs.
Actual PnL would be lower with costs.

## Test Coverage

- Test paper trade creation (valid/invalid qualification)
- Test lifecycle transitions (DETECTED → COMPLETE)
- Test target exit, stop exit, session close
- Test duplicate prevention
- Test active trade prevention
- Test PnL calculation
- Test trade fingerprint uniqueness
- 36/36 Phase 41 tests passing
