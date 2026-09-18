# Phase 42A.5 Research Collection Validation

## Research Collector Integration
- Component: ResearchCollector (in monitor.py)
- Method: collect()
- Trigger: Called by run_research_collection() in monitor.py
- Schedule: monitor.py runs via cron every 5 min during 9-15 IST

## Research Tables

| Table | Purpose | Status |
|---|---|---|
| market_snapshots_5m | 5m market snapshots | EMPTY (pre-market) |
| market_evidence_5m | 5m market evidence | EMPTY (pre-market) |
| research_setup_identity | Setup identity records | EMPTY (pre-market) |
| research_reentry_log | Re-entry information | EMPTY (pre-market) |
| research_ai_call_log | AI invocation records | EMPTY (pre-market) |
| research_outcome_tracking | Outcome tracking | EMPTY (pre-market) |
| research_manifest | Research manifest | EMPTY (pre-market) |

## Research Collection Trigger
```
Every completed 5m candle (09:20, 09:25, 09:30...):
   ↓
monitor.py runs (every 5 min)
   ↓
_is_market_hours() check
   ↓
run_research_collection()
   ↓
ResearchCollector.collect()
   ↓
Failure-isolated (doesn't affect market data)
Idempotent (can run multiple times safely)
Lightweight (minimal DB writes)
```

## Research Collection Tests
- collect() returns empty when not market hours ✅
- collect() is idempotent on empty DB ✅
- collect() returns dict with required fields ✅
- collect() does NOT modify production tables ✅
- monitor.py has research collection integration ✅
- monitor.py has market hours check ✅

## Research Data Safety
- No AI calculations in research data ✅
- Deterministic only ✅
- Failure isolated from primary data ✅
- Minimum sample size: 10 trades for personal intelligence ✅
