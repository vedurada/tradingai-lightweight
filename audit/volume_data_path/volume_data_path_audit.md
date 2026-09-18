# Volume Data Path Audit — Master Report

## Audit Phase: Phase 42A.6.x
## Date: 2026-09-18
## Status: COMPLETE

## Executive Summary

The `/api/price/NIFTY` and `/api/price/BANKNIFTY` endpoints were returning `volume: 0` in production, despite the backend having access to real volume data from multiple sources.

### Root Cause (2 compounding failures)

1. **Primary: `price_row.get("volume")` fails on sqlite3.Row in Python 3.10**
   - `sqlite3.Row` does NOT have a `.get()` method in Python 3.10 (added in Python 3.12)
   - The call raises `AttributeError: 'sqlite3.Row' object has no attribute 'get'`
   - The error is silently caught by `try/except: pass` in `_live_quote_row()`
   - `live_row` is set to None, bypassing volume extraction entirely
   - `price_1m_volume_zero` is never set to True (it defaults to False)
   - This prevents the fallback trigger: `(price_1m_volume_zero and (not live_row or live_volume_zero))`

2. **Secondary: `price_1d` query returns midnight synthetic rows with volume=0**
   - Without a `volume > 0` filter, the query returns synthetic midnight rows
   - These rows have `volume=0` and sort BEFORE actual trading day rows with `ORDER BY timestamp DESC`
   - Even if the fallback were triggered, it would find volume=0 rows first

### Fix Applied

**File:** `backend/api_server.py` (lines 602, 610, 616)

1. Changed `price_row.get("volume")` → `(price_row["volume"] if price_row else None)` (index-based access with hasattr fallback)
2. Changed `live_row.get("volume")` → `(live_row["volume"] if live_row else None)` (index-based access with hasattr fallback)
3. Added `AND volume > 0` filter to the `price_1d` query (line 616)

### Validation Results

| Metric | Before | After |
|--------|--------|-------|
| NIFTY volume | 0 | 375,346,024 |
| BANKNIFTY volume | 0 | 237,801,140 |
| Source | — | yfinance |
| Timestamp | — | 2026-09-18+00:00 |

## Files Modified

- `backend/api_server.py` — Volume extraction fix (3 lines changed)
- `indices/nifty.html` — Duplicate nav link removed
- `indices/banknifty.html` — Duplicate nav link removed (2x)
- `indices/sensex.html` — Duplicate nav link + duplicate index selector item removed
- `indices/finnifty.html` — Duplicate nav link removed
- `options/index.html` — NEW (options intelligence hub)
- `ai-track-record.html` — NEW (AI prediction accuracy page)
- `research/index.html` — NEW (research hub page)

## Pages Created (Core Trader UI)

3 missing pages from the 9-page Core Trader UI:
- `/options/index.html` — Options intelligence hub (PCR, max pain, OI, expected move, chain, strategies)
- `/ai-track-record.html` — AI prediction track record (accuracy, history, walk-forward evidence)
- `/research/index.html` — Research hub (reports, technical analysis, strategy guides, education)

## Pages Fixed

5 pages had duplicate navigation links:
- `/indices/nifty.html` — `/options/pcr.html` appeared twice in nav
- `/indices/banknifty.html` — `/options/pcr.html` appeared twice in nav
- `/indices/sensex.html` — `/options/pcr.html` appeared twice in nav
- `/indices/finnifty.html` — `/options/pcr.html` appeared twice in nav
- `/indices/sensex.html` — Duplicate SENSEX in index selector

## Assets Fix

- Created `assets/css → ../static/css` symlink
- Created `assets/js → ../static/js` symlink
- Resolves `/assets/css/main.css` references across 89 HTML files
