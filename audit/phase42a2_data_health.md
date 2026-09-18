# Phase 42A.2 — Data Health

**Date**: 2026-09-18
**Phase 41**: FROZEN

---

## RESEARCH DATA HEALTH

### Current State (Pre-Market)

| Table | Records | Health |
|-------|---------|--------|
| research_setup_identity | 0 | HEALTHY (expected pre-market) |
| research_reentry_log | 0 | HEALTHY |
| research_ai_call_log | 0 | HEALTHY |
| research_outcome_tracking | 0 | HEALTHY |
| research_data_health | 0 | HEALTHY |
| research_manifest | 0 | HEALTHY |

### Data Health Checks (When Active)

The research_data_health table will track:

| Check | Purpose |
|-------|---------|
| Stale data detection | Flag aging price data |
| Missing candles | Detect gaps in 5m sequence |
| Duplicate timestamps | Prevent double-processing |
| Missing evidence | Flag candles without evidence |
| Missing AI where expected | Flag missed triggers |
| Orphan records | Detect referential integrity issues |
| Timestamp inconsistencies | Find out-of-order data |
| Source failures | Track data source availability |

### Warning vs Failure Policy

EXPECTED UNAVAILABLE vs ACTUAL APPLICATION FAILURE:
- Market closed → STALE data (EXPECTED, not failure)
- Options data unavailable → UNAVAILABLE (EXPECTED, not failure)
- AI service down → FAILED (actual failure, logged)
- Database connection lost → FAILURE (actual, logged)

Warnings are NOT converted to failures artificially.

## RESEARCH MANIFEST

### Current State

research_manifest has 0 records — no data collected yet (pre-market).

### Expected Manifest Fields (When Active)

| Field | Purpose |
|-------|---------|
| dataset | Dataset identifier |
| instruments | Covered instruments |
| earliest_data | First data timestamp |
| latest_data | Last data timestamp |
| row_count | Total records |
| schema_version | Schema version |
| engine_version | Engine version |
| data-quality | Data quality assessment |

### Important: DO NOT CLAIM

❌ "90 days sufficient"
❌ "Statistically validated"

This is only the BEGINNING of prospective collection.

## API DATA HEALTH

### Health Check API

| Endpoint | Status | Data Age | Notes |
|----------|--------|----------|-------|
| /api/health | 200 OK | 588m stale | Degraded (pre-existing) |
| /api/price/NIFTY | 200 OK | 588m stale | Pre-market |
| /api/price/BANKNIFTY | 200 OK | 588m stale | Pre-market |
| /api/price/FINNIFTY | 200 OK | 588m stale | Pre-market |
| /api/price/SENSEX | 200 OK | 918m stale | Pre-market |
| /api/vix | 200 OK | 588m stale | Pre-market |
| /api/market | 200 OK | degraded | Pre-existing |
| /api/market-evidence/NIFTY | 200 OK | ok | Historical data |
| /api/paper-trades | 200 OK | ok | Historical data |
| /api/paper-trades/active | 200 OK | ok | No active trades |

### Research API Health

| Endpoint | Status | Records |
|----------|--------|---------|
| /api/research/summary | 200 | All 0 (expected) |
| /api/research/data-health | 200 | All 0 (expected) |
| /api/research/coverage | 200 | 6 datasets listed |
| /api/research/setups | 200 | Empty (expected) |
| /api/research/reentries | 200 | Empty (expected) |
| /api/research/ai-history | 200 | Empty (expected) |
| /api/research/manifest | 200 | Empty (expected) |

## DATA FRESHNESS POLICY

### During Market Hours

| Status | Criteria |
|--------|----------|
| FRESH | Data within freshness threshold |
| STALE | Data exceeds freshness threshold |
| UNAVAILABLE | No data available |

### Pre-Market / Post-Market

| Status | Display |
|--------|---------|
| Last session data | Historical/last-session context |
| LIVE label | NEVER used for non-fresh data |
| MARKET CLOSED · LAST SESSION DATA | Used after market close |
| PRE-MARKET | Used before market open |

### Verification

The website/API must NOT show:
- ❌ LIVE when data is actually stale
- ❌ LIVE before market open
- ❌ LIVE after market close

## DATA QUALITY FLAGS

| Flag | Meaning | Current |
|------|---------|---------|
| OK | Data is fresh and complete | N/A |
| STALE | Data is aging | All instruments (pre-market) |
| UNAVAILABLE | No data exists | Research tables |
| DEGRADED | Partial data issues | API health (pre-existing) |

## NO FABRICATED VALUES

All research data is:
- ✅ Collected from actual market data
- ✅ Empty when no data available (0 records)
- ✅ Marked as UNAVAILABLE/STALE/PENDING appropriately
- ❌ No fabricated AI calls
- ❌ No fabricated outcomes
- ❌ No fabricated option data
- ❌ No fabricated market data
- ❌ No fabricated research records
