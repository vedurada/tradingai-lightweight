# Database Inventory — AI Outlook Pipeline

Date: 2026-09-18
Database: /opt/tradingai/database/tradingai.db (264MB, integrity OK)
Backup: /opt/tradingai/backups/tradingai_pre_ai_outlook_pipeline_20260918_222245.db

## AI Outlook Related Tables

### 1. ai_outlooks (LEGACY — twice-daily, LLM + rule-based)
| Metric | Value |
|--------|-------|
| Total rows | 39,148 |
| Symbols | 41 (all NIFTY, BANKNIFTY, FINNIFTY, SENSEX + ~37 stocks) |
| Per index | ~1,295 rows (NIFTY: 1295, BANKNIFTY: 1295, FINNIFTY: 1295, SENSEX: 1295) |
| Per stock | ~87-260 rows |
| Date range | 2026-09-15T12:37:23Z to 2026-09-18T16:40:59Z |
| Source | outlook.py (9AM/7PM LLM) + data_fetcher_db.py (every minute rule-based) |
| Schema | (id, symbol, timestamp, outlook TEXT JSON, data_quality) |
| Schema file | backend/db_schema.py (ai_outlooks table) |

### 2. ai_outlooks_5m (INTRADAY — 5-minute, BROKEN)
| Metric | Value |
|--------|-------|
| Total rows | **0** ← THE CORE ISSUE |
| All instruments | 0 |
| Date range | N/A — no data |
| Source | outlook_scheduler.py → OutlookScheduler → AIOutlookGenerator5m → _store_outlook() |
| Schema | (id, outlook_id, instrument, candle_timestamp, generated_at, model, model_version, prompt_version, data_snapshot_id, bias, confidence, market_regime, summary, evidence_json, watch_levels_json, confirmation_json, invalidation_json, risk_json, trade_state, expected_horizon_minutes, material_changes_json, data_state, created_at, generated_success) |
| UNIQUE constraint | outlook_id |
| Schema file | backend/db_schema.py line 553 |
| Missing columns | data_snapshot_id (always NULL), generated_success (always 0) |
| Insert path | outlook_scheduler.py:_store_outlook() lines 188-221 |
| Insert SQL columns | 21 (excludes data_snapshot_id, generated_success) |

### 3. market_outlooks (DAILY — framework payload)
| Metric | Value |
|--------|-------|
| Total rows | 206 |
| NIFTY | 67 (2026-06-18 to 2026-09-18) |
| BANKNIFTY | 67 (2026-06-18 to 2026-09-18) |
| SENSEX | 67 (2026-06-18 to 2026-09-18) |
| FINNIFTY | 5 (2026-09-14 to 2026-09-18 — started recently) |
| Source | outlook.py main() → refresh_ai_outlook() + merge_llm_into_payload() |
| Schema | (id, date, symbol, payload TEXT JSON, created_at, UNIQUE(date, symbol)) |
| Schema file | backend/db_schema.py |

### 4. market_snapshots_5m (5-MINUTE — BROKEN)
| Metric | Value |
|--------|-------|
| Total rows | **0** |
| All symbols | 0 |
| Source | research_collector.py:_record_snapshot() → populated from price_5m table |
| Schema | (id, symbol, candle_timestamp, snapshot_time, open, high, low, close, volume, vwap, ema9, ema21, ema20, ema200, rsi, rsi_14, macd, macd_signal, adx, atr, cpr_upper, cpr_lower, pivot, support, resistance, prev_day_high, prev_day_low, price_vs_vwap, trend_state, volatility_state, regime, vix, pcr, call_oi, put_oi, expected_move, max_pain, data_state, data_timestamp, created_at, setup_id) |
| UNIQUE | (symbol, candle_timestamp) |
| Schema file | backend/db_schema.py line 602 |
| Insert SQL | research_collector.py:297 → INSERT OR REPLACE INTO market_snapshots_5m |
| Data source | price_5m table (SELECT * FROM price_5m WHERE symbol=? AND timestamp=?) |

