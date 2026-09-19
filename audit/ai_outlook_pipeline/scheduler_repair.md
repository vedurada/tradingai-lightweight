# Scheduler Repair

Date: 2026-09-19
Classification: REPLAY/VALIDATION

## Original Defect

`outlook_scheduler.py` had NO production trigger. No cron entry, no systemd timer, no integration in any production script. The scheduler was designed but never activated.

## Repair

### Integration Point

Added scheduler trigger to `backend/monitor.py`, which already runs every 5 minutes during market hours via cron (`*/5 9-15 * * 1-5`).

### Implementation

```python
# backend/monitor.py
def run_scheduler():
    try:
        sys.path.insert(0, "/opt/tradingai/backend")
        from outlook_scheduler import run_scheduler as _run
        result = _run(dry_run=False)
        log(f"Outlook scheduler: {json.dumps(result)}")
        return result
    except Exception as e:
        log(f"Outlook scheduler failed: {e}")
        return {"status": "ERROR", "error": str(e)}
```

Integrated into `check_health()`:
```python
if _is_market_hours():
    run_research_collection()
    run_scheduler()
```

### Existing Scheduler Flow (unchanged)

`OutlookScheduler.run()`:
1. For each primary symbol (NIFTY, BANKNIFTY):
2. Get current candle timestamp (only at CRANDLE_BOUNDARIES)
3. Check duplicate (checks market_snapshots_5m)
4. Create snapshot (reads from price_5m via create_snapshot fix)
5. Evaluate material change (outlook_change_detector)
6. Check if AI needed (needs_ai_outlook)
7. If needed: generate AI outlook → store to ai_outlooks_5m
8. Log result with status (GENERATE/SKIP_NO_MATERIAL_CHANGE/ALREADY_PROCESSED/ERROR)

### Failure Isolation

- Each symbol is processed in try/except
- LLM failures are caught by `_generate_ai_outlook()` and logged
- Scheduler failure doesn't affect research collection
- Monitor health check continues regardless

## Supporting Fixes

### market_snapshot.py
- `create_snapshot()` now reads OHLCV from price_5m when not provided
- This enables the scheduler to create snapshots from raw data

### ai_outlook_5m.py
- `_prepare_ai_input()` maps snapshot fields to AI engine format
- This enables the generator to receive proper market data

## Verification

- Scheduler function exists in monitor.py ✓
- Called during market hours ✓
- Not called outside market hours ✓
- Failure isolated ✓
- Idempotent (duplicate candles → ALREADY_PROCESSED) ✓
