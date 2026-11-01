# Phase 5.12 — Live Engine Comparison

## Existing Production Decision Path

The existing production decision path is **CPR-driven**, not HLC-only. HLC has been used as a separate research/paper-trading path.

### Comparison

| Aspect | Canonical HLC (backtest) | Live Engine (production) |
|--------|------------------------|------------------------|
| Signal detection | _scan_signals() (3-bar alignment) | _cpr_book_signal() (CPR triggers) |
| HLC usage | Primary (research) | Overlay only (display) |
| Entry timing | Next candle open (historical) | Live provider (forming candle) |
| Entry guard | N/A (backtest) | 5-min window |
| Mode C | Enforced | Enforced |
| Data source | Historical DB | Live collector + provider |

### Discrepancies

1. **Signal count:** Backtest generates more signals than live (no entry guard filtering)
2. **Entry price:** Backtest uses historical candle open; live uses provider forming candle
3. **Exit timing:** Backtest scans all future candles; live monitors candle-by-candle
4. **Data freshness:** Backtest has instant access; live has ~9s median ingestion delay

### No Production Changes

No production code was modified to make results match. The comparison is observational only.
