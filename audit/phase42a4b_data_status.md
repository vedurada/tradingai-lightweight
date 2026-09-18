# Phase 42A.4B — Data Status

**Date**: 2026-09-18
**Phase 41**: FROZEN

---

## Canonical Data Status Model

### Market State
| Status | Meaning |
|--------|---------|
| PRE_MARKET | Before 09:15 IST |
| MARKET_OPEN | During market hours (09:15-15:30 IST) |
| MARKET_CLOSED | After 15:30 IST or weekend |

### Data Quality States
| Status | Meaning |
|--------|---------|
| LIVE | Fresh, current session data |
| FRESH | Recently updated (equivalent to LIVE) |
| STALE | Data exists but older than threshold |
| UNAVAILABLE | No data available |
| ERROR | Data retrieval failed |
| LOADING | Data is being fetched (frontend state) |

### Existing API Statuses (Reused)
- DATA_QUALITY_LIVE (api_server.py)
- DATA_QUALITY_STALE (api_server.py)
- DATA_QUALITY_UNAVAILABLE (api_server.py)
- DATA_QUALITY_PARTIAL (existing)

### Existing Frontend States (Reused)
- LIVE, UPDATED, STALE, UNAVAILABLE, ERROR (phase41.js, api.js)

## Current Status (07:32 IST)

| Component | Status | Notes |
|-----------|--------|-------|
| Market state | PRE_MARKET | Pre-market |
| NIFTY price | STALE | 630m old (last session) |
| BANKNIFTY price | STALE | 630m old (last session) |
| Research tables | UNAVAILABLE | 0 records (not yet triggered) |
| API | DEGRADED | Pre-existing stale data |
| Frontend | STALE | Pre-market data shown |
| Research collection | MARKET_CLOSED | Not in market hours |
