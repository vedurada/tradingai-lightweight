# Phase 5.26 — Discrepancies and Limitations

## Paper Trades vs Replay

- 30 SCALP_HLC paper trades exist (Sep 25 - Oct 28)
- Replay generates 729 trades over 81 sessions
- Only overlapping period can be compared
- Live paper trades use entry guard (5-min window) which filters some signals
- Replay uses all signals (no entry guard filtering)

## 245-Row CSV Discrepancy

TRADE_LEDGER.csv has 974 rows vs 729 in JSON. 245 extra rows unexplained. JSON is authoritative.

## Data Limitations

1. Only 3.5 months of data (not 12+ months)
2. INDIA_VIX data starts Jul 29 (23 days later)
3. One session with missing candles (Oct 15)
4. No option premium data
5. No volume analysis
6. No market regime classification

## Execution Assumptions

1. Stop-first tie-break when both stop and target hit same candle
2. EOD exit at last session candle close
3. Mode C (one open position per instrument)
4. No transaction costs (gross points only)
5. No slippage modeled
