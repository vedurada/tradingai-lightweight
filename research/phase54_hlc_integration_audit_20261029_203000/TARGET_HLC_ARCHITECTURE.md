# Phase 5.4 — Target HLC Architecture

## 1. Target Architecture

### 1.1 HLC-Only Decision Ownership

In the target architecture, the three-candle HLC strategy is responsible for generating new entry decisions. The following components are reused and adapted:

| Component | Current State | Target State | Adapter Needed |
|-----------|--------------|--------------|----------------|
| Signal detection | scalp_engine._scan_signals() | Same | None — reuse directly |
| Signal qualification | paper_scalp_live.py:run_once() | Same | None — reuse directly |
| Entry-price resolution | _get_entry_price_from_provider() | Same | None — reuse directly |
| Entry-time guard | _entry_time_guard() | Same | None — reuse directly |
| Daily trade limit | NOT enforced (scalp path) | Enforce 1 per instrument/day | NEW — add daily_trade_locks integration |
| Concurrent position limit | has_open_position() (Mode C) | Same | None — reuse directly |
| Risk validation | risk/engine.py:RiskEngine | Same | None — reuse directly |
| Paper trade persistence | paper_trade/engine.py:create_paper_trade() | Same | None — reuse directly |
| Exit evaluation | paper_trade/engine.py:monitor() | Same | None — reuse directly |
| Telegram alerts | tg_alerts.py:do_watch() | Same | None — reuse directly |
| Dashboard/API | app/api/app.py | HLC overlay → HLC primary | Adapter — change display to primary |

### 1.2 Separation of Concerns

1. **HLC signal detection** — scalp_engine._scan_signals() (unchanged)
2. **Signal qualification** — freshness, staleness, entry-time guard (unchanged)
3. **Entry-price availability** — _get_entry_price_from_provider() (unchanged)
4. **Daily/concurrent position limits** — has_open_position() + new daily_trade_locks integration
5. **Risk/position sizing** — risk/engine.py:RiskEngine (unchanged)
6. **Paper-trade lifecycle** — paper_trade/engine.py (unchanged)
7. **Database persistence** — paper_trades table (unchanged)
8. **Telegram notifications** — tg_alerts.py (unchanged)
9. **Dashboard/API** — app/api/app.py (adapt display-only to primary)

### 1.3 Components Reused vs Adapted

| Component | Reuse? | Adapter? | Notes |
|-----------|--------|----------|-------|
| scalp_engine.py | YES | NO | Canonical HLC implementation |
| paper_scalp_live.py | YES | YES | Add daily trade limit enforcement |
| paper_trade/engine.py | YES | NO | Shared persistence + monitor |
| tg_alerts.py | YES | NO | Already polls HLC strategy |
| risk/engine.py | YES | NO | Risk validation |
| app/api/app.py | YES | YES | Change HLC from overlay to primary |
| app/live/engine.py | YES | YES | Change default from CPR to HLC |
| app/paper_trade/performance.py | YES | NO | Performance aggregation |

### 1.4 Components NOT Reused

| Component | Reason |
|-----------|--------|
| cpr_trigger_engine.py | CPR-specific, retained for rollback |
| cpr_strategy_engine.py | CPR-specific, retained for rollback |
| qualification.py | CPR qualification (uses StrategyEngine + RiskEngine) |
| strategies/engine.py | Credit spread selection (CPR path) |
| scenarios/engine.py | Scenario generation (CPR path) |

### 1.5 Single Authoritative HLC Signal Path

In the target architecture, there is ONE authoritative HLC signal path:
1. `scalp_engine._scan_signals()` → signal detection
2. `paper_scalp_live.py:run_once()` → signal qualification + trade creation
3. `PaperTradeEngine.create_paper_trade()` → persistence
4. `tg_alerts.py:do_watch()` → notification (reads from DB, never creates trades)

The live engine (`app/live/engine.py`) currently uses CPR for decisions. In HLC-only mode, it would use `_hlc_book_signal()` instead of `_cpr_book_signal()`.

### 1.6 Idempotency Key

The existing idempotency mechanism uses:
- `scalp_link(inst, trade_date, direction, signal_time)` → `"scalp|{inst}|{trade_date}|{direction}|{signal_time}"`
- `scalp_trade_id(link_key)` → `'PT-' + sha1(link_key)[:10].upper()`
- `trade_id` is the PRIMARY KEY in `paper_trades`

This prevents duplicate trades for the same signal across polling cycles and process restarts.

### 1.7 Daily Trade Limit (Proposed)

**Proposed conservative default:** 1 trade per instrument per day (matching Mode A from HLC frequency research).

**Effect on Phase 5.1 simulation:** Phase 5.1 used Mode C (one open position per instrument). With a daily limit of 1, the trade count would be further reduced from 63 to ~6 (one per instrument per day).

**Recommendation:** Start with Mode C (current behavior) and add daily limit as a separate, explicitly configurable parameter. Do not silently change the default.

### 1.8 Concurrent Position Limit

Mode C: one open position per instrument (NIFTY and BANKNIFTY tracked independently). Enforced via `has_open_position()` which checks for ACTIVE/OPEN SCALP_HLC trades.

### 1.9 Stale Signal Handling

- `_entry_time_guard()` rejects signals where `now > entry_time + 5min`
- `is_stale()` rejects signals where `entry_time` is >20 minutes old
- `validate_candle()` rejects stale candles (>15 min old)

### 1.10 Missing/Delayed Candle Behavior

- If candles are missing: `validate_candle()` returns `ok=False` → entries skipped
- If candles are delayed: `is_stale()` returns True → signal skipped
- If provider fails: explicit UNAVAILABLE/API_ERROR/RATE_LIMITED state → no trade

### 1.11 Persistence Failure Behavior

- `create_paper_trade()` catches `sqlite3.IntegrityError` and returns existing trade_id
- `try_create_trade()` catches exceptions and marks signal as failed
- No Telegram alert is sent until trade is confirmed in DB

### 1.12 Telegram Notification Behavior

- `tg_alerts.py:do_watch()` polls `/api/strategy/scalp` for signals
- Checks DB for existing trade before alerting
- Sends `sendMessage` only if trade exists
- Dedup via `fired` key in `tg_state.json`
- Retries on delivery failure (key not added to `fired`)

### 1.13 Dashboard/API Presentation

- `/api/decision` overlays HLC levels (market_bias, entry, stop, target) on CPR decision
- In HLC-only mode: HLC would be the primary decision, not an overlay
- `/api/strategy/scalp` serves HLC signal state (unchanged)
- `/api/paper/scalp` serves HLC paper trades (unchanged)
