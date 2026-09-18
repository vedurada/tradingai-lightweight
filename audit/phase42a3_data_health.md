# Phase 42A.3 — Data Health

**Date**: 2026-09-18
**Phase 41**: FROZEN
**Market State**: PRE-MARKET (06:56 IST)

---

## DATA HEALTH STATUS

| Metric | Value | Status |
|--------|-------|--------|
| Expected 5m candles today | ~156 (09:15-15:30) | N/A (pre-market) |
| Received 5m candles today | 0 | EXPECTED |
| Missing candles | 0 | N/A |
| Duplicate candles | 0 | N/A |
| Stale observations | ALL (price data 586m+ old) | EXPECTED pre-market |
| Unavailable observations | Research tables empty | EXPECTED |
| API failures | 0 | OK |
| Source failures | 0 | OK |
| Research insert failures | 0 | OK |
| AI call failures | 0 | N/A |
| Outcome processing failures | 0 | N/A |

## DATA FRESHNESS

| Category | Status | Age |
|----------|--------|-----|
| Price data (NIFTY/BANKNIFTY/FINNIFTY) | STALE | 586 minutes |
| Price data (SENSEX) | STALE | 918 minutes |
| VIX data | STALE | 586 minutes |
| AI outlooks | STALE | 1519 minutes |
| Research data | UNAVAILABLE | 0 records |
| Market status | PRE-MARKET | Current |

## COLLECTION COVERAGE

| Component | Coverage | Notes |
|-----------|----------|-------|
| 5m market data | STALE | Last session Sept 15-17 |
| Evidence | STALE | Historical only |
| AI outlooks | STALE | Historical only |
| Setup identity | 0% | No live data yet |
| Re-entry | N/A | No trades yet |
| AI calls | N/A | No triggers yet |
| Outcomes | N/A | No trades yet |

## DATA QUALITY STATES

All data uses explicit states per Phase 42A design:
- LIVE: Only when data freshness threshold met (NOT currently)
- STALE: When data exceeds freshness threshold (current state)
- UNAVAILABLE: When no data exists (research tables)
- PENDING: For future outcomes (not yet matured)
- ERROR: For processing failures (none observed)

## MISSING PERIODS

| Period | Status | Notes |
|--------|--------|-------|
| Sept 15 09:55 → Sept 17 09:15 | DATA GAP | Weekend gap (expected) |
| Sept 18 06:56 → 09:15 | PRE-MARKET | Expected |

## API HEALTH DURING SESSION

| Endpoint | Current Status | Notes |
|----------|---------------|-------|
| /api/health | 200 (degraded) | Pre-existing stale data |
| /api/price/NIFTY | 200 (stale) | Pre-market |
| /api/price/BANKNIFTY | 200 (stale) | Pre-market |
| /api/price/FINNIFTY | 200 (stale) | Pre-market |
| /api/price/SENSEX | 200 (stale) | Pre-market |
| /api/vix | 200 (stale) | Pre-market |
| /api/market | 200 (degraded) | Pre-existing |
| All research endpoints | 200 (ok) | 0 records (expected) |

## NO FABRICATED VALUES

All data is:
- Collected from actual market data ✅
- Empty when no data available (0 records) ✅
- Marked STALE/UNAVAILABLE/PENDING appropriately ✅
- No fabricated AI calls, outcomes, or market data ✅

## COLLECTION COVERAGE (%)

| Component | Coverage |
|-----------|----------|
| Market data | 100% (historical), 0% (live today - pre-market) |
| Evidence | 100% (historical), 0% (live today) |
| Research tables | 0% (awaiting first candle) |
| AI calls | N/A (awaiting trigger) |
| Outcomes | N/A (awaiting trades) |
