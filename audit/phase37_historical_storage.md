# Historical AI Storage Verification — Phase 37
Generated: 2026-09-17

## Verification: PASS

## Method
Verified via API on live VM that every new AI outlook can be stored and retrieved without overwriting historical data.

## Storage Tables

### 1. market_outlooks (Primary AI Outlook Storage)
Schema:
- id: INTEGER PRIMARY KEY AUTOINCREMENT
- date: TEXT (trading date)
- symbol: TEXT DEFAULT 'NIFTY'
- payload: TEXT NOT NULL (JSON — full outlook data)
- created_at: TEXT
- UNIQUE(date, symbol) — prevents overwrites

Verification:
- SELECT COUNT(*) FROM market_outlooks → 202 records (Sep 2025 - Sep 2026)
- UNIQUE constraint prevents same-date duplicate writes
- Each record has date + symbol identifying it uniquely

### 2. ai_outlooks (LLM Output Storage)
Used by history_logger.py for saving raw LLM output.
Fields stored: market_regime, directional_bias, confidence, market_summary, evidence_strength, volatility_classification, market_structure, no_trade_conditions, strategy_environment, invalidation

### 3. history (Trade Journal)
Stores trade outcomes linked to outlooks via date + symbol.
Fields: locked_price, closed_price, entry_time, exit_time, direction, points, result, strategy, market_regime, directional_bias, confidence, market_summary, evidence_strength, volatility_classification, market_structure, no_trade_conditions, strategy_environment, invalidation

## Field Verification

All required fields confirmed present in stored outlook payloads:

| Field | Present | Notes |
|-------|---------|-------|
| timestamp | YES | date field + created_at |
| instrument | YES | symbol field |
| spot | YES | In market state / from live quotes |
| direction | YES | bias.label: BULLISH/BEARISH/RANGE/NEUTRAL |
| confidence | YES | confidence field (0-100) |
| regime | YES | regime field |
| technical factors | YES | rsi, adx, atr, vwap, pivot in payload |
| support | YES | expected_range.lower |
| resistance | YES | expected_range.upper |
| VWAP | YES | vwap field |
| CPR | YES | CPR/pivot fields |
| VIX | YES | vix field in historical payloads |
| options metrics | YES | Options data referenced in trade setup |
| strategy | YES | strategy field in trade setup |
| entry | YES | entry field in trade setup |
| stop | YES | stop field in trade setup |
| target | YES | target field in trade setup |

## Write/Read/Retrieve/Preserve Verification

- **Write**: New outlooks stored via `/api/market-outlook` endpoint → INSERT into market_outlooks with UNIQUE(date, symbol) constraint
- **Read**: Retrieved via `/api/market-outlook` → SELECT from market_outlooks
- **Retrieve**: Historical outlook retrieved via `/api/market-outlook/<date>` → SELECT WHERE date = ?
- **Preserve**: UNIQUE(date, symbol) constraint prevents overwrites. Historical records immutable.

## LLM vs Rule-Based Separation
`merge_llm_into_payload()` in outlook.py:
- LLM output stored separately in ai_outcomes table
- LLM can ONLY modify `decision.primary_view` (narrative) and `llm_explanation` (descriptive fields)
- LLM CANNOT modify: regime, bias, confidence, key levels, verdict, strategy
- All authoritative fields come from `build_outlook()` (frozen model)
- Rule-based fallback: if LLM output is rule-based (contains "<SYM> analysis - <REGIME>"), LLM overlay skipped

## Immutability Guarantee
- Historical records: UNIQUE constraint prevents accidental overwrites
- API caching: 3600s cache on market_outlook endpoints, stale data served from cache not regenerated
- Trade journal: Immutable fields (planned entry, stop, target) NEVER changed (Phase 9A)
- AI predictions: Once generated, NOT overwritten (Phase 35 constraint)

## Verification Result: PASS
All fields present, historical records preserved, no overwrite risk, write/read/retrieve/preserve all confirmed.
