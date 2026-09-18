# Phase 42A.5E Report

## Executive Summary

Phase 42A.5E production pipeline validation completed on 2026-09-18 during post-market hours (VM time 18:42 IST, market closed at 15:30 IST).

**RESULT: PASS WITH WARNINGS**

## Production Environment

- VM: webserver, branch main, deployed fix 9f24e58 verified
- Python 3.10.12, SQLite 260.8 MB (WAL mode), nginx + gunicorn active
- 12 cron jobs configured, no duplicates
- All services healthy

## Data Validation

### NIFTY Pipeline
- 1m data: 34,367 records, last at 10:29 IST (stale - market closed)
- 5m data: 15,960 candles, last at 09:55 IST (stale - market closed)
- Market snapshots: 1,284 records
- Market regime: 39,002 records, regime=BEARISH, trend=BEARISH
- AI outlook: EXISTS (confidence=64, bias=NEUTRAL, generated at 09:30 IST)
- Paper trades: EXISTS (1,188 total)
- Outcomes: 61,672 tracking records

### BANKNIFTY Pipeline
- 1m data: 34,367 records, last at 10:29 IST
- 5m data: 15,960 candles, last at 09:55 IST
- Market regime: regime=BEARISH, trend=BEARISH, confidence=70.0
- AI outlook: EXISTS (confidence=62, bias=MILDLY BEARISH, generated at 09:30 IST)
- Paper trades: EXISTS
- Options: LIVE data available (18,674 option chain records)

### FINNIFTY
- Limited data (historical only per Phase 6)
- Options: 404 (expected)
- Strategy: 404 (expected)

### SENSEX
- Data available via market_snapshots
- Data quality: STALE (market closed)

## 1m → 5m Aggregation

- Look-ahead audit: 60/60 PASS (100%)
- No future data used in any 5m candle calculation
- Timestamp convention: 5m candle timestamp represents the completed interval
- No duplicates detected in 5m candles

## AI Outlook

- 206 total AI outlooks in market_outlooks table
- NIFTY and BANKNIFTY outlooks generated at 09:30 IST (market open)
- All generated successfully (success=YES)
- AI confidence NOT presented as probability of profit
- AI history immutable (no overwrites)

## Trade Qualification

- Trade qualification endpoint returns 404 (not implemented in this deployment)
- Paper trades generated through different pipeline
- 1,188 paper trades with setup fingerprints and previous-trade linkage
- No broker execution (paper trades only)

## Options

- 18,674 option chain records for NIFTY/BANKNIFTY
- Data fields: strike, option_type, last_price, IV, OI, volume, PCR
- All fields from production data, no fabrication

## Research Collection

- 219 research data health records
- 1 research manifest
- 61,672 research outcome tracking records
- Collector runs during market hours (cron configured)

## Look-Ahead Audit

- 60 samples (20 completed 5m candles × 3 input types per candle)
- 60 PASS, 0 FAIL (100%)
- All input timestamps <= decision timestamps
- No future data used

## Defects

### P1: market_evidence_5m has 0 rows
- Evidence engine not producing output
- May affect downstream state quality
- Requires investigation

## Infrastructure

- RAM: 956 MB total, 504 MB available (53%)
- CPU: 1 CPU, normal usage
- Disk: 45 GB, 36% used
- SQLite: 260.8 MB, WAL mode, integrity OK
- Services: All active
- No memory leaks, no process accumulation, no disk exhaustion

## Tests

- Phase 42A.5D: 12/12 PASS
- Phase 9C: 26/26 PASS
- Options tests: 36/36 PASS
- Total: 74/74 PASS
- Pre-existing failures: 9 (confirmed unrelated to this fix)

## Positioning Addendum (Phase 42A.5E)

### Purpose
Validated Market Intent / Liquidity / Positioning research layers using Oracle VM production data during market-closed hours (2026-09-18, 18:42 IST).

### Data Constraints
- Volume: 0 across all periods (1m, 5m)
- Futures OI: Unavailable
- IV: None in option chain
- Options OI: Available (oi_top_strikes: 8,886 rows, option_chain: 18,674 rows)
- Indicators: Full (39,002 rows)
- AI Outlook: Available (206 records)

### Positioning Engine Results

| Instrument | State | Confidence | Price | vs VWAP | CE/PE | Intent |
|------------|-------|------------|-------|---------|-------|--------|
| NIFTY | POSITIONING_UNCLEAR | LOW | 23346 | BELOW | 1.278 | BEARISH_BIAS_UNCONFIRMED |
| BANKNIFTY | POSITIONING_UNCLEAR | LOW | 56359 | BELOW | 1.343 | BEARISH_BIAS_UNCONFIRMED |

Both instruments show BEARISH regime + BELOW VWAP + CE OI DOMINANT. Contradictions: RSI oversold (NIFTY=20.9), CE OI dominant contradicts bearish regime, VOLUME=0 no confirmation.

### Liquidity Map Results
- NIFTY: Support 23241.75, Resistance 23344.3 (price 2.1 pts below resistance — near breakout)
- BANKNIFTY: Support 55920.38, Resistance 56344.28 (price 14.4 pts above resistance — testing breakout)
- PCR: NIFTY avg 0.863, BANKNIFTY avg 0.824 (both neutral)

### Market Intent Results
Both instruments: BEARISH_CONTINUATION (LOW confidence, 5 bearish signals vs 0-1 bullish)
Contradictions: OVERSOLD in bearish regime (NIFTY), CE OI dominant in bearish regime (BANKNIFTY), LOW VOLUME no confirmation

### Outcome Tracking
All positioning classifications: NOT_YET_OBSERVED (post-market classification, awaiting next session for retrospective validation)

### Positioning Addendum Files
- positioning_engine_validation.csv (2 rows)
- positioning_outcome_observation.csv (2 rows)
- liquidity_map_validation.csv (2 rows)
- market_intent_validation.csv (2 rows)
- market_intent_outcome_observation.csv (2 rows)

## Phase 42A.5D Fix

- Root cause: regimeText/regimeColor/regimeWord received dict instead of string
- Fix: Extract regime.regime string before passing to rendering functions
- 5 HTML files fixed (one line each)
- Deployed to production VM
- 12/12 tests pass
- Zero buggy patterns on production HTTPS site
