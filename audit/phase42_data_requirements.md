# Phase 42 — Data Requirements

**Date**: 2026-09-17
**Phase 41**: FROZEN
**Objective**: Define what data must be available before Phase 42 research begins

---

## Problem

Phase 42 research requires comprehensive data collection. Current data is:
- NIFTY only (no BANKNIFTY, FINNIFTY, or SENSEX in replay)
- 5-minute candles (26 days, 1,950 candles)
- No historical option chain data
- No AI outlook history
- No production paper trade history (replay used synthetic pipeline)

## Required Data for Phase 42 Research

### Market Data (Per 5m Candle, Per Instrument)

| Field | Source | Priority |
|-------|--------|----------|
| timestamp | Exchange | REQUIRED |
| instrument | Exchange | REQUIRED |
| OHLC | Exchange | REQUIRED |
| volume | Exchange | REQUIRED |
| VWAP | Backend calculation | REQUIRED |
| EMA (20, 50) | Backend calculation | REQUIRED |
| RSI (14) | Backend calculation | REQUIRED |
| MACD | Backend calculation | REQUIRED |
| ADX | Backend calculation | REQUIRED |
| ATR (14) | Backend calculation | REQUIRED |
| CPR (Pivot + Support/Resistance) | Backend calculation | REQUIRED |
| VIX | External API | REQUIRED |
| AI outlook fields | LLM | PHASE 43 |
| Outcome fields | Post-close | PHASE 43 |

### Evidence Data (Per 5m Candle, Per Instrument)

| Field | Description | Priority |
|-------|-------------|----------|
| trend_direction | BULLISH/BEARISH/NEUTRAL | REQUIRED |
| trend_score | Numeric score | REQUIRED |
| momentum_direction | BULLISH/BEARISH/NEUTRAL | REQUIRED |
| momentum_score | Numeric score | REQUIRED |
| structure_direction | BULLISH/BEARISH/NEUTRAL | REQUIRED |
| structure_score | Numeric score | REQUIRED |
| volatility_state | HIGH/LOW/NORMAL | REQUIRED |
| options_state | BULLISH/BEARISH/NEUTRAL/NOT_AVAILABLE | REQUIRED |
| confirmation_direction | BULLISH/BEARISH/NEUTRAL | REQUIRED |
| confirmation_score | Numeric score | REQUIRED |
| evidence_available | Boolean per group | REQUIRED |
| evidence_conflicts | Boolean | REQUIRED |

### AI Data (Per Outlook Generation)

| Field | Description | Priority |
|-------|-------------|----------|
| outlook_id | Unique ID | REQUIRED |
| AI timestamp | When outlook was generated | REQUIRED |
| bias | BULLISH/BEARISH/NEUTRAL | REQUIRED |
| confidence | 0-100 | REQUIRED |
| regime | Market regime | REQUIRED |
| summary | AI summary text | REQUIRED |
| evidence summary | Evidence summary text | REQUIRED |
| confirmation | AI confirmation level | REQUIRED |
| invalidation | AI invalidation level | REQUIRED |
| trade_state | Expected trade state | REQUIRED |
| expected horizon | Expected holding period | REQUIRED |
| engine/model version | Version info | REQUIRED |

### Qualification Data (Per Trade Attempt)

| Field | Description | Priority |
|-------|-------------|----------|
| All qualification checks | 6-layer checklist results | REQUIRED |
| Decision | GO/WAIT/NO_SETUP | REQUIRED |
| Reason | Why this decision | REQUIRED |
| Engine version | Version info | REQUIRED |

### Paper Trade Data (Per Completed Trade)

| Field | Description | Priority |
|-------|-------------|----------|
| Entry timestamp | When trade was entered | REQUIRED |
| Exit timestamp | When trade was exited | REQUIRED |
| Entry price | Entry price | REQUIRED |
| Exit price | Exit price | REQUIRED |
| Stop level | Stop loss level | REQUIRED |
| Target level | Target level | REQUIRED |
| Strategy | Which strategy was used | REQUIRED |
| P&L | Net profit/loss | REQUIRED |
| Costs | Brokerage, exchange fees, etc. | REQUIRED |
| Slippage | Actual slippage | REQUIRED |
| R-multiple | P&L / risk per unit | REQUIRED |
| Holding time | Duration in minutes | REQUIRED |
| Outcome | WIN/LOSS/BREAKEVEN/OPEN | REQUIRED |

### Outcome Data (Per Completed Candle)

| Field | Description | Priority |
|-------|-------------|----------|
| Close | Closing price | REQUIRED |
| High | High of candle | REQUIRED |
| Low | Low of candle | REQUIRED |
| Volume | Volume | REQUIRED |
| Subsequent move | % move in next N candles | REQUIRED |
| Regime at close | Regime at end of candle | REQUIRED |

## Minimum Data for Phase 42 Research

### Data Sufficiency Gate

Before Phase 42 optimization research begins, the following minimums must be met:

| Criteria | Minimum | Current Status |
|----------|---------|----------------|
| Trading days | 90+ | 26 (INSUFFICIENT) |
| 5m candles | 5,000+ | 1,950 (INSUFFICIENT) |
| Independent setups | 100+ | Unknown (NEED ANALYSIS) |
| Market regimes | All 4+ | BULLISH/BEARISH confirmed (PARTIAL) |
| NIFTY coverage | 90+ days | 26 days (INSUFFICIENT) |
| BANKNIFTY coverage | 90+ days | 0 days (MISSING) |
| Option-chain coverage | 90+ days | 0 days (MISSING) |
| AI outlook history | 90+ days | 0 days (MISSING) |
| Paper trade history | 100+ trades | 0 production trades (MISSING) |
| Timestamp integrity | No gaps | Must verify |
| Missing data | <5% | Must verify |

## NOT IMPLEMENTED IN PHASE 42

- No data collection will be automated in this phase
- No database schema changes will be made
- No new data sources will be connected
- This is documentation only
