# Product Architecture Feedback — Scoping

Based on user's 9 confirmed themes (4 items missing — to be added later).

## Current Refresh Architecture (as-is)

| Layer | Current Interval | Mechanism |
|-------|-----------------|-----------|
| Market prices | ~15s | Background thread in `api_server.py:2045` (`_refresh_market_background`) |
| Market data (API cache) | 20s TTL | `/api/market` cache in `api_server.py:1116` |
| Cron data fetch | 1 minute | `data_fetcher_db.py` via crontab |
| AI outlook | 2x/day (09:30/19:00) | `outlook.py:871` `refresh_ai_outlook` via cron |
| Static pages | On demand | `generate_json.py` on cron/schedule |

## Proposed Three-Layer Refresh Architecture

### Layer 1 — Market Data: ~5-15s (already exists)
- Background thread refreshes every 15s (already implemented)
- `/api/market` 20s TTL cache → reduce to 10-15s during market hours
- **No breaking changes**
- Files: `backend/api_server.py:2045-2049`, `backend/api_server.py:1116`

### Layer 2 — Market State (regime, indicators, strategies): ~1-5min
- Currently computed on-demand from `price_1m` data (no explicit interval)
- Add explicit 1-5min refresh cycle for computed state
- Add change detection: compare current vs previous state
- **New module**: `backend/market_change.py` (material change detector)
- **Modified**: `backend/regime.py`, `backend/strategies.py` (add state comparison hooks)
- Files to create: `backend/market_change.py`
- Files to modify: `backend/api_server.py` (add state refresh endpoint), `backend/regime.py` (snapshot comparison)

### Layer 3 — AI Narrative: only on material change (event-driven)
- Currently: twice daily via cron (09:30/19:00)
- Proposed: regenerate AI outlook ONLY when `market_change.py` detects material change
- Keep fallback: if no AI outlook in last 2 hours, generate regardless
- **Modified**: `backend/outlook.py:871` — add `should_regenerate_ai()` check
- **New field**: `ai_outlook.generation_reason` (manual | material_change | timeout_fallback)
- **New field**: `ai_outlast.last_change_timestamp` — when last material change occurred

## Scoping by Item

### Items 1-3: Refresh Architecture (Foundation)

#### Item 1: Event-driven AI refresh (only on material change)
- **Current**: AI outlook regenerates on fixed cron (09:30/19:00)
- **Target**: Regenerate only when market_change engine detects material shift
- **Mechanism**: 
  1. `market_change.py` runs after each Layer 2 refresh (every 1-5min)
  2. Compares current regime/bias/confidence vs previous snapshot
  3. If material change: trigger AI outlook regeneration
  4. If no change: skip AI regeneration (use existing)
- **Fallback**: If AI outlook is >2 hours old, regenerate regardless
- **Files**: 
  - NEW: `backend/market_change.py` (change detection engine)
  - MODIFY: `backend/outlook.py:871` (add should_regenerate check)
  - MODIFY: `backend/api_server.py` (trigger change check after data refresh)
- **Frozen**: No — this is a new feature, not a model change
- **Tests**: New tests for change detection scenarios
- **Est**: 2-3 days

#### Item 2: Market change engine
- **Current**: No explicit material change detection
- **Target**: Dedicated engine that detects when market has materially changed
- **Definition of "material"**: 
  - Regime transition (BULLISH → BEARISH, etc.)
  - Bias reversal
  - Confidence >15% swing
  - VIX >5pt move in 5min
  - NIFTY >1% move in 5min
- **Mechanism**: 
  1. Store snapshot of regime/bias/confidence every refresh
  2. Compare against previous snapshot
  3. If any threshold crossed → material change
- **Files**:
  - NEW: `backend/market_change.py` (material change engine)
  - MODIFY: `backend/api_server.py` (call after data refresh)
  - DB: new table `market_snapshots` (symbol, timestamp, regime, bias, confidence, vix, nifty_price)
- **Frozen**: No — new engine, but no model changes
- **Tests**: Test threshold detection for each material change type
- **Est**: 2-3 days (can overlap with Item 1)