### 5. market_evidence_5m (5-MINUTE — BROKEN)
| Metric | Value |
|--------|-------|
| Total rows | **0** |
| All instruments | 0 |
| Source | research_collector.py:_record_evidence() → **BUG: never inserts** |
| Schema | (id, evidence_id, instrument, candle_timestamp, generated_at, snapshot_id, trend_json, momentum_json, structure_json, volatility_json, options_json, confirmation_json, overall_signal, overall_strength, conflict_json, data_quality, data_state, engine_version, created_at, setup_id) |
| UNIQUE | (evidence_id), (instrument, candle_timestamp) |
| Schema file | backend/db_schema.py line 647 |
| Bug | _record_evidence() checks if row exists and returns True/False but NEVER inserts |

### 6. outlook_changes (MISSING TABLE)
| Metric | Value |
|--------|-------|
| Exists | **NO — table does not exist** |
| Source | N/A |
| Note | Section 17 references this table; it was never created |

### 7. ai_outcome_predictions (EXISTS — EMPTY)
| Metric | Value |
|--------|-------|
| Total rows | 0 |
| Schema | (id, outlook_id, symbol, entry_price, reference_price, horizon_minutes, future_return_pct, correct, mfe_pct, mae_pct, bias, recorded_at, evaluated_at, status, created_at) |
| Schema file | backend/db_schema.py |
| Purpose | Track whether AI outlook predictions were correct |

### 8. research_ai_call_log (EXISTS — EMPTY)
| Metric | Value |
|--------|-------|
| Total rows | 0 |
| Schema | (id, call_timestamp, instrument, candle_timestamp, trigger, model, provider, prompt_version, success, latency_ms, token_usage, error, fallback_used, outlook_id, data_version, created_at, UNIQUE(call_timestamp, instrument)) |
| Index | idx_ai_call_sym_ts (instrument, call_timestamp DESC) |
| Schema file | backend/db_schema.py line 791 |
| Purpose | Log every AI/LLM call for outlook generation |
| Expected caller | ResearchCollector.record_ai_call() (called by monitor.py via run_research_collection()) |
| Actual calls logged | 0 — monitor.py calls collect() but _record_ai_from_outlooks() reads existing ai_outlooks; record_ai_call() is never called in production pipeline |

### 9. research_setup_identity, research_reentry_log (EXISTS — EMPTY)
| Table | Rows | Notes |
|-------|------|-------|
| research_setup_identity | 0 | Needs paper_trades data |
| research_reentry_log | 0 | Depends on setup_identities |

### 10. research_outcome_tracking, research_data_health (EXIST — POPULATED)
| Table | Rows | Notes |
|-------|------|-------|
| research_outcome_tracking | 61,672 | Working — populated via daily_page.py |
| research_data_health | 219 | Working — populated via research_collector |

## Table Relationships (Intended 5-Minute Pipeline)

```
price_5m (raw 5m candles)
  → research_collector.collect() every 5 min (via monitor.py)
    → market_snapshots_5m (snapshot data)  [BROKEN: 0 rows — price_5m may be empty or collect can't find candles]
    → market_evidence_5m (evidence analysis)  [BROKEN: _record_evidence never inserts]
    → outlook_scheduler.run() [NEVER TRIGGERED]
      → AIOutlookGenerator5m.generate()
        → _call_llm()  [BUG: hardcoded NIFTY, empty state]
        → _validate()
      → _store_outlook() → ai_outlooks_5m  [NEVER REACHED]
      → research_ai_call_log  [NEVER REACHED]

Separate path:
outlook.py (9AM/7PM via cron)
  → refresh_ai_outlook()
    → AIOutlookEngine.generate(use_llm=True) [LLM]
    → ai_outlooks  [WORKING: 39,148 rows]
```

## Database Integrity Checks
- PRAGMA integrity_check: OK
- All tables present (no missing tables in core schema)
- Missing: outlook_changes table (referenced but not created)

## Key Finding
The 5-minute AI outlook pipeline has zero data in ALL three intermediate tables (market_snapshots_5m, market_evidence_5m, ai_outlooks_5m) because:
1. `outlook_scheduler.py` is never triggered by cron/service
2. `research_collector._record_evidence()` has a bug — never inserts into market_evidence_5m
3. `market_snapshots_5m` is empty even though `research_collector.collect()` runs every 5 min via monitor.py
