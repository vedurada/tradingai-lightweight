# Phase 42 — Walk-Forward Design

**Date**: 2026-09-17
**Phase 41**: FROZEN
**Objective**: Design proper walk-forward validation framework

---

## Core Principle

TRAIN → VALIDATION → OUT-OF-SAMPLE TEST, then roll forward.

Never tune and evaluate on the same period. Never use future data to make past decisions.

## Proposed Framework

### Window Definitions

| Component | Purpose | Minimum Length | TBD? |
|-----------|---------|---------------|------|
| Training | Discover patterns | 60 trading days | YES — must verify data availability |
| Validation | Confirm patterns | 30 trading days | YES — must verify data availability |
| Test | Evaluate performance | 30 trading days | YES — must verify data availability |
| Roll frequency | How far to advance | 5 trading days | YES — must verify data availability |
| Holdout | Final untouched period | 30 trading days | YES — must verify data availability |

### Minimum Sample Size

Per window:
- Training: Minimum 60 days (360 candles) — must contain multiple regimes
- Validation: Minimum 30 days (180 candles)
- Test: Minimum 30 days (180 candles)
- Total minimum: 180 trading days (1 year) before any optimization

### Parameter Freeze Rules

When rolling forward:
1. Parameters discovered in training are FROZEN
2. Validation tests if frozen parameters work on new data
3. If validation fails, parameters are NOT updated — research question raised instead
4. Test is only run once per parameter set
5. No parameter updates between validation and test

### Why Parameter Freeze Matters

If parameters are tuned at every roll:
- It becomes curve-fitting on rolling data
- Out-of-sample performance is meaningless
- Forward performance will degrade

## Data Availability Assessment

Current data availability (as of Phase 41):
- Total trading days available: 26 (from replay period)
- Phase 41C API: Live data available from current date
- Historical data: Need to verify total available history

**Gate**: Phase 42 walk-forward CANNOT begin until at minimum 180 trading days (1 year) of clean data is available.

## Roll-Forward Schedule (Template)

```
Window 1: Train[Day 1-60] → Val[Day 61-90] → Test[Day 91-120]
Window 2: Train[Day 1-60] → Val[Day 61-90] → Test[Day 121-150]  (roll 5 days)
Window 3: Train[Day 61-120] → Val[Day 121-150] → Test[Day 151-180] (roll 60 days)
...
```

Note: Exact schedule depends on data availability and will be determined in Phase 42.

## Evaluation Metrics Per Window

For each walk-forward window, compute:
- Total trades
- Win rate
- Net P&L
- Profit factor
- Max drawdown
- Average win/loss
- Expectancy
- Consecutive losses
- Regime coverage
- Data completeness

## Consistency Criteria

A strategy passes walk-forward if:
1. Positive expectancy in ≥70% of test windows
2. Max drawdown ≤ acceptable threshold (TBD in Phase 42)
3. Performance not dependent on single regime
4. No degradation trend across windows
5. Out-of-sample performance within 50% of validation performance