#### Item 3: Three-layer refresh architecture
- **Current**: Two effective layers (market data ~15s, AI ~12hr cron)
- **Target**: Three explicit layers with different refresh intervals
- **Layers**:
  1. Market Data: 5-15s (already exists, document explicitly)
  2. Market State: 1-5min (regime, indicators, strategies — computed from data)
  3. AI Narrative: event-driven (on material change, max 30min fallback)
- **Mechanism**:
  1. Document the three layers in `KNOWLEDGE.md` and architecture docs
  2. Implement Layer 2 explicit refresh (1-5min)
  3. Implement Layer 3 event-driven (Items 1-2)
  4. Add `/api/data_status` fields showing last refresh time per layer
- **Files**:
  - NEW: `backend/market_change.py` (Layer 2+3)
  - MODIFY: `backend/api_server.py` (add layer timestamps to responses)
  - MODIFY: `KNOWLEDGE.md` (document architecture)
  - MODIFY: `backend/data_status` (track per-layer freshness)
- **Frozen**: No — structural change, not model change
- **Tests**: Verify each layer refreshes at its specified interval
- **Est**: 3-4 days (includes Items 1-2)

### Items 4-9: UX Display Features

#### Item 4: "outdated outlook" warning
- **Current**: No explicit staleness warning on dashboard
- **Target**: Show warning when AI outlook hasn't regenerated and market data has changed since
- **Mechanism**:
  1. Track `ai_outlook.generated_at` vs `market_data.last_changed`
  2. If market changed >15min ago and AI outlook not regenerated → show "Outlook may be outdated"
  3. Frontend: amber banner on dashboard
- **Files**:
  - MODIFY: `backend/outlook.py` (add generated_at timestamp if missing)
  - MODIFY: `backend/api_server.py` (expose ai_outlook_age_minutes)
  - MODIFY: `assets/js/ai-outlook.js` (display banner)
  - MODIFY: `index.html` (banner container)
- **Frozen**: No — presentation only
- **Tests**: Verify banner appears at correct thresholds
- **Est**: 1-2 days

#### Item 5: Regime→options strategy mapping
- **Current**: StrategyEngine selects strategies based on regime (already exists in `backend/strategies.py`)
- **Target**: Explicit, visible mapping displayed to user
- **Mechanism**:
  1. Verify existing regime→strategy mapping is correct
  2. Display mapping in dashboard: "Current regime: BULLISH → Recommended: Bull Call Spread"
  3. Show alternative strategies per regime
- **Files**:
  - VERIFY: `backend/strategies.py` (existing mapping)
  - MODIFY: `assets/js/ai-outlook.js` (display regime→strategy mapping)
  - MODIFY: `index.html` (if needed for banner display)
- **Frozen**: Possibly — might just need display changes
- **Tests**: Verify all 4 regimes have valid strategy mappings
- **Est**: 1-2 days

#### Item 6: "NO CLEAR EDGE" / "WAIT" states
- **Current**: Verdicts are TRADE/WAIT/AVOID; regime values are BULLISH/BEARISH/SIDEWAYS/HIGH_VOLATILITY/UNKNOWN
- **Target**: Add "NO CLEAR EDGE" as a distinct state when signals are mixed/weak
- **Mechanism**:
  1. Define criteria for "NO CLEAR EDGE" (e.g., confidence <40 AND bias = NEUTRAL)
  2. Add as a possible regime or verdict state
  3. Display distinctly in dashboard
- **Files**:
  - VERIFY: `backend/outlook.py` (where verdicts are set)
  - MODIFY: `backend/outlook.py` (add NO CLEAR EDGE criteria)
  - MODIFY: `assets/js/ai-outlook.js` (display new state)
- **Frozen**: Unclear — might touch model logic if it affects verdict computation
- **Tests**: Add test cases for NO CLEAR EDGE scenarios
- **Est**: 2-3 days (depending on model impact)

#### Item 7: "OUTLOOK CHANGED" visible notifications
- **Current**: No change notification when AI outlook updates
- **Target**: Show notification banner when outlook changes (regime shift, bias change, verdict change)
- **Mechanism**:
  1. Track previous AI outlook state (regime, bias, verdict)
  2. On refresh, compare current vs previous
  3. If different → show "OUTLOOK CHANGED — NIFTY regime shifted from BULLISH to BEARISH"
  4. Frontend: green notification banner with change details
