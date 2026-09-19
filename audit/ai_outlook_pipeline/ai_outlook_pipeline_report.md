# AI Outlook Pipeline — Final Report

Date: 2026-09-18
Auditor: opencode
Scope: 36 sections across production environment, database, generators, APIs, frontend, security, governance, monitoring, retention

---

## Executive Summary

The AI Outlook pipeline has TWO generators: a **working twice-daily legacy generator** (39,148 rows) and a **completely broken 5-minute generator** (0 rows). The 5-minute pipeline fails at 4 distinct levels, all of which must be fixed for real-time AI outlooks to work.

## Key Findings

### P0 — CRITICAL (Blocking)

| # | Finding | Location | Impact |
|---|---------|----------|--------|
| P0-1 | **OutlookScheduler has no production trigger** | No cron, no service, no integration | 5-minute AI outlooks never generated |
| P0-2 | **ai_outlook_5m.py _call_llm() hardcodes NIFTY** | backend/ai_outlook_5m.py:159 | Even if scheduler ran, ALL symbols get NIFTY outlooks with empty state |
| P0-3 | **market_evidence_5m _record_evidence() never inserts** | backend/research_collector.py:308-318 | Evidence data never stored despite schema existing |
| P0-4 | **research_ai_call_log never populated** | research_collector.record_ai_call() never called | No AI call logging, no audit trail, no performance monitoring |

### P1 — HIGH (Data Quality)

| # | Finding | Location | Impact |
|---|---------|----------|--------|
| P1-1 | **market_snapshots_5m empty** | 0 rows (price_5m has 15,960 rows) | research_collector.collect() fails to create snapshots during market |
| P1-2 | **Legacy ai_outlooks lacks structured fields** | No evidence_json, watch_levels_json, etc. | Frontend can't show structured evidence/levels from legacy source |
| P1-3 | **Fallback always returns data_state: LIVE** | `_ai_outlook_from_legacy()` hardcodes `"data_state": "LIVE"` | Shows LIVE when market is CLOSED |
| P1-3 | **ai_outlooks uses INSERT OR REPLACE** | Overwrites latest outlook | Violates immutability requirement |

### P2 — MEDIUM (Completeness)

| # | Finding | Location | Impact |
|---|---------|----------|--------|
| P2-1 | **outlook_changes table missing** | DB schema has no such table | Change tracking between outlooks impossible |
| P2-2 | **ai_outcome_predictions empty** | 0 rows | No validation of AI prediction accuracy |
| P2-3 | **No early detection** | N/A | No predictive capability |
| P2-4 | **No unified evidence API** | N/A | No structured evidence breakdown endpoint |

### P3 — LOW (Monitoring/Governance)

| # | Finding | Location | Impact |
|---|---------|----------|--------|
| P3-1 | **No AI pipeline monitoring** | /api/health doesn't check ai_outlooks_5m | Silent failure possible |
| P3-2 | **No prompt/response persistence** | research_ai_call_log empty | Can't audit LLM quality |
| P3-3 | **Schema mismatch** | _store_outlook doesn't set data_snapshot_id, generated_success | Minor — defaults handle it |
| P3-4 | **No data retention policy** | All tables grow forever | Disk space concern at scale |

## Root Cause

The 5-minute AI Outlook pipeline was designed but never activated. The root cause chain:

1. **No trigger**: `outlook_scheduler.py` was written but never integrated into cron/services. `outlook.py` (twice-daily cron) has no dependency on it.
2. **Generator bug**: `ai_outlook_5m.py._call_llm()` was written with hardcoded "NIFTY" and empty `{}` state — likely a development-time shortcut never fixed.
3. **Evidence bug**: `research_collector._record_evidence()` checks existence but never INSERTS — likely an incomplete implementation.
4. **Monitoring gap**: No health check verifies ai_outlooks_5m has data during market hours.

## Current Workaround (Active)

The `/api/ai-outlook/<symbol>` endpoint falls back to `ai_outlooks` (legacy) when `ai_outlooks_5m` is empty (commit `cbb2641`). This means users still see AI outlooks, but they are:
- Template-generated (use_llm=False) not LLM-generated during most hours
- Missing structured evidence/levels
- Updated every minute (from data_fetcher_db.py) rather than every 5 minutes

## Required Fixes (Priority Order)

### Fix 1 — Activate OutlookScheduler (P0)

