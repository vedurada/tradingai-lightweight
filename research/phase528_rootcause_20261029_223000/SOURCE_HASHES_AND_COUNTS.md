# Phase 5.28 — Source Hashes and Counts

## File Hashes

| File | Hash | Rows |
|------|------|------|
| TRADE_LEDGER.csv | 2816c4b727cfb8ad47b41a2e9e768b0ab1bcefc1bd3ba18487f1c493ce0c2e3a | 974 (+1 header) |
| TRADE_LEDGER_NIFTY.json | c2e252c1e3a8522b16ad881cb21a62bd03a115a6c8365c56c91b7a1b944c342b | 382 trades |
| TRADE_LEDGER_BANKNIFTY.json | 9256729dcc1e43715bad4a489104c7a9fa5304ecf85babee1ed297b0103af2da | 347 trades |
| 245_ROW_DISCREPANCY_CLASSIFICATION.csv | dc845982ad078bc96e3a0a69df4a4469e02c53d493f1904ae1f8f9f528e8b6e2 | 974 rows |

## Counts

- JSON trades: 729 (382 NIFTY + 347 BANKNIFTY)
- CSV rows: 974
- Extra CSV rows: 245
- Exact duplicates: 0
- All 974 keys unique by (instrument, entry_time, direction)
