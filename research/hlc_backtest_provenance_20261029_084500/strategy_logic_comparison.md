# Strategy Logic Comparison — HLC 3-Bar Scalp vs CPR Trigger

## Overview

This document compares the current live trading engine strategy (CPR Trigger) with the HLC 3-Bar Scalp strategy used in research backtests and paper trading.

## 3. Comparison Table

| Aspect | Live Decision Engine (`app/live/engine.py`) | HLC 3-Bar Scalp (`app/research/scalp_engine.py`) | Difference |
|--------|--------------------------------------------|--------------------------------------------------|----------|
| **Strategy type** | CPR Trigger (Previous-session CPR breakout) | HLC 3-Bar Alignment (Higher/Lower H/L/C x3) | **MISMATCH** — Different methodologies |
| **Signal detection** | CPR breakout above TC / below BC, PDH/PDL touches | 3 consecutive candles with H/L/C moving same direction | **MISMATCH** |
| **Signal priority** | BEAR checked before BULL (SHORT_ONLY) | BULL and BEAR both detected equally | **MISMATCH** |
| **Entry price** | Next candle open | Next candle open | MATCH |
| **Stop (BULL)** | Entry × 0.995 (0.5% below) | Signal candle low − 1.0 point | **MISMATCH** |
| **Stop (BEAR)** | Entry × 1.005 (0.5% above) | Signal candle high + 1.0 point | **MISMATCH** |
| **Target (BULL)** | Entry × 1.02 (2% above) | Entry + 1.5×risk | **MISMATCH** |
| **Target (BEAR)** | Entry × 0.98 (2% below) | Entry − 1.5×risk | **MISMATCH** |
| **Risk-reward ratio** | Fixed at 4:1 (2%/0.5%) | Fixed at 1.5:1 | **MISMATCH** |
| **Stop-first tie-break** | Yes (stop checked before target on same candle) | Yes | MATCH |
| **EOD exit** | Last candle close at 15:30 IST | Last session candle close | MATCH (conceptually) |
| **Daily trade limit** | Yes (1 per instrument per day via `daily_trade_locks`) | None (every qualifying signal creates trade) | **MISMATCH** |
| **Position limit** | 1 per instrument per day | 1 open position per instrument (Mode C) | MATCH (conceptually) |
| **Weekday gate** | SKIP_FRIDAY (BEAR signals dropped on Friday) | None | **MISMATCH** |
| **Direction bias** | SHORT_ONLY (BULL suppressed) | Both BULL and BEAR | **MISMATCH** |
| **Look-ahead protection** | Completed candles only, forming candle excluded | Completed candles only, entry candle excluded from trigger | MATCH |
| **Data source** | Stored `market_candles_5m` | Stored `market_candles_5m` | MATCH |

## 4. Key Differences Summary

| # | Difference | Impact |
|---|-----------|--------|
| 1 | **Signal methodology** — CPR breakout vs HLC 3-bar alignment | Completely different signals; will never produce the same trades |
| 2 | **Stop/Target** — 0.5%/2% vs ±1pt/1.5×R | Different risk profiles; CPR has smaller R (4:1 vs 1.5:1) |
| 3 | **Direction bias** — SHORT_ONLY vs bidirectional | CPR only takes BEAR (mostly); HLC takes both |
| 4 | **Weekday gate** — SKIP_FRIDAY vs none | CPR drops Friday BEAR signals; HLC does not |
| 5 | **Daily trade limit** — 1 per instrument/day vs none | CPR limits to 1 trade/day; HLC takes every signal |
| 6 | **Backtest vs live parity** — API `/api/backtest/cpr-triggers` uses CPR; `/api/backtest/scalp` uses HLC | Two different backtest APIs with different strategies |

## 5. Conclusion

**The historical backtest results are NOT comparable to the current live engine.**

- The live decision engine uses CPR Trigger strategy (0.5%/2% stop/target, SHORT_ONLY, skip-Friday)
- The research backtests (`hlc_backtest_20261028/`, `hlc_frequency_risk_20261028/`) use HLC 3-Bar Scalp (±1pt stop/1.5×R target, bidirectional)
- Database backtest_runs (2,293 runs) all have scenario_filter="ALL" and status RUNNING — the actual strategy used is unknown
- `backtest_trades` table is EMPTY — no persisted results from any database run

**To establish an apples-to-apples comparison:**
1. Re-run backtests using `scalp_engine.run_opens_range` (current HLC code) over the same date ranges
2. Compare results against the live paper trading engine (which also uses `scalp_engine`)
3. Complete the `backtest_runs` and `backtest_trades` tables (currently all RUNNING, 0 trades)
