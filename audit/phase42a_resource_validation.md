# Phase 42A — Resource Validation

**Date**: 2026-09-17
**Phase 41**: FROZEN

---

## VM Resources

| Resource | Before | After | Safe? |
|----------|--------|-------|-------|
| RAM | 956MB total, 285MB free | No significant change expected | YES |
| CPU | 2 CPUs | Negligible increase | YES |
| Disk | 45GB, 30GB free | +1-5MB/day | YES |
| DB Size | 174MB | +small growth | YES |

## Resource Impact Analysis

### CPU
- Hashing (SHA256): negligible
- String operations: negligible
- DB inserts: minimal (SQLite, local)
- Impact: <0.1% CPU during market hours

### Memory
- Connection pool: shared with existing code
- Research data: held in SQLite only (no in-memory caching)
- Impact: <5MB peak additional memory

### Disk
- Current DB: 174MB
- Daily growth estimate: ~1-5MB (at current trade frequency)
- Monthly growth: ~30-150MB
- Yearly growth: ~365-1825MB
- 50GB disk: safe for >27 years at current rate

## Database Growth Projections

### Per 5-Minute Candle (During Market Hours)

| Table | Rows per Day | Rows per Month | Rows per Year |
|-------|-------------|----------------|---------------|
| research_setup_identity | ~78 (15.6 trades/hour x 5) | ~2340 | ~28470 |
| research_reentry_log | ~65 | ~1950 | ~23725 |
| research_ai_call_log | ~5-15 | ~150-450 | ~1825-5475 |
| research_outcome_tracking | ~78 | ~2340 | ~28470 |
| research_data_health | ~1440 (every minute check) | ~43200 | ~525600 |
| research_manifest | 0-1 | ~0-3 | ~0-36 |

### Market Data Tables (Existing)

| Table | Rows per Day | Rows per Month |
|-------|-------------|----------------|
| market_snapshots_5m | ~1560 | ~46800 |
| market_evidence_5m | ~1560 | ~46800 |
| ai_outlooks_5m | ~5-15 | ~150-450 |
| paper_trades | ~15-50 | ~450-1500 |

### Total DB Growth Estimate

| Period | Growth | Total DB Size |
|--------|--------|---------------|
| Day 1 | ~3MB | 177MB |
| Month 1 | ~100MB | 274MB |
| Year 1 | ~1.2GB | 2.4GB |
| Year 5 | ~6GB | 8.4GB |
| Year 10 | ~12GB | 14.4GB |

50GB disk is safe for >10 years at current rate.

## VM Resource Verification

| Check | Result |
|-------|--------|
| RAM usage acceptable | YES (no new daemon, shared connection pool) |
| CPU usage acceptable | YES (negligible) |
| Disk space sufficient | YES (1.2GB/year, 30GB free) |
| No new processes | YES (uses existing gunicorn workers) |
| No new services | YES (scheduled collection via existing cron) |
