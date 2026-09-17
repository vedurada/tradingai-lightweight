# Phase 39 — Architecture Document

## 1. System Architecture

### 5-Minute Pipeline

```text
5-MINUTE CANDLE CLOSE (09:20, 09:25, ... 15:30 IST)
        ↓
OUTLOOK_SCHEDULER.run() — idempotent, checks for duplicate candles
        ↓
MARKET_SNAPSHOT.create_snapshot() — stores market_snapshots_5m row
        ↓
OUTLOOK_CHANGE_DETECTOR.evaluate() — compares current vs previous state
        ↓
MATERIAL CHANGE?
      /       \
    NO         YES
    |           |
    |    AI_OUTLOOK_GENERATOR.generate() — structured JSON via LLM
    |           ↓
    |    STORE in ai_outlooks_5m (immutable, unique outlook_id)
    |           ↓
    |    OUTCOME_PREDICTIONS.record_outcome() — future evaluation
    |
    ↓
CURRENT STATE updated
```

### Key Design Decisions

1. **AI is NOT called every 5 minutes** — Only on material change, max age, or first outlook
2. **Every candle gets a snapshot** — Even if no AI outlook is generated
3. **Every outlook is immutable** — INSERT OR REPLACE with UNIQUE(outlook_id)
4. **Idempotency** — Database constraint on (symbol, candle_timestamp) for snapshots
5. **AI call protection** — MIN_AI_INTERVAL_SECONDS=120, MAX_AI_OUTLOOKS_PER_SESSION=200
6. **Deterministic states** — Market state engine calculates regime/trend/vwap/volatility without AI
7. **Outcome evaluation** — Future price measured at 5/15/30/60 min horizons, marked PENDING until data available

## 2. Modules

### backend/market_snapshot.py
- `create_snapshot()` — Creates 5-minute candle snapshot with all indicators
- `get_latest_snapshot()` — Returns most recent snapshot for a symbol
- `get_snapshot_history()` — Returns historical snapshots
- Calculates: trend_state, volatility_state, price_vs_vwap from indicators

### backend/market_state_engine.py
- `MarketStateEngine` — Deterministic market state from indicators
- `evaluate()` — Returns regime, trend, price_vs_vwap, volatility, trade_state
- All thresholds configurable via `self.thresholds`

### backend/outlook_change_detector.py
- `evaluate()` — Full change evaluation (current state + change detection + AI trigger decision)
- `needs_ai_outlook()` — Checks if AI regeneration is needed
- Reuses `market_change.py` for material change detection logic

### backend/ai_outlook_5m.py
- `AIOutlookGenerator5m` — AI outlook generation with structured JSON
- `generate()` — Main entry point, returns validated outlook dict
- `_validate()` — Enforces allowed bias (BULLISH/BEARISH/RANGE/MIXED), trade_state (TRADE/WAIT/NO_TRADE), confidence 0-100
- `_call_llm()` — Calls AIOutlookEngine from ai_outlook.py

### backend/outcome_engine.py
- `record_outcome()` — Records pending prediction with reference price
- `evaluate_outcome()` — Evaluates future price movement against prediction
- `_calculate_future_return()` — Measures 5/15/30/60 min price change
- `get_pending_evaluations()` — Returns PENDING outcomes for evaluation
- `get_aggregate_stats()` — Returns accuracy stats with sample size protection (min 10)

### backend/outlook_scheduler.py
- `OutlookScheduler.run()` — Main scheduling entry point
- `_process_symbol()` — Full processing pipeline per symbol per candle
- `_generate_ai_outlook()` — AI call with rate limiting and protection
- `_store_outlook()` — Idempotent storage with INSERT OR REPLACE
- `is_market_open()` — Checks if market session is active

## 3. Database Schema

### New Tables

**ai_outlooks_5m** — Every AI outlook generated
- outlook_id (UNIQUE) — Immutable ID: OUTLOOK-{symbol}-{timestamp}
- instrument, candle_timestamp, generated_at
- model, model_version, prompt_version
- bias, confidence, market_regime
- summary, evidence_json, watch_levels_json, etc.
- trade_state, expected_horizon_minutes
- material_changes_json, data_state

**market_snapshots_5m** — Every 5-minute candle snapshot
- symbol, candle_timestamp (UNIQUE)
- OHLC, volume, vwap, all indicators
- price_vs_vwap, trend_state, volatility_state, regime
- Options data: pcr, call_oi, put_oi
- data_state, data_timestamp

**ai_outcome_predictions** — Every prediction evaluation
- outlook_id, symbol, entry_price, reference_price
- horizon_minutes (5/15/30/60)
- future_return_pct, correct, mfe_pct, mae_pct
- bias, status (PENDING/EVALUATED)

## 4. APIs

| Endpoint | Method | Description |
|----------|--------|-------------|
| /api/ai-outlook/{symbol} | GET | Current outlook + previous + change + timeline |
| /api/ai-outlook/timeline/{symbol} | GET | Historical outlook timeline (paginated) |
| /api/ai-outlook/scheduler | GET | Scheduler status + dry run + stats |
| /api/outlook/5m/latest/{symbol} | GET | Latest evaluation result |
| /api/outlook/5m/timeline/{symbol} | GET | Outlook timeline |
| /api/outlook/5m/snapshot/{symbol} | GET | Latest market snapshot |
| /api/outlook/5m/changes/{symbol} | GET | Material change evaluation |
| /api/outlook/5m/outcome | POST | Record/evaluate outcomes |

## 5. AI Generation Triggers

AI outlook is generated ONLY when:
1. No current outlook exists (first generation)
2. Material market change detected (regime, bias, Vwap, level, trend, volatility, options)
3. Maximum outlook age exceeded (30 minutes default)
4. Minimum interval respected (120 seconds between AI calls)
5. Session limit not reached (200 per session max)

## 6. Data State Model

- LIVE — Data current, outlook fresh
- DELAYED — Market closed, data delayed
- STALE — Outlook exceeds max age
- UNAVAILABLE — No data/outlook available
- NO_OUTLOOK — No AI outlook generated yet
