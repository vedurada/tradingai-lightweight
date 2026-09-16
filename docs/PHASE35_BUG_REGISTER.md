# Phase 35 Bug Register

Date: 2026-09-16
Status: IN PROGRESS — bugs being fixed on VM

## Format
ID | Severity | Page/Component | Expected | Actual | Root Cause | Fix | Status

## Bugs Found & Fixed

### BUG-001 ✅ | P0 | /api/risk/FINNIFTY | Risk data for FINNIFTY | 404 "FINNIFTY is not available" | Risk endpoint line 3390: allowed symbols list missing FINNIFTY | Added FINNIFTY to allowed symbols | FIXED

### BUG-002 ✅ | P0 | /api/maxpain | Max pain data per symbol | 500 INTERNAL_ERROR | OptionsEngine import `from backend.options` fails (no backend/__init__.py) | Changed to `from options import OptionsEngine` + graceful empty handling | FIXED

### BUG-003 ✅ | P0 | /api/pcr-history | PCR data | 500 (same import bug) | Same as BUG-002 | Fixed by BUG-002 | FIXED

### BUG-004 | P1 | /api/oi-top | OI top strikes | Returns empty array [] | oi_top_strikes table has 0 rows (data pipeline gap) | Requires data pipeline fix | OPEN

### BUG-005 | P1 | option_chain table | Populated option chain data | 0 rows (option_expiries has 27) | data_fetcher_db.py option fetch fails or returns empty chains | Requires data pipeline fix | OPEN

### BUG-006 | P1 | /api/backtest | Backtest results | Returns 202 "running" (async) | Backtest jobs are async; first poll shows completed with data, second poll shows NOT_FOUND (job expired) | Jobs are ephemeral; frontend needs to poll and display result | OPEN

## Bugs Intentionally Deferred
- instruments table empty (0 rows) — legacy table, symbols (47 rows) is current
- regimes table empty (0 rows) — legacy table, market_regime (12,905 rows) is current
- Empty tables: portfolio, alerts, etf_data, mf_data, history_archive, price_15m, prices, daily_strategy — expected empty, no data source or user-dependent
