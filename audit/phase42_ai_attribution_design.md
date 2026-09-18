# Phase 42 — AI Attribution Design

**Date**: 2026-09-17
**Phase 41**: FROZEN
**Known Limitation**: No historical AI calls exist in the replay data

---

## Critical Constraint

Historical replay currently contains NO AI CALLS. Therefore, the following CANNOT be claimed:
- AI win rate
- AI accuracy
- AI contribution
- AI incremental alpha
- AI outperformance vs deterministic

## Future AI Attribution Framework

### Objective

Determine whether AI adds measurable value beyond deterministic evidence.

### Data Collection Requirements

For every AI outlook generation, persist:

| Field | Description | Example |
|-------|-------------|---------|
| outlook_id | Unique identifier | "OUT-20260917-145413-001" |
| AI timestamp | When outlook was generated | "2026-09-17T14:54:13Z" |
| bias | BULLISH/BEARISH/NEUTRAL | "BULLISH" |
| confidence | 0-100 | 72 |
| regime | Market regime | "BULLISH" |
| summary | AI summary text | "Strong momentum..." |
| evidence summary | Evidence summary text | "EMA aligned with VWAP..." |
| confirmation | Confirmation level | "STRONG" |
| invalidation | Invalidation level | "VWAP reversal" |
| trade_state | Expected trade state | "GO" |
| expected horizon | Expected holding period | "30-60 minutes" |
| engine/model version | Version info | "phase41_v2.1" |

### Comparison Framework

When sufficient historical AI data exists, evaluate:

**Comparison A: Evidence-Only Baseline**
- Qualification engine runs without AI outlook
- Trades based solely on deterministic evidence
- All metrics computed (win rate, PnL, drawdown, etc.)

**Comparison B: Evidence + AI Outlook**
- Same qualification engine WITH AI outlook
- AI outlook influences qualification threshold or strategy selection
- All metrics computed identically

**Comparison C: Qualification Without AI**
- Trade qualification uses evidence checks only
- AI not consulted
- Compare against Comparison B

**Comparison D: Qualification With AI**
- Trade qualification uses evidence + AI confidence
- Compare against Comparison C

### Proposed Metrics for AI Attribution

| Metric | Description | How to Compute |
|--------|-------------|----------------|
| Change in expectancy | Δ expectancy (B vs A) | (B expectancy) - (A expectancy) |
| False signal reduction | Fewer losing trades | Count trades that lose in A but don't enter in B |
| Drawdown reduction | Smaller max drawdown | max_drawdown(B) vs max_drawdown(A) |
| Setup quality improvement | Higher win rate per setup | Compare WR per setup type |
| Calibration | Do AI confidence levels match actual outcomes? | Bin by confidence, check WR per bin |
| Trade filtering value | How many trades AI filters out? | Count trades entered in A but skipped in B |

### AI Exclusion Rule

AI NEVER computes:
- Walk-forward metrics
- Historical evidence scores
- Win rates
- P&L calculations
- Performance statistics

AI MAY:
- Generate outlooks (production)
- Explain already-calculated results
- Summarize evidence alignment
- Translate deterministic outputs to text

### Statistical Significance

AI attribution requires:
- Minimum 300 trades per comparison group
- Same time period for fair comparison
- Same market conditions
- Same transaction costs
- Statistical test (t-test or bootstrap) for significance

## NOT IMPLEMENTED IN PHASE 42

- No AI calls will be made to historical data
- No LLM will be used for analysis
- No AI-generated comparisons will be created
- No prompt changes will be evaluated
- This is framework documentation only
