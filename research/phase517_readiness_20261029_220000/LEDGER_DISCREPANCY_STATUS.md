# Phase 5.17 — Ledger Discrepancy Status

## Status: UNRESOLVED

### Counts

| Source | Rows | Status |
|--------|------|--------|
| TRADE_LEDGER_NIFTY.json | 382 | Authoritative |
| TRADE_LEDGER_BANKNIFTY.json | 347 | Authoritative |
| TRADE_LEDGER.csv | 974 | Unreliable (245 extra rows) |

### Classification of 245 Extra Rows

| Category | Count | Description |
|----------|-------|-------------|
| CLOSE_ENTRY_TIME | 197 | Entry time within 1 hour of a JSON trade on same day/instrument |
| NEW_SIGNAL_NOT_IN_JSON | 48 | No close JSON trade on that day/instrument |

### Root Cause

First backtest script (phase512_backtest.py) processed candle-by-candle with last-candle detection, generating 245 extra signals that the day-by-day script filtered out.

### Resolution

Use JSON files as authoritative. Do not delete or modify CSV. Regenerate analysis from JSON if needed.

### Index-Point vs Option-Level

- All metrics are in index points (NIFTY/BANKNIFTY)
- No option premium data available
- No conversion to rupees (no contract specifications)
- Option-level profitability: NOT VERIFIED
