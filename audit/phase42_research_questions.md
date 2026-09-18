# Phase 42 — Research Questions

**Date**: 2026-09-17
**Phase 41**: FROZEN

---

## Primary Research Questions

### Q1: WHY ARE THERE 1,184 TRADES?

1,184 trades from 1,950 candles (60.9% conversion) over 26 trading days (45.54 trades/day). Is this:

- A. Normal for an intraday system?
- B. Excessive due to repeated signals?
- C. Inflated by replay sequencing (candle-by-candle qualification)?
- D. A result of lack of setup persistence?
- E. A result of re-entry behavior?

**Research approach**: Analyze trade identity, re-entry patterns, signal persistence, and setup independence.

### Q2: IS THE DIRECTIONAL ASYMMETRY REAL?

BULLISH trades: 0.7% WR (2/281), BEARISH trades: 50.2% WR (453/903).

Possible explanations:
1. BULLISH signals occur during unfavorable market regimes
2. BULLISH trades are concentrated in a specific period
3. Market regime classification was BEARISH during BULLISH signals
4. VWAP/momentum was unfavorable for BULLISH trades
5. Sample size is too small for BULLISH (281 vs 903)
6. Replay logic contributed to BULLISH losses

**Research approach**: Break down BULLISH trades by regime, time, market state, and evidence alignment.

### Q3: DOES STRATEGY SELECTION WORK?

All 1,184 replay trades have strategy=None (replay bug). Production behavior differs. But we cannot evaluate strategy performance without either:
- Fixing the replay bug and re-running
- Using production trade data

**Research approach**: Evaluate strategy selection using production paper trade data where strategy is set correctly.

### Q4: DOES AI ADD VALUE?

No historical AI calls exist in the replay. Therefore:
- AI win rate: NOT MEASURED
- AI accuracy: NOT MEASURED
- AI contribution: NOT MEASURED

**Research approach**: Design future AI attribution framework. Require AI output logging in production. Compare evidence-only vs evidence+AI when sufficient data exists.

### Q5: ARE EVIDENCE GROUPS INDEPENDENT?

6 evidence groups (trend, momentum, structure, volatility, options, confirmation) may be correlated:
- VWAP and EMA both measure price location
- Trend and structure both describe market movement
- Momentum and trend are related

**Research approach**: Correlation analysis between evidence groups. Determine which groups add independent information.

### Q6: SHOULD SETUP PERSISTENCE BE REQUIRED?

87.2% re-entry within 5 minutes suggests:
- Either rapid legitimate new setups
- Or duplicate/repeated setups
- Or replay sequencing artifact

**Research approach**: Define "distinct setup" and measure independent setup count vs trade count.

### Q7: WHAT IS THE TRUE TRADE DEPENDENCE?

1,184 highly correlated trades may represent far fewer independent decisions.

**Research approach**: Calculate effective independent setup count. Assess statistical significance.
