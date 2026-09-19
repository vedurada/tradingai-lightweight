# AI Outlook Generator Inventory

Date: 2026-09-18

## Generators Overview

Three generators exist in the codebase, forming a layered architecture:

### 1. AIOutlookEngine (Twice-Daily, Legacy)

| Field | Value |
|-------|-------|
| File | backend/ai_outlook.py |
| Class | AIOutlookEngine |
| Trigger | outlook.py via cron (09:30/19:00 IST, weekdays) |
| Also called by | data_fetcher_db.py (every minute, use_llm=False) |
| LLM usage | Twice-daily: use_llm=True (LLM). Per-minute: use_llm=False (rule-based template) |
| Output table | ai_outlooks |
| Row count | 39,148 |
| Prompt | AI_OUTLOOK_PROMPT (hardcoded in file) — structured data analysis prompt |
| Model | Groq/OpenRouter/Gemini/etc (provider-preference list, FREE_PROVIDERS = ["gemini", "groq", "deepseek", "openrouter", "ollama"]) |
| Key method | generate(symbol, data, use_llm=True) |
| Caching | In-memory: `self._cache[f"ai:{symbol}"]` |
| normalize | _normalize_llm_outlook(symbol, outlook, data) — maps LLM output to internal schema |
| rule-based | _rule_based_outlook(data) — template from data dict (used when use_llm=False) |

**Key design**: LLM is used twice daily for outlook.py. The per-minute poller (data_fetcher_db.py) reuses stored outlook or generates rule-based template. Never calls LLM in the poller path.

### 2. AIOutlookGenerator5m (5-Minute, Broken)

| Field | Value |
|-------|-------|
| File | backend/ai_outlook_5m.py |
| Class | AIOutlookGenerator5m |
| Trigger | outlook_scheduler.py → OutlookScheduler._generate_ai_outlook() |
| Cron? | **NO — OutlookScheduler is never triggered** |
| LLM usage | Always use_llm=True via self.engine.generate() (AIOutlookEngine) |
| Output table | ai_outlooks_5m |
| Row count | **0** |
| Prompt | Same AI_OUTLOOK_PROMPT as parent engine |
| Key method | generate(symbol, market_state, material_changes, evidence) |
| **BUG** | `_call_llm()` line 159: `self.engine.generate("NIFTY", {}, use_llm=True)` — hardcoded "NIFTY" instead of `symbol`, empty `{}` instead of `market_state` |
| Fallback | _fallback_outlook() — returns MIXED/0/NEUTRAL with "AI outlook temporarily unavailable" |
| Validation | _validate() — clamps bias/confidence/regime to allowed sets |
| Data state | LIVE/DELAYED/UNAVAILABLE based on evidence and market_state |
| Does NOT call | research_ai_call_log.record_ai_call() — no AI call logging |

**Critical bug detail**:
```python
def _call_llm(self, prompt: str) -> dict:
    try:
        result = self.engine.generate("NIFTY", {}, use_llm=True)  # ← BUG: hardcoded NIFTY, empty state
        return result
    except Exception as e:
        logger.error(f"LLM call failed: {e}")
        return self._fallback_outlook()
```
This means even if the scheduler ran, ALL symbols would generate NIFTY outlooks using empty market state data.

### 3. OutlookScheduler (5-Minute Orchestrator, Never Triggered)

| Field | Value |
|-------|-------|
| File | backend/outlook_scheduler.py |
| Class | OutlookScheduler |
| Trigger | **NONE — no cron, no service, no API production call** |
| API exposure | /api/outlook/5m/scheduler (dry_run=True only — diagnostic) |
| Primary symbols | NIFTY, BANKNIFTY |
| Support symbols | SENSEX, FINNIFTY |
| Candle boundaries | 28 predefined IST times (09:20 to 15:30) |
| Max AI per session | 200 |
| Min AI interval | 120 seconds |
| Max outlook age | 30 minutes |
| Age warn threshold | 15 minutes |
| Key method | run(dry_run=False) → processes all 4 symbols |
| _process_symbol() | Gets candle timestamp → checks duplicate → creates snapshot → evaluates change → checks if AI needed → generates AI if needed |
| _get_current_candle_timestamp() | Returns current candle only if time matches CRANDLE_BOUNDARIES |
| _is_duplicate() | Checks market_snapshots_5m (which is empty) |

**Scheduler flow (if it ran)**:
```
_for each symbol in [NIFTY, BANKNIFTY, SENSEX, FINNIFTY]:_
  candle_timestamp = _get_current_candle_timestamp()
  if no candle → skip (market_closed)
  if duplicate → skip (duplicate_candle)
  create_snapshot(symbol, candle_timestamp) → market_snapshots_5m
  evaluate_change(symbol) → outlook_change_detector
  needs_ai_outlook(symbol) → check age/material change
  if needs_ai and not dry_run:
    _generate_ai_outlook(symbol, snapshot, changes)
      → check rate limits
      → AIOutlookGenerator5m.generate() [BUG: hardcoded NIFTY]
      → _store_outlook() → ai_outlooks_5m
```

## Callers/Importers of Each Generator

### AIOutlookEngine callers
- `backend/ai_outlook.py` — self (generate method)
- `backend/ai_outlook_5m.py` — via AIOutlookGenerator5m.__init__()
- `backend/data_fetcher_db.py` — via _latest_ai_outlook() + AIOutlookEngine().generate(use_llm=False)
- `backend/outlook.py` — via refresh_ai_outlook()
- Tests: test_ai_outlook_backtest.py

### AIOutlookGenerator5m callers
- `backend/outlook_scheduler.py` — via _generate_ai_outlook() (NEVER CALLED)
- No other callers in production code

### OutlookScheduler callers
- `backend/outlook_scheduler.py` — run_scheduler() (NEVER CALLED)
- `backend/api_server.py` — api_ai_outlook_scheduler() (dry_run=True only, diagnostic endpoint at /api/outlook/5m/scheduler)

## Summary Table

| Generator | Status | Rows Produced | LLM Used | Trigger |
|-----------|--------|--------------|----------|---------|
| AIOutlookEngine (use_llm=True) | Working | 39,148 in ai_outlooks | Yes (2x/day) | outlook.py cron |
| AIOutlookEngine (use_llm=False) | Working | Part of 39,148 | No | data_fetcher_db.py |
| AIOutlookGenerator5m | **Broken** (hardcoded NIFTY) | 0 | Yes (never runs) | Never triggered |
| OutlookScheduler | **Never triggered** | 0 | N/A | No cron/service |
