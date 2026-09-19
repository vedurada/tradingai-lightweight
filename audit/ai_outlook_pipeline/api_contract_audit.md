# API Source/Contract Audit

Date: 2026-09-18

## All AI Outlook Related API Endpoints

### 1. /api/ai-outlook/<symbol> (PRIMARY — frontend consumer)

**File**: api_server.py line 3747
**Function**: api_ai_outlook(symbol)
**Called by**: static/js/nifty.js, static/js/banknifty.js, static/js/finnifty.js, static/js/sensex.js via `/api/<symbol>`

**Request**: GET /api/ai-outlook/NIFTY
**Response**: success, data.{instrument, current, previous, change, timeline, data_state, market_status, current_candle}

**Current behavior (verified)**: Returns data via fallback to ai_outlooks (legacy) since ai_outlooks_5m is empty.
- `current.data_state`: "DELAYED" (market closed)
- `current.age_minutes`: ~14 (from legacy outlook)
- `current.age_status`: "FRESH"
- `data_state`: "DELAYED"

**Bug**: When ai_outlooks_5m is empty, current is None initially, then falls back to `_ai_outlook_from_legacy()`. Legacy data uses different schema — fields like `summary` become `market_summary`, `market_regime` becomes `market_regime` (mapped), but `evidence_json`, `watch_levels_json`, etc. are NOT populated from legacy.

### 2. /api/ai-outlook/timeline/<symbol>

**File**: api_server.py line 3868
**Function**: api_ai_outlook_timeline(symbol)
**Called by**: Frontend timeline display

**Behavior**: Uses same `_ai_outlook_from_legacy()` fallback. Returns timeline from ai_outlooks table.

### 3. /api/outlook/5m/latest/<symbol>

**File**: api_server.py line 3587
**Function**: api_outlook_5m_latest(symbol)
**Called by**: Frontend (static/js/ai-outlook.js? — need to verify)

**Behavior (verified)**: Calls `evaluate(symbol)` + `needs_ai_outlook(symbol)`. Works correctly. Returns material_change info, current_state from market_regime/indicators/vix/price_1m.
**Note**: This endpoint does NOT return ai_outlooks_5m data — it returns change detection results.

### 4. /api/outlook/5m/timeline/<symbol>

**File**: api_server.py line 3605
**Function**: api_outlook_5m_timeline(symbol)
**Behavior**: Reads from ai_outlooks_5m → returns empty (0 rows). Pagination works but data is empty.

### 5. /api/outlook/5m/snapshot/<symbol>

**File**: api_server.py line 3647
**Function**: api_outlook_5m_snapshot(symbol)
**Behavior**: Reads market_snapshots_5m → returns snapshot or NO_DATA.
**Issue**: market_snapshots_5m is empty → always returns NO_DATA.

### 6. /api/outlook/5m/changes/<symbol>

**File**: api_server.py line 3667
**Function**: api_outlook_5m_changes(symbol)
**Behavior**: Calls evaluate() from outlook_change_detector → works (reads from market_regime, indicators, vix, price_1m).

### 7. /api/outlook/5m/scheduler

**File**: api_server.py line 3937
**Function**: api_ai_outlook_scheduler()
**Behavior**: Calls run_scheduler(dry_run=True) — DIAGNOSTIC ONLY. Never runs for real.

### 8. /api/market-outlook

**File**: api_server.py line 1627
**Function**: market_outlook_latest()
**Behavior**: Reads from market_outlooks table → WORKING (206 rows). Uses outlook.py data, not 5m pipeline.

### 9. /api/market-outlook/<date>

**File**: api_server.py line 1657
**Function**: market_outlook_by_date(date)
**Behavior**: Same as above, by date.

### 10. /api/<symbol> (index pages)

**File**: api_server.py (dynamic route)
**Behavior**: Returns per-symbol data including ai_outlook from ai_outlooks table (via _latest_ai_outlook + AIOutlookEngine).

## API Contract Mismatches

### Frontend Expectation vs API Reality

| Page | Endpoint | Expects | Gets |
|------|----------|---------|------|
| today/index.html | /api/ai-outlook/NIFTY | Full outlook with evidence, levels | Fallback legacy outlook (no evidence/levels) |
| indices/nifty.html | /api/NIFTY | ai_outlook data | Template-based outlook (use_llm=False) |
| static/js/ai-outlook.js | /api/market-outlook?symbol=X | {outlook: {...}} wrapper | {outlook: {...}} — correct |
| tools/journal.html | /api/journal | Trade data | Trade data — correct |

### Data Completeness Issues

| Field | Legacy (ai_outlooks) | 5m (ai_outlooks_5m) | Frontend Needs |
|-------|---------------------|---------------------|----------------|
| bias | Yes (directional_bias) | Yes (bias) | Yes |
| confidence | Yes | Yes | Yes |
| regime | Yes (market_regime) | Yes (market_regime) | Yes |
| summary | market_summary | summary | Yes |
| evidence | Not populated | evidence_json | Yes |
| watch_levels | Not populated | watch_levels_json | Yes |
| confirmation | Not populated | confirmation_json | Yes |
| invalidation | Not populated | invalidation_json | Yes |
| risk | Not populated | risk_json | Yes |
| trade_state | Not populated | trade_state | Yes |
| material_changes | Not populated | material_changes_json | Yes |

**Legacy table is missing all structured fields** — it only has the flat narrative from AIOutlookEngine template output.

## Data State Bug

**File**: `backend/api_server.py` — `_ai_outlook_from_legacy()` function

When `ai_outlooks_5m` is empty and the fallback to `ai_outlooks` is triggered, the constructed `current` dict hardcodes `"data_state": "LIVE"`. This is incorrect when the market is closed — verified live: market reports `"session": "CLOSED"` but `data_state` returns `"LIVE"`.

**Impact**: Frontend shows LIVE indicator when market is closed.
**Fix**: Derive `data_state` from market status after fallback, not hardcode `"LIVE"`.

## Rate Limiting
All outlook endpoints are rate limited (30/minute except market-outlook which is cached 3600s).
