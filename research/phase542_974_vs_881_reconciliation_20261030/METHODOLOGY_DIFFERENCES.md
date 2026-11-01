# Phase 5.42 — Methodology Differences (974 vs 881)

## Purpose
Explain why the new deterministic 974-trade replay differs from the earlier 881-trade candle-by-candle ledger.

## Identified Differences
1. Dataset coverage / date range and candle counts (6071 candles per instrument in new replay).
2. Candle-by-candle versus full-history scan replay implementation.
3. Signal generation and final-candle handling.
4. Entry and exit calculations and field semantics (points vs mfe_pts / excursion vs realised P&L).
5. Expiry / overnight / session filtering.
6. Duplicate handling.
7. EOD exits and missing stop exits.

## Note
Do not assume 974 is better than 881 or vice versa.

## Status
INVESTIGATION_CONTINUING
