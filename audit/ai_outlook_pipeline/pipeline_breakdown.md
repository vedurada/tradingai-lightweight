# Pipeline Breakdown — Why ai_outlooks_5m Has Zero Rows

Date: 2026-09-18

## The Complete Data Chain

The 5-minute AI outlook pipeline is designed to produce real-time AI outlooks every 5 minutes during market hours. The chain is:

```
Step 1: Completed 5m candle (price_5m)
  └─→ Step 2: research_collector.collect() (via monitor.py every 5 min)
       └─→ Step 2a: market_snapshots_5m (INSERT from price_5m data)
       └─→ Step 2b: market_evidence_5m (INSERT — BUG: never inserts)
       └─→ Step 2c: research_ai_call_log (record_ai_call — never called)

Step 3: OutlookScheduler.run() (NEVER TRIGGERED)
  └─→ Step 3a: Check candle timestamp (CRANDLE_BOUNDARIES)
  └─→ Step 3b: Check duplicate (market_snapshots_5m — empty)
  └─→ Step 3c: create_snapshot() (market_snapshot.py)
  └─→ Step 3d: evaluate_change() (outlook_change_detector)
  └─→ Step 3e: needs_ai_outlook() (outlook_change_detector)
  └─→ Step 3f: AIOutlookGenerator5m.generate() [BUG: hardcoded NIFTY]
  └─→ Step 3g: _store_outlook() → ai_outlooks_5m (NEVER REACHED)
```

## Finding 1: outlook_scheduler.py Has No Production Trigger

**Evidence**:
- No cron entry for `outlook_scheduler.py` or `run_scheduler()`
- No systemd timer for the 5-minute AI outlook pipeline
- No script in /opt/tradingai/ops/ references it
- Only reference is `api_ai_outlook_scheduler()` in api_server.py which calls `run_scheduler(dry_run=True)` (diagnostic only)
- `outlook.py` (twice-daily cron) has NO integration with OutlookScheduler

**Verification**:
```bash
# Dry-run scheduler on VM (market closed at time of test):
cd /opt/tradingai/backend && SKIP_LLM=1 python3 -c "from outlook_scheduler import run_scheduler; import json; print(json.dumps(run_scheduler(dry_run=True), indent=2))"
# Result: All 4 symbols skipped — trigger_reason: "market_closed"
```

**Impact**: Even if market were open, the scheduler would run when manually triggered, but it has no production trigger.

## Finding 2: ai_outlook_5m.py._call_llm() Has a Critical Bug

**File**: backend/ai_outlook_5m.py, line 159

```python
def _call_llm(self, prompt: str) -> dict:
    try:
        result = self.engine.generate("NIFTY", {}, use_llm=True)  # BUG
        return result
```

**Bugs**:
1. **Hardcoded symbol**: `"NIFTY"` instead of `self.symbol` or passed `symbol` parameter
2. **Empty market state**: `{}` instead of `market_state` parameter (which contains regime, RSI, price, VIX, etc.)
3. **No use of prompt parameter**: The built prompt (which includes symbol-specific state and evidence) is never passed to the engine

**Impact**: Even if the scheduler ran, all 4 symbols would generate NIFTY-specific outlooks using completely empty market data, producing meaningless results.

## Finding 3: market_snapshots_5m Is Empty

**Evidence**: 0 rows in production database.

**Why**: `research_collector.collect()` runs every 5 min via `monitor.py` (line 81-83) and calls `_record_snapshot()` which does:
```python
row = conn.execute("SELECT * FROM price_5m WHERE symbol=? AND timestamp=?", (symbol, ts)).fetchone()
```
If `price_5m` has no data for the current candle, no snapshot is created. Alternatively, the `_is_market_hours()` check might fail.

**Verification needed**: Check if `price_5m` table has data.

## Finding 4: market_evidence_5m Has a Bug

**File**: backend/research_collector.py, lines 308-318

```python
def _record_evidence(self, conn, result, symbol, ts) -> bool:
    try:
        row = conn.execute(
            "SELECT * FROM market_evidence_5m WHERE symbol=? AND timestamp=?",
            (symbol, ts),
        ).fetchone()
        if not row:
            return False  # ← Returns False but NEVER INSERTS
        return True  # evidence already exists
    except Exception:
        return False
```

**Bug**: The function checks if evidence exists, returns True/False, but NEVER executes an INSERT. The function is called by `collect()` and its return value increments `result["evidence"]`, but no data ever gets written.

## Finding 5: research_ai_call_log Is Never Populated

**Expected**: Every AI/LLM call for outlook generation should be logged.
**Actual**: 0 rows in production.
**Why**: `ResearchCollector.record_ai_call()` (line 120-122 of research_collector.py) exists and has schema, but is never called in the production pipeline. The 5-minute generator doesn't call it, and the twice-daily generator doesn't call it.

## Finding 6: outlook_changes Table Missing

**Expected**: A table to track changes between consecutive AI outlooks.
**Actual**: No `outlook_changes` table in the database.
**Why**: The schema was never created, or the table was dropped.

## Fix Priority

| Priority | Issue | Fix |
|----------|-------|-----|
| P0 | outlook_scheduler never triggered | Add cron entry or integrate with data_fetcher_db.py |
| P0 | ai_outlook_5m._call_llm() hardcoded NIFTY | Change to use `symbol` and `market_state` parameters |
| P1 | market_snapshots_5m empty | Verify price_5m data exists; fix collect() if needed |
| P1 | market_evidence_5m never inserts | Fix _record_evidence() to actually INSERT |
| P2 | research_ai_call_log empty | Add record_ai_call() call in generator or collector |
| P2 | outlook_changes table missing | Create table via db_schema.py |
| P3 | Schema column mismatch | Add data_snapshot_id, generated_success to _store_outlook() |
