# Phase 41 — Backtest Results Documentation
Generated: 2026-09-17

## Method

Historical replay of NIFTY 5-minute candles (2026-08-08 to 2026-09-15)
through the Phase 41 deterministic pipeline:

1. Extract candles from SQLite DB (1,950 candles)
2. Evaluate market evidence per candle (deterministic)
3. Run 6-layer qualification (modified by replay_qualify)
4. Create paper trade on qualified setup
5. Simulate exit (target/stop/session close)
6. Calculate PnL and statistics

**This is NOT AI performance.** All decisions are rules-based.
AI outlook is an input only. See `phase41_ai_attribution.md`.

## Results Summary

| Metric | Value |
|--------|-------|
| Period | 2026-08-08 to 2026-09-15 |
| Candles | 1,950 |
| Eligible (after warm-up) | 1,929 |
| Directional signals | 1,184 (61.4%) |
| Qualified setups | 1,184 (100% of directional) |
| Paper trades | 1,184 |
| Completed | 1,184 |
| Wins | 455 (38.43%) |
| Losses | 644 (54.39%) |
| Breakeven | 85 (7.18%) |

## Performance Metrics

| Metric | Value | Assessment |
|--------|-------|------------|
| Net PnL | -₹130,391.72 | Negative |
| Gross Profit | ₹69,892.74 | Moderate |
| Gross Loss | -₹200,284.47 | High |
| Profit Factor | 0.349 | Poor (<1.0) |
| Avg Win | ₹153.61 | Very small |
| Avg Loss | -₹311.00 | 2x avg win |
| Expectancy | -₹110.13 | Negative |
| Max Drawdown | -₹135,470.57 | Severe |
| Max Consecutive Losses | 37 | High |
| Trades/Day | 45.54 | Excessive |

## Trade Distribution

### By Direction
- BEARISH: 903 trades, 50.2% win rate, PnL: +₹6,904.33
- BULLISH: 281 trades, 0.7% win rate, PnL: -₹137,296.06

### By Outcome
- TARGET_HIT: 894 (75.5%), PnL: +₹6,904.33
- STOPPED: 223 (18.8%), PnL: -₹137,296.06
- EXPIRED: 67 (5.7%), PnL: ₹0

### By Exit Reason
- TARGET_HIT: 894
- STOP_LOSS: 223
- SESSION_CLOSE: 67

## Methodology Notes

1. **Entry**: At close of qualifying candle (no intrabar entry)
2. **Exit**: Scanning forward within same day for target/stop hit
3. **Stop**: Entry × 0.995 (0.5% below entry for BULLISH)
4. **Target**: Entry × 1.015 (1.5% above entry for BULLISH)
5. **No transaction costs**: PnL is gross (no brokerage/slippage)
6. **No look-ahead**: All data ≤ entry candle timestamp
7. **Options data**: NOT available (simulated underlying-only)

## Comparison with Phase 37 Baseline

| Metric | Phase 37 | Phase 41 | Equivalent? |
|--------|----------|----------|-------------|
| Strategy | EMA(9)/21 crossover | Evidence-based qualification | NO |
| Trades | 12 | 1,184 | NO (99x more) |
| Win Rate | 16.67% | 38.43% | NOT comparable |
| Net PnL | -₹90,576 | -₹130,392 | NO (different scale) |
| Holding Period | Days to weeks | Minutes to hours | NO |
| Position Sizing | Same | Same (1 unit) | YES |
| Transaction Costs | Not applied | Not applied | YES |
| Data | Same DB | Same DB | YES |
| Trading Hours | Market hours | 03:00-09:59 (DB range) | NO |

**LABEL: NON-EQUIVALENT BASELINES**

Phase 37 is a conservative rules-based strategy (12 trades over 30 days).
Phase 41 is an aggressive evidence-based system (45 trades/day).
Direct comparison is misleading.

## Files Generated

- `audit/phase41_trade_ledger.csv` — Individual trade records (1,184 rows)
- `audit/phase41_trade_statistics.csv` — Performance statistics
- `audit/phase41_signal_funnel.csv` — Signal funnel data
- `audit/phase41_replay_log.json` — Full replay log with events
