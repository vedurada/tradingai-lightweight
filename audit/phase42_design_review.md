# Phase 42 — Design Review

**Date**: 2026-09-17
**Phase 41**: FROZEN
**Phase 41C**: COMPLETE
**This Document**: Design review only — no implementation

---

## Purpose

This document defines what Phase 42 should research and investigate. It does NOT implement any trading rule changes, threshold adjustments, or strategy modifications. The sole objective is to determine the research agenda for Phase 42 based on actual Phase 41 evidence.

## Current Production Pipeline (Frozen)

```
5m MARKET DATA
    ↓
MARKET SNAPSHOT
    ↓
MARKET EVIDENCE (6 groups)
    ↓
MARKET STATE
    ↓
AI OUTLOOK (Groq LLM)
    ↓
TRADE QUALIFICATION (6-layer checklist)
    ↓
STRATEGY SELECTION (3 strategies)
    ↓
PAPER TRADE (no broker execution)
    ↓
OUTCOME (P&L tracking)
```

## Key Baseline Numbers (Phase 41 Replay)

| Metric | Value |
|--------|-------|
| Period | 2026-08-08 to 2026-09-15 |
| Trading days | 26 |
| Total trades | 1,184 |
| Win rate | 38.43% |
| Net P&L | -₹130,391.72 |
| Profit factor | 0.349 |
| Avg win | +₹153.61 |
| Avg loss | -₹311.00 |
| Expectancy | -₹110.13 |
| Max drawdown | -₹135,470.57 |
| Max consecutive losses | 37 |
| Trades/day | 45.54 |
| Bullish trades | 281 (0.7% WR, -₹137,296) |
| Bearish trades | 903 (50.2% WR, +₹6,904) |
| Strategy field | None (100% — replay bug) |
| Instrument | NIFTY (100%) |

## Known Findings

1. **1,184 trades from 1,950 candles** — 60.9% of eligible candles produced a trade
2. **87.2% re-entry within 5 minutes** — high frequency of same-instrument re-entry
3. **Directional asymmetry** — BULLISH 0.7% WR vs BEARISH 50.2% WR
4. **Strategy=None in replay** — `_determine_strategy` called before `trade_status` set to TRADE; production behavior is different
5. **AI not called in replay** — historical AI attribution unavailable
6. **Options data insufficient** — cannot realistically evaluate options strategies
7. **Exit-order ambiguity** — stop and target may occur in same candle
8. **Phase 37 vs Phase 41 not directly comparable** — different methodologies

## Detailed Analysis Findings

### Funnel Analysis

| Stage | Count | Conversion Rate |
|-------|-------|-----------------|
| Candles | 1,950 | — |
| Eligible | 1,929 | 98.9% |
| Evidence Directional | 1,184 | 61.4% (of eligible) |
| Qualified | 1,184 | 100% (of directional) |
| Paper Trades Created | 1,184 | 100% (of qualified) |
| Paper Trades Completed | 1,184 | 100% (of created) |

**Key insight**: 38.6% of eligible candles did NOT have directional evidence. Of those that did, 100% passed qualification in replay (expected — replay bypasses qualification checks). Production qualification is expected to be more selective.

### Trade Performance by Direction

| Direction | Trades | Wins | Win Rate | Net P&L | Avg Win | Avg Loss |
|-----------|--------|------|----------|---------|---------|----------|
| BULLISH | 281 | 2 | 0.7% | -₹137,296 | ₹153 | -₹489 |
| BEARISH | 903 | 453 | 50.2% | +₹6,904 | ₹153 | -₹311 |

**BULLISH trades are 0.7% WR** — 2 wins out of 281 trades. This is the single most critical research question for Phase 42. Possible causes: (a) BULLISH signals occur during BEARISH regime, (b) VWAP/momentum unfavorable for BULLISH, (c) sample dominated by specific period, (d) replay logic artifact.

### Trade Performance by Strategy

| Strategy | Trades | Note |
|----------|--------|------|
| None | 1,184 | Replay bug — strategy determined after trade_status |

**Production behavior differs**: In production, strategy selection occurs before paper trade creation. This replay artifact does not reflect production behavior.

### Trade Performance by Instrument

| Instrument | Trades | Note |
|------------|--------|------|
| NIFTY | 1,184 | Only instrument in replay period |

BANKNIFTY, FINNIFTY, SENSEX data not included in this replay period.

### Trade Performance by Holding Period

(To be computed in Phase 42 research — requires exit timestamps from production data)

### Evidence Alignment (Phase 40 Engine Output)

- 6 evidence groups: trend, momentum, structure, volatility, options, confirmation
- Options group frequently NOT_AVAILABLE
- 100% qualification pass rate in replay (expected — replay bypasses qualification checks)
- Production qualification expected to be more selective

### Time Distribution

- Replay timestamps span 26 trading days from 2026-08-10 to 2026-09-15
- Timestamps observed include pre-market hours (05:30 in sample trade)
- Hourly distribution to be computed in Phase 42 research framework

### Key Research Priorities for Phase 42

1. **BULLISH 0.7% WR investigation** — determine root cause before any rule changes
2. **Trade identity** — determine independent setup count vs raw trade count
3. **Evidence independence** — verify if 6 groups are truly independent
4. **AI attribution** — cannot evaluate until AI data is logged
5. **Options data** — blocked by unavailability
6. **Statistical robustness** — effective sample size likely much smaller than 1,184
7. **Cost impact** — determine if edge survives after realistic costs
