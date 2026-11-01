# Phase 5.16 — 245-Row Discrepancy

## Status: UNRESOLVED

### Counts

| Source | Rows | Status |
|--------|------|--------|
| TRADE_LEDGER_NIFTY.json | 382 | Authoritative |
| TRADE_LEDGER_BANKNIFTY.json | 347 | Authoritative |
| TRADE_LEDGER.csv | 974 | Unreliable (245 extra) |

### Classification of 245 Extra Rows

| Category | Count | Description |
|----------|-------|-------------|
| CLOSE_ENTRY_TIME | 197 | Entry time within 1 hour of a JSON trade on same day/instrument |
| NEW_SIGNAL_NOT_IN_JSON | 48 | No close JSON trade on that day/instrument |

### Root Cause

The first backtest script (phase512_backtest.py) processed candle-by-candle and used `_scan_signals` with last-candle detection, generating additional signals that the second script (day-by-day, phase512_backtest2.py) filtered out by requiring entry_candle['date'] == current_day.

### Evidence

- All 729 JSON trades are present in the CSV (no JSON-only trades)
- 245 extra CSV rows have unique (instrument, entry_time, direction) keys
- No duplicate keys found among extra rows
- Extra rows cannot be traced to authoritative trade records

### Resolution

Use JSON files as the authoritative trade ledger. The CSV is unreliable and should not be used for analysis. Do not delete or modify the CSV (preserve as evidence).
