# Phase 5.12 — Limitations and Assumptions

## Data Limitations

1. Only 3.5 months of data (Jul 29 - Oct 29, 2026) — not 12+ months
2. INDIA_VIX data starts Jul 29 (23 days later)
3. One session with missing candles (Oct 15)
4. No volume analysis
5. No market regime classification

## Assumptions

1. Stop-first tie-break when both stop and target hit in same candle
2. EOD exit at last session candle close
3. Mode C (one open position per instrument) enforced
4. No transaction costs deducted (gross points only)
5. No slippage modeled
6. All candles are treated as completed (is_complete=1)

## Test Limitations

1. Synthetic lookahead tests use 100 candles (not full dataset)
2. No live-session validation performed
3. No test for provider publication latency
4. No test for live partial-candle handling

## Comparison with Phase 5.1

Phase 5.1 (3 days, 63 trades, 57.14% WR) vs Phase 5.12 (81 days, 729 trades, 72.43% WR):
- Larger sample size in Phase 5.12
- Phase 5.1 used live paper trading with entry guard filtering
- Phase 5.12 uses all historical signals (no entry guard)
- Difference in win rate may be due to sample size and filtering
