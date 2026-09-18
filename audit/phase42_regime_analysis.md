# Phase 42 — Market Regime Analysis Design

**Date**: 2026-09-17
**Phase 41**: FROZEN
**Regime definitions are frozen and MUST NOT be changed

---

## Regime Definitions (Frozen)

| Regime | Definition | Expected Characteristics |
|--------|-----------|------------------------|
| BULLISH | Trending upward | Higher highs, higher lows, EMA bullish |
| BEARISH | Trending downward | Lower highs, lower lows, EMA bearish |
| RANGE | Sideways | No clear trend, EMA flat |
| MIXED | Mixed signals | Some indicators bullish, some bearish |
| HIGH VOLATILITY | Elevated price swings | ATR above average |
| LOW VOLATILITY | Compressed price swings | ATR below average |

## Analysis Design

### Per Regime Metrics

For each regime, compute:

| Metric | BULLISH | BEARISH | RANGE | MIXED | HIGH VOL | LOW VOL |
|--------|---------|---------|-------|-------|----------|---------|
| Trade count | | | | | | |
| Wins | | | | | | |
| Losses | | | | | | |
| Win rate | | | | | | |
| Average win | | | | | | |
| Average loss | | | | | | |
| Expectancy | | | | | | |
| Profit factor | | | | | | |
| Net P&L | | | | | | |
| Max drawdown | | | | | | |
| Avg holding time | | | | | | |
| Max consecutive losses | | | | | | |

### Phase 41 Regime Data

Note: Phase 41 replay has strategy=None for all trades. Regime data per trade needs to be extracted from replay events/funnel data.

### Cross-Regime Analysis

1. **Regime dependency of BULLISH trades**: Do BULLISH trades occur during BEARISH regime?
2. **Regime performance**: Is performance concentrated in specific regimes?
3. **Regime transitions**: Do trades around regime transitions behave differently?
4. **Regime persistence**: How long does each regime typically last?

## Key Questions

### Q1: Is Performance Concentrated?

If 80% of P&L comes from BEARISH regime only:
- Strategy is regime-specific, not universal
- Risk is regime-change exposure
- Need to understand regime triggers better

### Q2: Do BULLISH Trades Occur During BEARISH Regime?

This is a critical investigation:
- BULLISH direction + BEARISH regime = conflicting signal
- Should this trade happen at all?
- What is the win rate for conflicting trades?

### Q3: Are There "Bad" Regimes?

- Identify regimes where WR < 30%
- Determine: should NO_TRADE be more aggressive in these regimes?
- This is RESEARCH, not implementation

## Data Requirements

For regime analysis, each trade needs:
- Regime at entry
- Regime at exit
- Regime duration (if applicable)
- Regime during trade holding period

## NOT IMPLEMENTED IN PHASE 42

- No regime definitions will be changed
- No regime-specific thresholds will be created
- No regime filters will be applied
- Regime classification logic is frozen
- This is analysis framework only
