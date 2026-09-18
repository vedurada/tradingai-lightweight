# Phase 42 — Re-entry Design

**Date**: 2026-09-17
**Phase 41**: FROZEN
**Known Finding**: 87.2% of re-entries occurred within 5 minutes

---

## Problem

87.2% re-entry within 5 minutes is a critical finding that must be investigated before any strategy optimization. The high re-entry rate could indicate:

A. Legitimate new setups (market conditions re-appear quickly)
B. Duplicate setups (same setup re-qualified after exit)
C. Exit/re-entry artifact (exit and re-entry are two sides of same signal)
D. Replay sequencing artifact (candle-by-calk qualification creates artificial re-entry)
E. Market-state persistence (market state doesn't change enough between exits)

## Breakdown Analysis Framework

The following breakdowns should be performed in Phase 42:

### By Instrument
- NIFTY re-entry rate
- BANKNIFTY re-entry rate (if data available)

### By Direction
- BULLISH re-entry rate and outcomes
- BEARISH re-entry rate and outcomes
- Does rapid re-entry after BULLISH losses lead to further losses?

### By Regime
- BULLISH regime re-entry
- BEARISH regime re-entry
- RANGE regime re-entry
- MIXED regime re-entry

### By Strategy
- Strategy 1 re-entry
- Strategy 2 re-entry
- Strategy 3 re-entry

### By Time of Day
- 09:15–10:00 re-entry
- 10:00–11:00 re-entry
- 11:00–12:00 re-entry
- 12:00–13:00 re-entry
- 13:00–14:00 re-entry
- 14:00–15:00 re-entry
- 15:00–15:30 re-entry

### By Holding Time
- <5 min holding → <5 min re-entry
- 5–15 min holding → <5 min re-entry
- 15–30 min holding → <5 min re-entry
- >30 min holding → <5 min re-entry

### By Previous Trade Result
- After WIN → re-entry rate and outcomes
- After LOSS → re-entry rate and outcomes
- After BREAKEVEN → re-entry rate and outcomes

## Classification Methodology

For each re-entry, classify as one of:
1. **Same Setup**: Same instrument, same direction, same regime, different candles
2. **New Setup**: Different instrument OR different direction OR different regime
3. **Exit/Re-entry Artifact**: Exit and re-entry within same market state
4. **Replay Artifact**: Caused by candle-by-candle qualification

## Expected Research Outcome

Determine whether 1,184 trades represent:
- ~1,184 independent decisions (if A/C classification dominates)
- ~200-400 independent decisions (if B/D classification dominates)
- Something else entirely

## NOT IMPLEMENTED IN PHASE 42

- No cooldown timer will be added
- No re-entry logic will be changed
- No duplicate detection will be implemented
- This is diagnostic research only