Add cron entry for outlook_scheduler during market hours:
```
*/5 9-15 * * 1-5 cd /opt/tradingai/backend && /usr/bin/python3 outlook_scheduler.py >> /opt/tradingai/logs/outlook_scheduler.log 2>&1
```

Or integrate `run_scheduler()` call into `data_fetcher_db.py` (which already runs every minute during market).

### Fix 2 — Fix _call_llm() Bug (P0)

In `backend/ai_outlook_5m.py`, change line 159-160 from:
```python
result = self.engine.generate("NIFTY", {}, use_llm=True)
```
To:
```python
result = self.engine.generate(symbol, market_state, use_llm=True)
```

### Fix 3 — Fix _record_evidence() Bug (P1)

In `backend/research_collector.py`, fix `_record_evidence()` to actually INSERT data into `market_evidence_5m` instead of returning True/False without writing.

### Fix 3b — Fix data_state Hardcode in Fallback (P1)

In `backend/api_server.py` `_ai_outlook_from_legacy()`, change `"data_state": "LIVE"` to derive from market status: `"data_state": "DELAYED" if market closed else "LIVE"`.

### Fix 4 — Add record_ai_call() Integration (P1)

Add `ResearchCollector.record_ai_call()` calls in `ai_outlook_5m.py._generate_ai_outlook()` or `outlook_scheduler.py._generate_ai_outlook()`.

### Fix 5 — Populate market_snapshots_5m (P1)

Investigate why `research_collector.collect()` produces 0 snapshots despite `price_5m` having 15,960 rows. Check if `_is_market_hours()` returns False or if `_record_snapshot()` fails.

## Verification Checklist

After fixes, verify on VM:
- [ ] `cd /opt/tradingai/backend && python3 outlook_scheduler.py` → non-zero rows in ai_outlooks_5m
- [ ] `sqlite3 ... "SELECT COUNT(*) FROM ai_outlooks_5m"` → > 0
- [ ] `curl /api/ai-outlook/NIFTY` → data_state: DELAYED (when market closed), LIVE (when open)
- [ ] `curl /api/ai-outlook/NIFTY` → current has evidence/levels when 5m pipeline working
- [ ] `curl /api/outlook/5m/timeline/NIFTY` → non-empty outlooks array
- [ ] `sqlite3 ... "SELECT COUNT(*) FROM research_ai_call_log"` → > 0 (after market hours)
- [ ] `sqlite3 ... "SELECT COUNT(*) FROM market_evidence_5m"` → > 0
- [ ] Run tests: `python3 -m pytest tests/ -q` → all passing
- [ ] Check no frozen files modified

## 18 Questions Answered

1. **What is the production state?** Legacy pipeline working (39,148 rows), 5-minute pipeline completely broken (0 rows across all 3 tables).
2. **Why is ai_outlooks_5m empty?** No scheduler trigger + generator bug + evidence bug + monitoring gap.
3. **Are AI outlooks available to users?** Yes, via fallback to legacy ai_outlooks table.
4. **Is the fallback real-time?** No — template-based (use_llm=False) updated every minute.
5. **What would fixing the pipeline require?** 4 fixes: activate scheduler, fix generator, fix evidence, add logging.
6. **Is data fresh?** Legacy outlooks ~5 hours old (within 12h TTL). 5m data unavailable.
7. **Is the AI outlook immutable?** No — INSERT OR REPLACE allows overwrites.
8. **Is evidence tracked?** No — ai_outlooks_5m and research_ai_call_log are empty.
9. **Can AI predictions be validated?** No — ai_outcome_predictions is empty.
10. **Is monitoring adequate?** No — no pipeline-specific health checks.
11. **Is security adequate?** Yes — CORS, rate limiting, API key protection all in place.
12. **Are frozen files protected?** Yes — pre-commit hook enforces.
13. **Is the database intact?** Yes — integrity OK, backup created.
14. **Are cross-page workflows working?** Mostly — 3 known issues from PHASE 29.
15. **Is data lineage tracked?** No — no audit trail for AI generation events.
16. **What's the resource impact of fixing?** Manageable — ~156 LLM calls/day during market, ~6MB RAM.
17. **What's the recovery procedure?** Restore from backup at /opt/tradingai/backups/.
18. **What's the priority for fixes?** P0: activate scheduler + fix generator. P1: fix evidence + logging + snapshots.
