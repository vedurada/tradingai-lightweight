# Phase 41C — Live Site Validation

**Date**: 2026-09-17
**Method**: HTTP requests against public URLs + VM inspection

---

## URL Validation

| URL | HTTP | Content-Type | Title | Canonical | Size |
|-----|------|-------------|-------|-----------|------|
| https://tradingai.in/ | 200 | text/html | AI Market Outlook - NIFTY, BANKNIFTY, FINNIFTY, SENSEX - TradingAI | https://tradingai.in/ | 36511 |
| https://tradingai.in/today/ | 200 | text/html | NIFTY Today — Live Intraday Terminal | https://tradingai.in/today/index.html | 25583 |
| https://tradingai.in/market.html | 200 | text/html | Market Overview - TradingAI | /market.html | — |
| https://tradingai.in/indices/nifty.html | 200 | text/html | NIFTY 50 - AI Market Outlook | https://tradingai.in/indices/nifty.html | 28029 |
| https://tradingai.in/indices/banknifty.html | 200 | text/html | BANKNIFTY 50 - AI Market Outlook | https://tradingai.in/indices/banknifty.html | 25854 |
| https://tradingai.in/indices/sensex.html | 200 | text/html | SENSEX 50 - AI Market Outlook | https://tradingai.in/indices/sensex.html | 19494 |
| https://tradingai.in/indices/finnifty.html | 200 | text/html | FINNIFTY 50 - AI Market Outlook | https://tradingai.in/indices/finnifty.html | 22134 |
| https://tradingai.in/options/pcr.html | 200 | text/html | — | — | — |
| https://tradingai.in/strategies.html | 200 | text/html | — | — | — |
| https://tradingai.in/strategy-builder.html | 200 | text/html | — | — | — |
| https://tradingai.in/tools/backtest.html | 200 | text/html | Backtest — Deterministic Strategy Performance | /tools/backtest.html | 20877 |
| https://tradingai.in/tools/position-size.html | 200 | text/html | — | — | — |

## Home Page (/index.html) — Phase 41 Content Check

| Element | Status |
|---------|--------|
| MARKET SNAPSHOT | PASS |
| AI MARKET OUTLOOK | PASS |
| Trade Qualification | PASS |
| Paper Trade | PASS |
| Market Evidence | PASS |
| NIFTY/BANKNIFTY/VIX data | PASS |
| Market Status | PASS |
| PAPER TRADING disclaimer | PASS |

## Today Page — Phase 41 Content Check

| Element | Status |
|---------|--------|
| Market Snapshot | PASS |
| Market Evidence (6 groups) | PASS |
| Trade Qualification (22 checks) | PASS |
| Paper Trade (active_trades) | PASS |
| AI Outlook | PASS |
| Key Levels | PASS |
| Options Intelligence | PASS |
| Strategy | PASS |
| Risk | PASS |
| PAPER TRADING NO BROKER disclaimer | PASS |

## NIFTY Page — Phase 41 Content Check

| Element | Status |
|---------|--------|
| NIFTY price data | PASS |
| Market Evidence | PASS |
| Trade Qualification | PASS |
| Paper Trade | PASS |
| Key Levels | PASS |
| AI Outlook | PASS |
| Strategy | PASS |
| No cross-instrument contamination | PASS |

## BANKNIFTY Page — Phase 41 Content Check

| Element | Status |
|---------|--------|
| BANKNIFTY data (not NIFTY) | PASS |
| Market Evidence | PASS |
| Trade Qualification | PASS |
| Paper Trade | PASS |
| No NIFTY data contamination | PASS (verified: 0 `nifty-spot` IDs) |

## SENSEX Page — Safety Check

| Element | Status |
|---------|--------|
| Standard market data | PASS |
| No false BUY/SELL/TRADE signals | PASS |
| No Phase 41 sections (as expected) | PASS |

## FINNIFTY Page — Safety Check

| Element | Status |
|---------|--------|
| DATA UNAVAILABLE indicators | PASS (1 occurrence) |
| DATA STALE indicators | PASS (1 occurrence) |
| No BUY CALL/BUY PUT/TRADE QUALIFIED | PASS (0 occurrences) |
| Loading state | PASS (22 occurrences) |

## Issues Found & Resolved

| Issue | Severity | Status |
|-------|----------|--------|
| /var/www/index.html had today page content instead of home page | CRITICAL | FIXED at 21:12 IST by cp from /opt/tradingai/index.html |

## Issues Documented for Phase 42

| Issue | Severity | Description |
|-------|----------|-------------|
| Backtest page lacks explicit "rules-based" labeling | LOW | Page is deterministic backtest (Phase 7) but doesn't explicitly distinguish from AI performance |
| SENSEX/FINNIFTY pages lack Phase 41 sections | LOW | Pages show standard market data; Phase 41 integration optional per spec |
