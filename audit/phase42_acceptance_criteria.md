# Phase 42 — Acceptance Criteria

**Date**: 2026-09-17
**Phase 41**: FROZEN
**Objective**: Define what constitutes successful Phase 42 research completion

---

## Principle

Phase 42 success is NOT defined by win rate > 50%. Phase 42 success is defined by having a rigorous, evidence-based research framework that can evaluate whether TradingAI produces a repeatable, independently testable, risk-controlled decision process.

## Research Completion Criteria

### Data Sufficiency
- [ ] Minimum 90 trading days of NIFTY data collected
- [ ] Minimum 90 trading days of BANKNIFTY data collected
- [ ] Historical option-chain data sourced or declared unavailable
- [ ] AI outlook data logged for at least 30 days
- [ ] Production paper trade data exists for at least 100 trades
- [ ] Data gaps documented
- [ ] Timestamp integrity verified (no future data in historical records)

### Trade Identity Research
- [ ] Independent setup count determined
- [ ] Trade-to-setup ratio documented (was 1,184 trades → ? setups)
- [ ] Re-entry classification framework applied
- [ ] Signal persistence measured
- [ ] Setup fingerprint documented

### Directional Asymmetry Research
- [ ] BULLISH trades broken down by regime
- [ ] BULLISH trades broken down by time of day
- [ ] BULLISH trades broken down by evidence alignment
- [ ] Root cause(s) of 0.7% BULLISH WR identified (at least one)
- [ ] BULLISH sample size assessed for statistical significance

### Evidence Research
- [ ] All 6 evidence groups documented with scores for replay period
- [ ] Evidence correlation matrix computed
- [ ] Aligned vs conflicting evidence outcomes documented
- [ ] Determination: is qualification equivalent to "some evidence exists"?
- [ ] Unavailable evidence states documented and handled

### Cost/Slippage Framework
- [ ] All transaction costs sourced and documented
- [ ] Zero-cost, base-cost, stress-cost scenarios defined
- [ ] Slippage sensitivity framework defined (0, low, medium, high)
- [ ] Break-even edge calculated for each cost scenario

### Walk-Forward Design
- [ ] Training/validation/test window sizes defined
- [ ] Roll-forward frequency defined
- [ ] Parameter freeze rules documented
- [ ] Holdout period defined
- [ ] Minimum sample size verified against available data

### Statistical Robustness
- [ ] Independent setup count vs raw trade count
- [ ] Bootstrap analysis framework defined
- [ ] Consecutive losses analyzed (Phase 41: max 37)
- [ ] Trade clustering documented
- [ ] Regime dependency analyzed
- [ ] Confidence intervals estimated

### Look-Ahead Prevention
- [ ] Formal look-ahead checklist created and verified
- [ ] Data leakage tests designed
- [ ] Indicator warmup period documented
- [ ] Future normalization/scaling addressed
- [ ] Replay-generated labels audited

### AI Attribution Framework
- [ ] AI data collection schema defined
- [ ] Comparison framework (A: evidence-only, B: evidence+AI) defined
- [ ] AI exclusion rule documented (AI does not compute metrics)
- [ ] Minimum sample size for AI attribution defined (≥300 trades)

### Production Safety
- [ ] No production code modified during research design
- [ ] Research code separately versioned
- [ ] Clear separation: PRODUCTION (Phase 41) vs RESEARCH (Phase 42)
- [ ] Any future Phase 42 candidate: separately versioned, tested, backtested, approved

## NOT ACCEPTABLE

The following are NOT acceptable Phase 42 outcomes:
- Claiming AI win rate without historical AI data
- Tuning thresholds to improve backtest
- Cherry-picking favorable date ranges
- Removing unfavorable regimes
- Fabricating data to fill gaps
- Declaring "strategy is broken" without controlled comparison
- Comparing Phase 37 vs Phase 41 without identical methodology

## ACCEPTABLE

The following ARE acceptable Phase 42 outcomes:
- Identifying BULLISH 0.7% WR as a genuine research question
- Determining trade count inflation cause
- Documenting evidence correlation structure
- Defining proper walk-forward framework
- Sourcing transaction cost data
- Creating data sufficiency gate
- Declaring "insufficient data for optimization, more collection needed"
