# Phase 42A.4B — Research Collector Integration

**Date**: 2026-09-18
**Phase 41**: FROZEN

---

## Implementation

Added `collect()` method to ResearchCollector class in `backend/research_collector.py`.

### Architecture

```text
Completed 5m candle (from price_5m)
        ↓
collect() method [READ-ONLY observation]
        ↓
For each completed candle:
  1. Record market snapshot → market_snapshots_5m
  2. Record evidence → market_evidence_5m
  3. Record setup identity → research_setup_identity
  4. Record outcome → research_outcome_tracking
  5. Record reentry → research_reentry_log
  6. Record AI call → research_ai_call_log
  7. Record data health → research_data_health
        ↓
Update manifest → research_manifest
```

### Key Design Decisions

- **READ-ONLY**: collect() does NOT modify production pipeline
- **Observation-only**: reads existing production data, records observations
- **Idempotent**: uses INSERT OR IGNORE for snapshots
- **Market-hours guard**: skips execution outside 09:15-15:30 IST
- **No duplicate collection**: skips already-collected candles
- **No AI forcing**: does NOT trigger AI calls for testing

### Integration Point

Added `run_research_collection()` to monitor.py, called at end of `check_health()` when market is open.

```python
def run_research_collection():
    sys.path.insert(0, "/opt/tradingai/backend")
    from research_collector import ResearchCollector
    rc = ResearchCollector(DB_PATH)
    result = rc.collect()
    log(f"Research collection: {json.dumps(result)}")
    return result
```

### monitor.py Integration

```python
if _is_market_hours():
    run_research_collection()
```

### ResearchCollector.collect() Method Details

**Returns**: dict with timestamps, status, counts for snapshots/evidence/ai_calls/setup_identities/reentries/outcomes/data_health/manifest_updated

**Status values**:
- MARKET_CLOSED: Skip (pre-market or after close)
- COMPLETED: Success with counts
- ERROR: Failure with error message

## Verification

- collect() returns MARKET_CLOSED when not in market hours ✅
- collect() returns dict with required fields ✅
- collect() is idempotent on empty DB ✅
- Does not modify production tables when in MARKET_CLOSED state ✅
- monitor.py has research collection integration ✅
- monitor.py has market hours check ✅
