# Phase 5.12 — Rigorous HLC No-Lookahead Historical Backtest

## Environment

- Host: `webserver` (Oracle VM)
- Application root: `/opt/tradingai`
- Database: `/opt/tradingai/database/tradingai.db` (read-only)
- Report directory: `/opt/tradingai/research/phase512_backtest_20261029_211000/`

## Phase A — Strategy and Data Audit

### Strategy Rules (Frozen)

See `STRATEGY_RULES_FROZEN.md`.

| Component | Value |
|-----------|-------|
| Signal condition | 3 consecutive 5m candles with higher H/L/C (BULL) or lower H/L/C (BEAR) |
| Signal candle | 3rd confirming candle (candles[i]) |
| Entry candle | Next candle (candles[i+1]) |
| Entry price | Entry candle's open |
| Stop (BULL) | Signal candle low − 1.0 |
| Stop (BEAR) | Signal candle high + 1.0 |
| Risk | \|entry − stop\| |
| Target | entry ± 1.5 × risk |
| Stop-first tie-break | Yes (same candle hits both → STOP) |
| EOD exit | Last session candle close |
| Session boundary | Stop scanning when candle date changes |
| Mode C | One open position per instrument |

### Data Coverage

See `DATA_COVERAGE_AND_QUALITY.md`.

| Instrument | Candles | Sessions | Date Range | Gaps |
|-----------|---------|----------|------------|------|
| NIFTY | 6,071 | 81 | 2026-07-06 to 2026-10-29 | 1 (Oct 15, 11:40-11:55) |
| BANKNIFTY | 6,071 | 81 | 2026-07-06 to 2026-10-29 | 1 (Oct 15, 11:40-11:55) |
| INDIA_VIX | 4,794 | 62 | 2026-07-29 to 2026-10-29 | — |

### Phase 5.1 Comparison

Phase 5.1 used 3 days (Oct 27-29) with 63 trades, 57.14% WR, +713.94 points. Phase 5.12 uses 81 days with 729 trades, 72.43% WR, +19,210.95 points. The difference is due to larger sample size and the fact that Phase 5.1 used live paper trading with entry guard filtering.

## Phase B — Isolated Research Harness

Built in `/tmp/phase512_backtest2.py`. Reuses canonical `_scan_signals` and `_trade_for` from `app/research/scalp_engine.py`. No production code modified. No services started. No DB writes.

## Phase C — Strict Chronological Simulation

Processed day-by-day. For each day, added today's candles to available set, scanned for signals, processed only those whose entry candle is today. Mode C enforced (one open position per instrument). No future data used in signal detection.

## Phase D — Lookahead-Bias Test Suite

See `NO_LOOKAHEAD_TEST_RESULTS.md`. 14/14 tests PASS.

## Phase E — Historical Performance

See `TRADE_LEDGER.csv`, `DAILY_PERFORMANCE.csv`, `MONTHLY_PERFORMANCE.csv`, `INSTRUMENT_COMPARISON.csv`.

### Summary

| Metric | NIFTY | BANKNIFTY | Combined |
|--------|-------|-----------|----------|
| Trades | 382 | 347 | 729 |
| Wins | 278 | 250 | 528 |
| Losses | 104 | 97 | 201 |
| Win Rate | 72.77% | 72.05% | 72.43% |
| Total Points | 5,278.58 | 13,932.37 | 19,210.95 |
| Profit Factor | 3.74 | 3.39 | 3.47 |
| Max Drawdown | 105.13 | 412.50 | 442.40 |
| Max Consec Losses | 5 | 4 | 6 |
| Expectancy (R) | 0.807 | 0.779 | 0.794 |

### Out-of-Sample (Test Period: last 17 days)

| Metric | Value |
|--------|-------|
| Trades | 161 |
| Win Rate | 78.26% |
| Total Points | 5,763.37 |
| Profit Factor | 4.34 |
| Max Drawdown | 250.15 |
| Expectancy (R) | 0.953 |

### Monthly Performance

| Month | Trades | WR | Points | PF |
|-------|--------|-----|--------|-----|
| 2026-07 | 177 | 70.06% | 6,549.19 | 3.19 |
| 2026-08 | 177 | 67.23% | 2,733.73 | 2.99 |
| 2026-09 | 194 | 69.59% | 3,277.97 | 3.02 |
| 2026-10 | 181 | 77.90% | 6,650.07 | 4.77 |

## Phase F — Compare with Existing Engine

See `LIVE_ENGINE_COMPARISON.md`.

The existing production decision path is CPR-driven. HLC has been used as a separate research/paper-trading path. No production code changed to make results match.

## Final Status

**PARTIAL — SOME TESTS PASS BUT EVIDENCE OR DATA IS INSUFFICIENT**

Reasons:
- Only 3.5 months of data (not 12+ months)
- No transaction cost sensitivity analysis performed
- No market regime classification
- Historical data only (no live validation)
- Phase 5.1 comparison shows different results (sample size difference)
