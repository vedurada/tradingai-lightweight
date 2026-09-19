# Scheduler Execution Trace

Date: 2026-09-18

## Manual Dry-Run (Market Closed)

Executed on VM at 2026-09-18 16:56 IST (market closed):

```bash
cd /opt/tradingai/backend && SKIP_LLM=1 python3 -c "from outlook_scheduler import run_scheduler; import json; print(json.dumps(run_scheduler(dry_run=True), indent=2))"
```

Result:
```json
{
  "timestamp": "2026-09-18T16:56:13.903366+00:00",
  "symbols_processed": [
    {
      "symbol": "NIFTY",
      "candle_timestamp": null,
      "trigger_reason": "market_closed",
      "ai_generation_required": false,
      "ai_generation_result": "SKIPPED"
    },
    {
      "symbol": "BANKNIFTY",
      "candle_timestamp": null,
      "trigger_reason": "market_closed",
      "ai_generation_required": false,
      "ai_generation_result": "SKIPPED"
    },
    {
      "symbol": "SENSEX",
      "candle_timestamp": null,
      "trigger_reason": "market_closed",
      "ai_generation_required": false,
      "ai_generation_result": "SKIPPED"
    },
    {
      "symbol": "FINNIFTY",
      "candle_timestamp": null,
      "trigger_reason": "market_closed",
      "ai_generation_required": false,
      "ai_generation_result": "SKIPPED"
    }
  ],
  "total_snapshots": 0,
  "total_ai_generated": 0,
  "total_changes_detected": 0,
  "errors": []
}
```

**Analysis**: The scheduler correctly identifies market is closed and skips all symbols. The `_get_current_candle_timestamp()` returns None because current IST time (16:56) is not in CRANDLE_BOUNDARIES and market hours are 09:15-15:30 IST.

## Would Run If Market Were Open?

At a time like 10:00 IST (which IS in CRANDLE_BOUNDARIES):
1. `_get_current_candle_timestamp()` → returns "2026-09-18T10:00:00Z"
2. `_is_duplicate()` → checks `market_snapshots_5m` → 0 rows → NOT duplicate → proceeds
3. `create_snapshot()` from `market_snapshot.py` → attempts to create snapshot
4. `get_latest_snapshot()` → returns None if market_snapshots_5m is empty → triggers "insufficient_data"
5. If snapshot existed → `evaluate_change()` → outlook_change_detector works (uses market_regime, indicators, vix, price_1m — all populated)
6. `needs_ai_outlook()` → checks age/material change → likely returns needs_ai=False (existing ai_outlooks are fresh)
7. If needs_ai=True → `_generate_ai_outlook()` → rate check → `AIOutlookGenerator5m.generate()` → **BUG: hardcoded NIFTY**

## What Would Actually Happen If We Fixed the Trigger (Cron)

Even with a cron entry added, the pipeline would still fail because:
1. `market_snapshots_5m` is empty → `create_snapshot()` may not work → insufficient_data
2. Even if snapshot created → `_generate_ai_outlook()` → `_call_llm()` hardcoded NIFTY
3. AI calls would all generate for NIFTY with empty state for all symbols

## Check: Does price_5m Have Data?

This determines whether market_snapshots_5m can ever be populated via research_collector.

```sql
SELECT COUNT(*) FROM price_5m; -- NEEDS CHECK
```

If price_5m is also empty, then market_snapshots_5m can never be populated through research_collector, and the entire 5-minute data foundation is missing.

## Check: monitor.py run_research_collection()

Called at line 140 of monitor.py (inside main loop). monitor.py runs every 5 minutes during market hours (cron: */5 9-15 * * 1-5). It calls `run_research_collection()` which:
1. Creates ResearchCollector(DB_PATH)
2. Calls rc.collect()
3. Logs result

So research_collector IS running every 5 minutes. But:
- collect() tries to read from price_5m (may be empty → 0 snapshots)
- _record_evidence() has a bug → 0 evidence
- record_ai_call() is never called

## Trigger Mechanism Analysis

| Mechanism | Exists? | Active? |
|-----------|---------|---------|
| Cron job for outlook_scheduler | NO | NO |
| Systemd timer for scheduler | NO | NO |
| Script calling scheduler | NO | NO |
| API endpoint (dry_run) | YES | Diagnostic only |
| Integration in outlook.py | NO | NO |
| Integration in data_fetcher_db.py | NO | NO |
| Integration in monitor.py | NO | NO |

**Conclusion**: The OutlookScheduler has ZERO production triggers. It is purely a diagnostic/unused component.
