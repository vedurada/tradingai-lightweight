# Phase 35 Bug Register — Updated

Date: 2026-09-16
Status: IN PROGRESS

## Bugs Fixed
### BUG-001 ✅ | P0 | /api/risk/FINNIFTY 404 | Added FINNIFTY to allowed symbols | FIXED
### BUG-002 ✅ | P0 | /api/maxpain 500 | Fixed OptionsEngine import + graceful handling | FIXED
### BUG-003 ✅ | P0 | /api/pcr-history 500 | Fixed by BUG-002 | FIXED
### BUG-004 ✅ | P0 | /api/key-levels wrong supports/resistances | support_resistance JSON in indicators table wrong (all supports above spot 23,217); root cause: indicators table support_resistance column populated with incorrect values; fixed key-levels endpoint (market_state.build_market_state) and daily_page.py to use pivot/r1/s1/r2/s2/r3/s3 columns; also regenerated indicators table and NIFTY daily pages | FIXED

## Bugs Open
### BUG-005 | P1 | option_chain empty | Root cause: yfinance returns 0 Indian options expirations, NSE API returns 404 | DATA SOURCE LIMITATION — not fixable without new data source | DEFERRED (monitor NSE API)
### BUG-006 | P1 | /api/oi-top returns [] | Root cause: oi_top_strikes table empty (same data source) | DEFERRED (same as BUG-005)
### BUG-007 | P1 | /api/backtest 202 async | Jobs complete but frontend doesn't properly poll | OPEN

## Data Source Findings
- yfinance: 0 expirations for ^NSEI (NIFTY), ^NSEBANK (BANKNIFTY)
- NSE API: 404 (unstable/disabled endpoint)
- option_chain: 0 rows (correct — no data source available)
- Pages correctly show UNAVAILABLE (not fabricated data)
- This is an external dependency issue, not a code bug

## Additional Fixes (Phase 35)
- Regenerated indicators.support_resistance column for all symbols using pivot/r1/s1 calculation (S3<S2<S1<Spot<R1<R2<R3)
- Regenerated NIFTY daily outlook/close pages (2026-09-15, 2026-09-16) with correct support/resistance