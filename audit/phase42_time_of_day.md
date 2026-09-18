# Phase 42 — Time-of-Day Analysis Design

**Date**: 2026-09-17
**Phase 41**: FROZEN

---

## Period Definitions

| Period | Time | Rationale |
|--------|------|-----------|
| Opening | 09:15–10:00 | Market opening, highest volatility |
| Mid-morning | 10:00–11:00 | Post-opening stabilization |
| Late morning | 11:00–12:00 | Mid-session |
| Lunch | 12:00–13:00 | Indian market lunch break reduces activity |
| Early afternoon | 13:00–14:00 | Post-lunch reopening |
| Late afternoon | 14:00–15:00 | Institutional activity, closing price formation |
| Closing | 15:00–15:30 | Final 30 minutes, closing auction |

## Metrics Per Period

For each period compute:
- Trades (count)
- Wins / Losses / Breakeven
- Win rate (%)
- Average win (₹)
- Average loss (₹)
- Expectancy (₹) = WR × avg_win + (1-WR) × avg_loss
- Net P&L (₹)
- Maximum drawdown (₹)
- Maximum consecutive losses
- Average holding time (minutes)

## Period Analysis Design

### Baseline (Phase 41 Data)
- Total period: 2026-08-08 to 2026-09-15
- All trades: 1,184
- All NIFTY (BANKNIFTY data not in replay)
- Timestamps include pre-market hours (05:30 observed in replay)

### Distribution Analysis

1. **Trade frequency by period**: Are trades evenly distributed or concentrated?
2. **Win rate by period**: Are certain periods more profitable?
3. **P&L by period**: Which periods contribute most/least?
4. **Drawdown by period**: Do losses concentrate in specific periods?
5. **Direction by period**: Is BULLISH/BEARISH distribution period-dependent?

### Key Questions to Answer

1. Are BULLISH trades concentrated in a specific period?
2. Does the Opening period have higher or lower WR than average?
3. Does the Closing period have different characteristics?
4. Is there a "dead period" with low WR?
5. Are losses concentrated in a specific period?

## NOT IMPLEMENTED IN PHASE 42

- No time filtering will be applied
- No period-specific rules will be created
- All periods remain valid trading opportunities
- This is diagnostic analysis only
