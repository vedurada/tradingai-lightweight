# Phase 42A.6 Data Quality Findings

## Volume=0 Root Cause (BLOCKER - RESOLVED)

**Finding**: All Indian indices (NIFTY, BANKNIFTY, FINNIFTY, SENSEX, VIX) show volume=0 across price_1m, price_5m, and live_quotes tables.

**Root Cause**: Three compounding failures:
1. yfinance returns volume=0 for Indian indices (^NIFTY, ^BANKNIFTY)
2. NSE source hardcodes `"volume": 0` in nse_source.py:90 (NSE allIndices API doesn't provide index volume)
3. API routing bug in api_server.py:599 — when price_1m has data (even volume=0), fallback to price_1d (which has REAL volume from bhavcopy) is never reached

**Fix Applied**: Modified api_server.py to also fall back to price_1d when price_1m volume is zero. price_1d has real volume from NSE bhavcopy EOD CSV (e.g., NIFTY today: 375M).

**Evidence**: price_1d NIFTY today: volume=375,346,024 (REAL). price_1m NIFTY: volume=0 (100% zero).

## Options IV Unavailable

**Finding**: All NIFTY option_chain records have implied_volatility=NULL.

**Impact**: Options expected movement calculation cannot use IV-based models. Volume-dependent confirmations disabled.

## Futures OI Unavailable

**Finding**: No futures_oi table exists. Only options OI available via oi_top_strikes.

**Impact**: Futures positioning analysis not possible. Options OI from oi_top_strikes used as proxy.

## PCR Stale

**Finding**: pcr_history has only 9 rows (daily, 3 symbols). Not sufficient for intraday PCR analysis.

## Data Quality Summary

| Field | Status | Notes |
|-------|--------|-------|
| Price | AVAILABLE | Real data from yfinance |
| Volume | UNAVAILABLE | Indices lack volume data; price_1d has EOD volume from bhavcopy |
| VWAP | AVAILABLE | Computed from zero-volume candles (potentially unreliable) |
| Options Chain | AVAILABLE | 18,674 records for NIFTY/BANKNIFTY |
| IV | UNAVAILABLE | All NULL in option_chain |
| OI | AVAILABLE | oi_top_strikes: 8,886 rows |
| PCR | STALE | 9 rows, daily frequency |
| VIX | AVAILABLE | 2,570 rows |
| Indicators | AVAILABLE | 39,002 rows, full technical set |
| Market Regime | AVAILABLE | 39,002 rows |
| Historical Outcomes | AVAILABLE | research_outcome_tracking: 61,672 rows |