- **Files**:
  - NEW: `backend/market_change.py` (also detects outlook-relevant changes)
  - MODIFY: `backend/api_server.py` (expose change details)
  - MODIFY: `assets/js/ai-outlook.js` (display notification)
  - MODIFY: `index.html` (notification container)
- **Frozen**: No — presentation only
- **Tests**: Verify notification appears when state changes
- **Est**: 1-2 days (depends on Item 2 for change detection)

#### Item 8: Last-analysis timestamp display
- **Current**: `last-updated-bar` shows data refresh time, not AI analysis time
- **Target**: Show when AI outlook was last generated/updated
- **Mechanism**:
  1. Track `ai_outlook.generated_at` (when LLM ran or rule-based fallback)
  2. Display separately from data refresh time
  3. Format: "AI Analysis: 14 Sep 2026, 09:30 IST"
- **Files**:
  - VERIFY: `backend/outlook.py` (does it track generated_at?)
  - MODIFY: `backend/api_server.py` (expose ai_analysis_time)
  - MODIFY: `assets/js/ai-outlook.js` (display AI analysis time)
  - MODIFY: `index.html` (dedicated span for AI analysis time)
- **Frozen**: No — presentation only
- **Tests**: Verify timestamp updates on AI regeneration
- **Est**: 1 day

#### Item 9: Change-detail display
- **Current**: No delta display between AI analyses
- **Target**: Show what specifically changed (which indicators moved, which regime shifted, which key level broke)
- **Mechanism**:
  1. Store previous AI outlook state (regime, bias, key levels, confidence, verdict)
  2. Compare current vs previous
  3. Generate human-readable change summary: "VIX rose 2.3 → 3.1, regime shifted BEARISH, NIFTY broke support 23,100"
  4. Display in dashboard as expandable section
- **Files**:
  - MODIFY: `backend/market_change.py` (generate change summary)
  - MODIFY: `backend/api_server.py` (expose change details)
  - MODIFY: `assets/js/ai-outlook.js` (display change details)
  - MODIFY: `index.html` (change details container)
- **Frozen**: No — presentation + change detection
- **Tests**: Verify change details are accurate for each change type
- **Est**: 2-3 days (depends on Items 1-2)

## Implementation Order

### Phase A — Foundation (Items 1-3, 9)
Must complete before Phase B because Phase B features depend on change detection.

1. Build `market_change.py` (Items 1+2)
2. Implement three-layer refresh (Item 3, builds on 1+2)
3. Implement change-detail display (Item 9, uses market_change.py output)

**Est**: 5-7 days total

### Phase B — UX Display (Items 4-8)
Depends on Phase A for change detection data.

4. Outdated outlook warning (Item 4)
5. Regime→options mapping display (Item 5)
6. NO CLEAR EDGE / WAIT states (Item 6 — verify model impact first)
7. OUTLOOK CHANGED notifications (Item 7)
8. Last-analysis timestamp (Item 8)

**Est**: 4-6 days total

### Total Estimated: 9-13 days

## Frozen Model Files (untouched)
All model/analytical layers remain frozen:
- `backend/regime.py` — RegimeEngine (no logic changes, only snapshot reading)
- `backend/strategies.py` — StrategyEngine (no logic changes, only display mapping)
- `backend/outlook.py` — OutlookEngine (AI explanation, not decision)
- `backend/scenarios.py` — ScenarioEngine
- `backend/options.py` — Options intelligence
- `backend/ai_outlook.py` — AI outlook generation
- `backend/backtest.py` — Backtesting
- `backend/indicators.js` — Technical indicators

LLM EXPLAINS, never DECIDES. UI DISPLAYS, never calculates authoritative signals.

## New Files to Create
1. `backend/market_change.py` — Material change detection engine
2. `backend/market_snapshot.py` — Snapshot storage and comparison (if separate from change engine)

## New DB Tables (if needed)
1. `market_snapshots` — timestamp, symbol, regime, bias, confidence, vix, nifty_price, nifty_change_pct
2. `ai_outlook_history` — timestamp, symbol, regime, bias, verdict, confidence, key_levels, change_summary (for tracking changes over time)

## Open Questions (4 missing items)
1. [ ] Missing item 10: ???
2. [ ] Missing item 11: ???
3. [ ] Missing item 12: ???
4. [ ] Missing item 13: ???
