# Phase 41 — Replay Methodology Validation
Generated: 2026-09-17

## Question: Is the Replay Realistic?

This document validates the replay methodology against 5 criteria.

## ENTRY: No Future Data

### Check

A trade may only enter using information available at or before the entry candle.

### Validation

| Check | Result | Evidence |
|-------|--------|----------|
| Entry at close of qualifying candle | YES | Entry price = candle close |
| No future candle data in qualification | YES | Evidence evaluated at current timestamp |
| No future high/low | YES | Only current candle OHLC used |
| No future close | YES | Close used is from qualifying candle |
| No future option information | YES | Options not available in DB |
| No future AI output | YES | Synthetic outlook created per candle |

### Finding: PASS

Entry uses only data ≤ entry candle timestamp.
No future data used in qualification or entry.

## EXIT: Stop/Target Evaluation Order

### Check

Verify stop/target evaluation order when both could occur within the same candle.

### Current Behavior

The replay scans forward candle by candle:
```python
for j in range(i+1, min(i+80, len(candles))):
    f = candles[j]
    if f['close'] >= target: exit_info = ('TARGET_HIT', f['close'], f['timestamp']); break
    if f['close'] <= stop: exit_info = ('STOP_LOSS', f['close'], f['timestamp']); break
```

### Issue

If both stop and target are hit within the same candle, the current code checks
TARGET first, then STOP. This means if the candle's high hits target and low hits
stop, the replay assumes TARGET was hit first.

### Finding: AMBIGUOUS (Documented)

**Conservative rule documented**: If both conditions met in same candle,
TARGET is evaluated before STOP. This may not reflect actual intrabar sequence.

For NIFTY at ~23000 level:
- Stop distance: 0.5% = 115 points
- Target distance: 1.5% = 345 points
- In a 5-minute candle, range can exceed 345 points in volatile periods
- Both can be hit within same candle

### Recommendation

For production, use tick-level data or document the tie-breaking rule clearly.
Current rule: TARGET > STOP (favorable to trade).

## AI: No Fabricated Historical Performance

### Check

The replay must NOT claim historical AI performance unless actual historical AI
outputs were stored.

### Validation

| Check | Result | Evidence |
|-------|--------|----------|
| AI outlook generated during replay? | NO | No Groq API calls in replay_runner.py |
| Historical AI outputs stored? | NO | No storage mechanism in replay |
| AI performance claimed? | NO | Documents clearly state AI is input only |
| Attribution correct? | YES | See phase41_ai_attribution.md |

### Finding: PASS

Replay does NOT claim AI performance.
All results attributed to deterministic framework.
AI predictive performance explicitly marked as NOT MEASURABLE.

## OPTIONS: No Fabricated Option Data

### Check

If historical option-chain data was not stored, do not pretend paper trades
used realistic historical option premiums.

### Validation

| Check | Result | Evidence |
|-------|--------|----------|
| Options data in DB? | NO | options_chain table empty for historical period |
| Paper trade uses option premiums? | NO | Underlying-only logic |
| Options separation documented? | YES | Underlying vs Options separated in qualification |
| Realistic option execution? | NO | Not possible with available data |

### Finding: PARTIAL

**Underlying/index signal replay**: VALID
- Evidence evaluation, qualification, paper trade entry/exit all work
- PnL calculation is correct for underlying

**Realistic historical options execution replay**: NOT POSSIBLE
- No historical option-chain data available
- Options strategies (CALL_DEBIT_SPREAD, PUT_DEBIT_SPREAD) cannot be backtested
- Paper trades simulate underlying PnL only
- Options-specific risks (theta, vega, volatility) not modeled

### Recommendation

Clearly separate:
1. Underlying signal replay (current capability)
2. Realistic options execution replay (requires data collection)

## Summary

| Criterion | Result |
|-----------|--------|
| No future data at entry | PASS |
| Exit order ambiguity | DOCUMENTED (TARGET before STOP) |
| AI performance not fabricated | PASS |
| Option data not fabricated | PARTIAL (underlying only) |

### Overall Assessment

The replay is methodologically sound with two caveats:
1. Intrabar exit order is ambiguous when both stop and target are hit in same candle
2. Options execution cannot be validated without historical data

Both are documented and do not affect the validity of underlying-only replay.
