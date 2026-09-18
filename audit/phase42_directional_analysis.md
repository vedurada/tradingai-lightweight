# Phase 42 — Directional Asymmetry Analysis Design

**Date**: 2026-09-17
**Phase 41**: FROZEN
**Critical Finding**: BULLISH ≈ 0.7% WR (2/281) vs BEARISH ≈ 50.2% WR (453/903)

---

## The Problem

BULLISH trades have near-zero win rate while BEARISH trades are approximately breakeven/slightly profitable. This 7.4:1 asymmetry in win rate demands investigation before any optimization.

## Investigation Framework

### Hypothesis 1: Sample Dominated by Particular Period

**Test**: Break down BULLISH trades by date:
- How many BULLISH trades per day?
- Are they concentrated in specific days?
- Do WR vary significantly across days?

If BULLISH losses come from 2-3 bad days → period-specific issue
If losses are spread across all 26 days → systematic issue

### Hypothesis 2: BULLISH Signals During Pullbacks

**Test**: For each BULLISH signal, check market context:
- Was the overall regime BEARISH at the time?
- Was the immediate candle direction bearish before bullish signal?
- Was it a counter-trend signal?

If BULLISH signals mostly occur during BEARISH regimes → signal may be incorrect for that context

### Hypothesis 3: Market Regime Classification Issue

**Test**: Compare signal direction with regime classification:
- BULLISH signal + BULLISH regime = aligned
- BULLISH signal + BEARISH regime = conflicting
- BULLISH signal + RANGE regime = neutral

What WR does each combination have?

### Hypothesis 4: VWAP Relationship Unfavorable

**Test**: For each BULLISH trade:
- Was entry price above or below VWAP?
- Did VWAP slope support or oppose the trade?
- What is VWAP distance from entry for winners vs losers?

### Hypothesis 5: Momentum Unfavorable

**Test**: For each BULLISH trade:
- Was momentum direction BULLISH or BEARISH?
- Was momentum score high or low?
- Do BULLISH+BULLISH trades outperform BULLISH+BEARISH trades?

### Hypothesis 6: Data Quality Difference

**Test**: Compare data quality between BULLISH and BEARISH trades:
- Same indicators available?
- Same data completeness?
- Any timestamp gaps?

### Hypothesis 7: Replay Logic Contribution

**Test**: Check if replay sequencing affects BULLISH trades:
- Are BULLISH exits affected by stop/target ambiguity?
- Is exit timing different for BULLISH vs BEARISH?
- Does strategy=None affect BULLISH differently?

## Breakdown Analysis Design

### By Direction × Regime

| | BULLISH regime | BEARISH regime | RANGE | MIXED |
|---|---|---|---|---|
| BULLISH signal | TBD | TBD | TBD | TBD |
| BEARISH signal | TBD | TBD | TBD | TBD |

### By Direction × Time Period

| | 09:15-10 | 10-11 | 11-12 | 12-13 | 13-14 | 14-15 | 15-15:30 |
|---|---|---|---|---|---|---|---|
| BULLISH | TBD | ... | ... | ... | ... | ... | ... |
| BEARISH | TBD | ... | ... | ... | ... | ... | ... |

### By Direction × Previous Result

| | After WIN | After LOSS | After BREAKEVEN | First Trade |
|---|---|---|---|---|
| BULLISH | TBD | TBD | TBD | TBD |
| BEARISH | TBD | TBD | TBD | TBD |

## Expected Outcome

After this analysis, we should know:
1. WHY BULLISH WR is 0.7% (at least primary cause)
2. Whether the issue is signal, execution, or data
3. Whether BULLISH rules need review or context adjustment
4. Whether sample size is sufficient to draw conclusions

## NOT IMPLEMENTED IN PHASE 42

- No BULLISH rules will be modified
- No bullish signal logic will be changed
- No bullish thresholds will be tuned
- This is diagnostic analysis only
