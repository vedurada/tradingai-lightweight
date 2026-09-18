# Phase 42 — Evidence Analysis Design

**Date**: 2026-09-17
**Phase 41**: FROZEN
**Known**: 100% of qualification funnel passed the replay qualification stage

---

## Problem

100% of directional evidence led to qualification in the replay. This raises the question:

Is qualification effectively equivalent to "some evidence exists" rather than requiring sufficient independent confirmation?

## Evidence Groups (Phase 40 Engine)

### Group 1: Trend
- Direction: BULLISH/BEARISH/NEUTRAL
- Score: Numeric (0-100)
- Based on: EMA alignment, price position vs EMAs

### Group 2: Momentum
- Direction: BULLISH/BEARISH/NEUTRAL
- Score: Numeric (0-100)
- Based on: Rate of change, momentum indicators

### Group 3: Structure
- Direction: BULLISH/BEARISH/NEUTRAL
- Score: Numeric (0-100)
- Based on: Higher highs/higher lows, break patterns

### Group 4: Volatility
- State: HIGH/LOW/NORMAL
- Based on: ATR, range, volatility regime

### Group 5: Options
- State: BULLISH/BEARISH/NEUTRAL/NOT_AVAILABLE
- Based on: Option chain data (often unavailable in replay)

### Group 6: Confirmation
- Direction: BULLISH/BEARISH/NEUTRAL
- Score: Numeric (0-100)
- Based on: VIX, CPR, support/resistance, additional confirmation

## Analysis Framework

### Per Trade Analysis

For each of the 1,184 trades, where available, record:

| Field | Trade 1 Example | Trade 2 Example | ... |
|-------|----------------|----------------|-----|
| trend_direction | BULLISH | BEARISH | |
| trend_score | 75 | 60 | |
| momentum_direction | BULLISH | BULLISH | |
| momentum_score | 65 | 55 | |
| structure_direction | NEUTRAL | BEARISH | |
| structure_score | 40 | 70 | |
| volatility_state | HIGH | NORMAL | |
| options_state | NOT_AVAILABLE | NOT_AVAILABLE | |
| confirmation_direction | BULLISH | BEARISH | |
| confirmation_score | 80 | 65 | |
| evidence_available | 5/6 | 4/6 | |
| evidence_conflicts | N | Y | |

### Aligned Evidence Analysis

Count trades where:
- All available evidence groups agree direction (no conflicts)
- Majority of available evidence agrees direction
- Mixed evidence (conflicting directions)

### Conflicting Evidence Analysis

For conflicting trades:
- What is the win rate?
- What is the P&L?
- Does qualification pass when evidence conflicts?

### Unavailable Evidence Analysis

For trades where options_state = NOT_AVAILABLE:
- What percentage of trades have missing options data?
- Does missing options data affect qualification?
- Would options data change the decision?

## Key Research Questions

### RQ1: Is Qualification a Low Bar?

If 100% of directional evidence passes qualification:
- Are the qualification checks too permissive?
- Does "all evidence groups agree" = good setup?
- Or is alignment genuinely sufficient in production?

### RQ2: Evidence Independence

Do the 6 groups actually measure 6 independent things?
- Trend and Momentum are likely correlated (both use price data)
- Structure and Trend are likely correlated (both describe market direction)
- Options data is often unavailable (4th group rarely contributes)
- Effective independent signals may be fewer than 6

### RQ3: Confirmation Value

Is the Confirmation group (group 6) actually confirming or just reinforcing?
- Does it use different data sources?
- Does it add genuinely independent information?

## Evidence Score Distribution

For each evidence group:
- Distribution of scores
- Distribution of directions
- Correlation with trade outcome (P&L)

## NOT IMPLEMENTED IN PHASE 42

- No evidence rules will be modified
- No new evidence groups will be added
- No score weights will be changed
- Qualification logic is frozen
- This is analysis framework only
