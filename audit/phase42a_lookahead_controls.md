# Phase 42A — Look-Ahead Controls

**Date**: 2026-09-17
**Phase 41**: FROZEN
**Critical**: Future outcomes must NEVER appear in decision-time records

---

## The Fundamental Rule

At timestamp T, a decision record can ONLY contain information available at T.

Future outcomes (T+5m, T+15m, T+30m, T+60m) are stored in SEPARATE records/tables.

The original decision record remains IMMUTABLE.

## Information Classification

### DECISION_TIME (Available at Timestamp T)

| Category | Examples |
|----------|---------|
| Market | OHLC, volume, VWAP, EMA, RSI, MACD, ADX, ATR |
| Evidence | Trend, momentum, structure, volatility, options, confirmation |
| AI | Bias, confidence, regime, summary, trade_state |
| Qualification | Checks, decision, reason, strategy, risk levels |
| Trade | Entry price, stop, target, quantity, direction |
| Setup | fingerprint, identity, type, re-entry relationship |

### FUTURE_OUTCOME (NOT Available at Timestamp T)

| Category | Examples |
|----------|---------|
| Market | Future OHLC, future VWAP, future EMA |
| Outcome | Win/loss, P&L, exit price, exit reason |
| AI | Future AI outlook, future confidence |
| Data | Future data availability, future staleness |

## Storage Separation

### Decision-Time Records (IMMUTABLE)
- research_setup_identity
- research_reentry_log
- research_ai_call_log
- market_snapshots_5m (existing)
- market_evidence_5m (existing)
- ai_outlooks_5m (existing)

### Future-Outcome Records (EVOLVING)
- research_outcome_tracking (NEW)
- ai_outcome_predictions (existing)
- paper_trades (existing, with outcome fields updated at exit)

## Outcome Tracking Lifecycle

```
At candle T:
  1. Setup identity recorded (DECISION_TIME fields only)
  2. AI call logged (DECISION_TIME fields only)
  3. Outcome record created (PENDING for all horizons)

At T+5m:
  1. Candle close confirmed
  2. Outcome record updated: outcome_5m = ACTUAL_RESULT
  3. Original decision record UNCHANGED

At T+15m, T+30m, T+60m:
  1. Same pattern: update outcome record, NOT decision record
```

## Tests for Look-Ahead Prevention

### Test 1: No Future Fields in Setup Identity
- Verify setup_fingerprint doesn't contain outcome data
- Verify setup_type is determined at decision time only

### Test 2: Outcome Records Separate from Decision Records
- Verify research_outcome_tracking has a separate primary key from setup_identity
- Verify updating outcome doesn't modify setup_identity record

### Test 3: Original Outlook Unchanged After Outcome Evaluation
- Verify ai_outlooks_5m record is not modified when outcome_5m is populated
- Verify research_outcome_tracking is a separate record

### Test 4: Deterministic Decision Records
- Given the same inputs at timestamp T, the decision record must be identical
- If code version changes, it creates a NEW record (not an UPDATE)

## Violation Detection

The research_data_health table records any detected look-ahead:
- Check: outcome fields populated before their time
- Check: decision records modified after outcome known
- Check: future timestamps in DECISION_TIME fields
- Check: outcome data in setup fingerprint

## Production Enforcement

1. Research tables are separate from production tables
2. Production trading code writes only to DECISION_TIME records
3. Outcome evaluation code writes only to FUTURE_OUTCOME records
4. No code path exists to update a decision record with outcome data
5. Tests verify this separation
