# Phase 5.15 — Ledger Discrepancy Status

## Status: UNRESOLVED

The 245-row discrepancy between TRADE_LEDGER.csv (974 rows) and the authoritative JSON files (729 trades) remains unresolved.

## Summary

| Source | Rows | Status |
|--------|------|--------|
| TRADE_LEDGER_NIFTY.json | 382 | Authoritative |
| TRADE_LEDGER_BANKNIFTY.json | 347 | Authoritative |
| TRADE_LEDGER.csv | 974 | Unreliable (245 extra rows) |

## Classification of 245 Extra Rows

| Category | Count | Description |
|----------|-------|-------------|
| CLOSE_ENTRY_TIME | 197 | Entry time within 1 hour of a JSON trade on same day/instrument |
| NEW_SIGNAL_NOT_IN_JSON | 48 | No close JSON trade on that day/instrument |

## Root Cause

The first backtest script (phase512_backtest.py) processed candle-by-candle and used _scan_signals with last-candle detection, generating additional signals that the second script (day-by-day, phase512_backtest2.py) filtered out by requiring entry_candle['date'] == current_day.

## Resolution

Use JSON files as the authoritative trade ledger. Regenerate any CSV-based analysis from JSON. Do not delete or modify the CSV.
