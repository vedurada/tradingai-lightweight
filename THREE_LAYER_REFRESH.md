# Three-Layer Refresh Architecture

## Overview

TradingAI.in refreshes data at three different layers, each with its own interval and purpose. This ensures users always see fast-moving market data while AI narrative stays stable unless the market materially changes.

## Layer 1: Market Data — ~5-15 seconds

**What**: Live prices, quotes, and tick data.

**Mechanism**:
- Background thread in `api_server.py:2045` (`_refresh_market_background`) sleeps 15s between refreshes
- `/api/market` cache TTL is 20 seconds (`_MARKET_TTL`)
- Live price blink on frontend via `live-blink.js`

**Data sources**: `price_1m`, `price_5m`, `price_15m` tables; NSE live feed

**Key property**: Always fresh or freshly-stale (never days-old)

## Layer 2: Market State — 1-5 minutes

**What**: Computed market state — regime, bias, confidence, indicators, strategies.

**Mechanism**:
- Computed on-demand from `price_1m` and `indicators` data
- `market_change.py` runs after each Layer 1 refresh, comparing current state vs stored snapshot
- Material changes (regime transition, >15% confidence swing, VIX >5pt, >1% price move) are flagged and trigger Layer 3
- Non-material changes are stored but don't trigger AI regeneration

**Data sources**: `market_regime`, `indicators`, `strategies`, `scenarios` tables

**Key property**: Changes gradually; notifications sent on material shifts only

## Layer 3: AI Narrative — Event-driven (on material change, max 120min fallback)

**What**: AI-generated outlook, strategies, verdicts, narratives.

**Mechanism**:
- `outlook.py:refresh_ai_outlook` checks `market_change.should_regenerate_ai()` before generating
- Regeneration triggered by:
  1. Material market change detected by Layer 2
  2. AI outlook older than 120 minutes (fallback)
- LLM is called only on regeneration; between events, cached AI outlook is used
- `generation_reason` field tracks why AI was regenerated (initial | material_change | max_age | manual)

**Data sources**: `ai_outlooks` table, `AIOutlookEngine`

**Key property**: AI narrative is stable between material market changes; always ≤120 minutes old

## Refresh Cycle Summary

```
Every 15s:  Layer 1 refresh (market data)
             ↓
             Check: material change?
             ↓ yes              ↓ no
Regenerate AI           Skip AI (use cache)
Layer 3 refresh         AI ≤120 min old?
(up to 120 min)         ↓ yes → Regenerate
                        ↓ no → Skip
```

## Per-Layer Freshness in API Responses

`/api/market` response includes:
```json
{
  "data_freshness": {
    "market_data_minutes_ago": 0,
    "market_state_minutes_ago": 2,
    "ai_outlook_minutes_ago": 15,
    "ai_outlook_stale": false
  }
}
```

## Model Layer Freeze

These files are FROZEN (never modified by the refresh architecture):
- `backend/regime.py` — RegimeEngine (read-only for state comparison)
- `backend/strategies.py` — StrategyEngine (read-only for display mapping)
- `backend/outlook.py` — OutlookEngine (AI explanation, not decision)
- `backend/scenarios.py` — ScenarioEngine
- `backend/options.py` — Options intelligence
- `backend/ai_outlook.py` — AI outlook generation
- `backend/backtest.py` — Backtesting
- `backend/indicators.js` — Technical indicators

LLM EXPLAINS, never DECIDES. UI DISPLAYS, never calculates authoritative signals.

## New Files

| File | Purpose |
|------|---------|
| `backend/market_change.py` | Material change detection engine; snapshot storage; AI regeneration decisions |
| `backend/db_schema.py` (added table) | `market_change_snapshots` table for state storage |

## New DB Table

| Table | Columns | Purpose |
|-------|---------|---------|
| `market_change_snapshots` | id, symbol, captured_at, state, material_change, changes | Stores regime/price/vix state at each Layer 1 refresh for comparison |
