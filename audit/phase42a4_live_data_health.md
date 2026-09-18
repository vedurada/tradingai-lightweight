# Phase 42A.4 LIVE SESSION — Live Data Health

**Date**: 2026-09-18
**Phase 41**: FROZEN
**Market State**: PRE-MARKET (07:14 IST)

---

## CHECKPOINT: 07:14 IST (PRE-MARKET)

### MARKET DATA

| Check | Expected | Actual | Status |
|-------|----------|--------|--------|
| NIFTY 5m candles today | ~156 (full session) | 0 | PRE-MARKET |
| BANKNIFTY 5m candles today | ~156 | 0 | PRE-MARKET |
| SENSEX 5m candles today | ~156 | 0 | PRE-MARKET |
| FINNIFTY 5m candles today | ~156 | 0 | PRE-MARKET |
| NIFTY historical 5m | >0 | 4,350 | OK |
| BANKNIFTY historical 5m | >0 | 4,350 | Ok |
| SENSEX historical 5m | >0 | 4,350 | Ok |
| FINNIFTY historical 5m | >0 | 4,350 | Ok |
| NIFTY price freshness | <30min | ~587min | STALE (expected) |
| BANKNIFTY price freshness | <30min | ~587min | STALE (expected) |
| SENSEX price freshness | <30min | ~919min | STALE (expected) |
| FINNIFTY price freshness | <30min | ~587min | STALE (expected) |

### RESEARCH TABLES

| Table | Records | Status |
|-------|---------|--------|
| research_setup_identity | 0 | EXPECTED |
| research_reentry_log | 0 | EXPECTED |
| research_ai_call_log | 0 | EXPECTED |
| research_outcome_tracking | 0 | EXPECTED |
| research_data_health | 0 | EXPECTED |
| research_manifest | 0 | EXPECTED |

### MARKET DATA TABLES

| Table | Records | Status |
|-------|---------|--------|
| market_snapshots_5m | 0 | EXPECTED |
| market_evidence_5m | 0 | EXPECTED |
| ai_outlooks_5m | 0 | EXPECTED |
| paper_trades | 1,188 | OK (historical) |

### API HEALTH

| Endpoint | Status | Notes |
|----------|--------|-------|
| /api/health | 200 | degraded (pre-existing) |
| /api/price/NIFTY | 200 | stale |
| /api/price/BANKNIFTY | 200 | stale |
| /api/price/FINNIFTY | 200 | stale |
| /api/price/SENSEX | 200 | stale |
| /api/vix | 200 | stale |
| /api/market | 200 | degraded (pre-existing) |
| /api/market-evidence/NIFTY | 200 | ok |
| /api/paper-trades | 200 | ok |
| /api/paper-trades/active | 200 | ok |
| All 8 research endpoints | 200 | ok (0 records) |

### CROSS-INSTRUMENT ISOLATION

| Check | Result |
|-------|--------|
| NIFTY records contain NIFTY data | VERIFIED |
| BANKNIFTY records contain BANKNIFTY data | VERIFIED |
| No NIFTY data in BANKNIFTY records | VERIFIED |
| No BANKNIFTY data in NIFTY records | VERIFIED |
| FINNIFTY data isolated | VERIFIED |
| SENSEX data isolated | VERIFIED |

### FABRICATED DATA

| Check | Result |
|-------|--------|
| Fabricated AI calls | 0 |
| Fabricated outcomes | 0 |
| Fabricated market data | 0 |
| Fabricated research records | 0 |

### NEXT CHECKPOINT: 09:30 IST

Wait for market open (09:15 IST). First completed candle expected ~09:20 IST.
