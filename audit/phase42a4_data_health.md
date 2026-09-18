# Phase 42A.4 — Data Health

**Date**: 2026-09-18
**Phase 41**: FROZEN
**Market State**: PRE-MARKET (06:56 IST)

---

## DATA HEALTH STATUS

| Check | Result |
|-------|--------|
| Expected 5m candles today | ~156 (09:15-15:30 IST) |
| Received 5m candles today | 0 (PRE-MARKET) |
| Missing candles | 0 (no session observed) |
| Duplicate candles | 0 |
| Stale observations | ALL (pre-market) |
| Unavailable observations | Research tables (0 records) |
| API failures | 0 |
| Source failures | 0 |
| Processing failures | 0 |
| Research insert failures | 0 |
| AI call failures | 0 |
| Outcome processing failures | 0 |

## COVERAGE

| Component | Coverage | Notes |
|-----------|----------|-------|
| Market data | 100% historical | Historical data complete |
| Research tables | 0% | Awaiting first candle |
| AI calls | N/A | No triggers |
| Outcomes | N/A | No trades |

## DATA FRESHNESS

| Category | Status | Age |
|----------|--------|-----|
| NIFTY price | STALE | ~587 minutes |
| BANKNIFTY price | STALE | ~587 minutes |
| SENSEX price | STALE | ~919 minutes |
| FINNIFTY price | STALE | ~587 minutes |
| VIX | STALE | ~587 minutes |
| AI outlooks | STALE | ~1520 minutes |
| Research data | UNAVAILABLE | 0 records |

## COLLECTION COVERAGE (%)

| Component | Coverage |
|-----------|----------|
| Market data | 100% historical |
| Evidence | 100% historical |
| Research tables | 0% (pre-market) |
| AI calls | N/A |
| Outcomes | N/A |

## NO FABRICATED VALUES

All data:
- ✅ Collected from actual market data (where available)
- ✅ Empty when no data available (0 records)
- ✅ Marked STALE/UNAVAILABLE/PENDING appropriately
- ❌ No fabricated AI calls
- ❌ No fabricated outcomes
- ❌ No fabricated market data
