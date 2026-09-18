# Phase 42A.4B — Live Data Diagnostics

**Date**: 2026-09-18
**Phase 41**: FROZEN

---

## Pre-Market Diagnostic (07:32 IST)

### Database State
| Metric | Value |
|--------|-------|
| DB size | 177.11 MB |
| Tables | 58 |
| paper_trades | 1,188 (all NIFTY) |
| research_tables | 0 records (expected) |
| price_5m | 17,400 rows (historical) |
| price_1m | 34,383 rows (historical + stale) |
| Latest NIFTY 5m | 2026-09-15 09:55:00 |
| Latest price_1m | 2026-09-17 15:31:00 |
| SQLite integrity | OK |

### API Health
| Endpoint | Status | Notes |
|----------|--------|-------|
| /api/health | 200 (DEGRADED) | Pre-existing stale data |
| /api/price/NIFTY | 200 | Stale (630m old) |
| /api/price/BANKNIFTY | 200 | Stale |
| /api/market | 200 | Degraded |
| /api/NIFTY | 200 | Stale |
| All research endpoints | 200 | 0 records |
| /api/options/state/NIFTY | 500 | Options unavailable (EOD only) |
| /api/market-evidence/NIFTY | 200 | OK |
| /api/trade-qualification | POST OK | Qualification engine |
| /api/market-outlook | 200 | Stale outlook |
| /api/strategy/NIFTY | 200 | OK |
| /api/risk/NIFTY | 200 | OK |
| /api/breadth | 200 | OK |

### Research Tables
| Table | Records | Status |
|-------|---------|--------|
| research_setup_identity | 0 | EXPECTED |
| research_reentry_log | 0 | EXPECTED |
| research_ai_call_log | 0 | EXPECTED |
| research_outcome_tracking | 0 | EXPECTED |
| research_data_health | 0 | EXPECTED |
| research_manifest | 0 | EXPECTED |
| market_snapshots_5m | 0 | EXPECTED |
| market_evidence_5m | 0 | EXPECTED |
| ai_outlooks_5m | 0 | EXPECTED |

### Root Cause of Frontend LOADING/UNAVAILABLE
1. **Primary**: data not fresh (market closed, pre-market) → STALE → frontend shows stale/pre-market
2. **Secondary**: generate_json.py has no cron → no JSON files (but frontend uses API, not JSON)
3. **Tertiary**: research tables empty → research sections show unavailable
4. **NOT a frontend bug**: Frontend correctly shows STALE/UNAVAILABLE for missing data
