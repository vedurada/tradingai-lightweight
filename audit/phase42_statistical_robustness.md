# Phase 42 — Statistical Robustness Design

**Date**: 2026-09-17
**Phase 41**: FROZEN
**Objective**: Design statistical analysis framework

---

## Principle

Do NOT overstate statistical significance from 1,184 highly correlated trades. The effective number of independent setups may be much lower.

## Sample Size Assessment

### Raw vs Effective Sample Size

| Measure | Value | Notes |
|---------|-------|-------|
| Raw trades | 1,184 | What we have |
| Trading days | 26 | Short period |
| Estimated independent setups | TBD | Likely 200-400 |
| Independent setup ratio | TBD | raw / effective |

### How to Estimate Independent Setups

1. Group trades by: instrument + date + direction + regime
2. Count unique groups
3. Each group = potentially one independent decision
4. Compare to raw trade count

### Why This Matters

If 1,184 trades represent 300 independent decisions:
- Confidence intervals are 2x wider than if 1,184 were independent
- Win rate of 38.43% with 300 observations: ±3.2% at 95% CI
- Win rate of 38.43% with 1,184 observations: ±1.8% at 95% CI
- The truth could be anywhere from 35.2% to 41.6% (with 300 obs)

## Bootstrap Analysis Design

### Procedure

1. Set N = independent setup count
2. Sample N trades WITH REPLACEMENT from all trades
3. Compute win rate, PnL, PF for sample
4. Repeat 10,000 times
5. Take 2.5th and 97.5th percentile = 95% CI

### Per-Group Bootstrap

For BULLISH trades specifically:
- 281 trades, 2 wins → WR ≈ 0.7%
- 95% CI: [0.0%, ~1.9%] — still close to zero
- Sample size: 281 is sufficient to say WR is definitely below 5%
- But is the cause identified?

## Distribution of Returns

### Design

1. Plot histogram of trade PnL
2. Check: is it normal? Skewed? Bimodal?
3. Expected: right-skewed (small wins, larger losses based on Phase 41 data)
4. Phase 41 data: avg win +₹153.61, avg loss -₹311.00 (losses are 2x wins)

### Implications

- Non-normal distribution means t-tests may not apply
- Use bootstrap instead of parametric tests
- Median may be more meaningful than mean

## Maximum Drawdown Analysis

### Phase 41 Result
- Max drawdown: -₹135,470.57
- With 1,184 trades over 26 days

### Research Questions
- How does drawdown scale with trade count?
- What is drawdown per independent setup?
- How does drawdown correlate with market conditions?

### Bootstrap Design
1. Resample independent setups with replacement
2. Compute max drawdown for each resample
3. Distribution of max drawdown across resamples
4. 95% CI for max drawdown

## Consecutive Losses

### Phase 41 Result
- Max consecutive losses: 37

### Research Questions
- Is 37 consecutive losses statistically unusual?
- What probability distribution fits the loss streak pattern?
- Does regime affect consecutive losses?

### Analysis Design
1. Compute expected streaks from win rate (38.43%)
2. Compare actual streaks to expected
3. Chi-squared or KS test for distribution fit

## Trade Clustering

### Design
1. Identify clusters of trades from same market move
2. Measure cluster size (number of trades per market move)
3. Assess: are clusters correlated?
4. Compute: what % of trades are in clusters?

## Regime Dependency

### Design
1. Compute metrics per regime (BULLISH, BEARISH, RANGE, MIXED)
2. Test: are regime-specific metrics significantly different?
3. Chi-squared test for win rate differences
4. ANOVA for PnL differences (if parametric) or Kruskal-Wallis (if non-parametric)

## Confidence Intervals Summary

For every metric reported in Phase 42:
1. State point estimate
2. State 95% confidence interval (bootstrap)
3. State effective sample size (independent setups)
4. State whether sample is adequate (≥300 independent)
