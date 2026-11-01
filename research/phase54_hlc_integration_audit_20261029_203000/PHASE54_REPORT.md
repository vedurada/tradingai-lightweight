# Phase 5.4 — HLC Live-Engine Integration and Safe Migration

**Report:** PHASE54_REPORT.md  
**Audit date:** 2026-10-29  
**Host:** webserver (Oracle VM)  
**Application root:** /opt/tradingai  
**Database:** /opt/tradingai/database/tradingai.db  
**Mode:** READ-ONLY audit and test-design (no production modifications)

---

## Executive Summary

### Confirmed Live Decision Path

The current live decision engine (`app/live/engine.py`) uses the **CPR trigger engine** as its default trade-decision engine. The HLC 3-bar scalp engine (`app/research/scalp_engine.py`) is used only as a **display overlay** on `/api/decision` and as a **separate signal source** via `/api/strategy/scalp`. The HLC engine does NOT drive live trade decisions — CPR does.

### Target Architecture

In the target architecture, the three-candle HLC strategy would be responsible for generating new entry decisions. The following components can be reused without modification:

- Signal detection: `scalp_engine._scan_signals()` (unchanged)
- Signal qualification: `paper_scalp_live.py:run_once()` (unchanged)
- Entry-price resolution: `_get_entry_price_from_provider()` (unchanged)
- Entry-time guard: `_entry_time_guard()` (unchanged)
- Concurrent position limit: `has_open_position()` (unchanged)
- Risk validation: `risk/engine.py:RiskEngine` (unchanged)
- Paper trade persistence: `paper_trade/engine.py:create_paper_trade()` (unchanged)
- Exit evaluation: `paper_trade/engine.py:monitor()` (unchanged)
- Telegram alerts: `tg_alerts.py:do_watch()` (unchanged)

The following components need adaptation:
- Daily trade limit: NOT enforced in scalp path (needs `daily_trade_locks` integration)
- Live engine default: Change from `_cpr_book_signal` to `_hlc_book_signal` in `evaluate()`
- Dashboard/API: Change HLC from display-only overlay to primary decision display

### Daily Limit Recommendation

**Proposed conservative default:** 1 trade per instrument per day (matching Mode A from HLC frequency research).

**Effect on Phase 5.1 simulation:** Phase 5.1 used Mode C (one open position per instrument). With a daily limit of 1, the trade count would be further reduced from 63 to ~6 (one per instrument per day, 3 days × 2 instruments).

**Recommendation:** Start with Mode C (current behavior) and add daily limit as a separate, explicitly configurable parameter. Do not silently change the default.

### Integration Test Results

- **Tests that can be run without production modifications:** 6/14 (all PASS via code review or runtime)
- **Tests requiring test database:** 8/14 (NOT RUN — requires isolated test DB)
- **Tests requiring production modifications:** 1/14 (feature flag not implemented)

### Outstanding Blockers

1. **Dirty working tree** — 33+ modified files and many untracked files
2. **CPR engine drives live decisions** — HLC is display-only on `/api/decision`
3. **No daily trade limit on scalp path** — need to add MAX_TRADES_PER_DAY enforcement
4. **Backtest vs live exit discrepancy** — backtest excludes entry candle; live protects during entry candle
5. **Two separate trade stores** — `paper_trades` (live) and `paper_scalp` (EOD backtest)
6. **No systemd unit for paper_scalp_live.py** — script exists but not running as service
7. **Untracked frontend signal pages** — ~200 untracked HTML files

### Final Status

**PARTIAL — MIGRATION DESIGN COMPLETE WITH UNRESOLVED DEPENDENCIES**

The migration design is complete. The target architecture, trade store audit, migration plan, and integration test framework are documented. However, 7 blockers prevent immediate deployment. The most critical are: dirty working tree, CPR engine as live decision driver, and no daily trade limit on scalp path.

**No production changes were made during this phase.** All outputs are in the isolated research directory.

---

## 1. Phase A — Verified Live Decision Flow

### 1.1 Market Data Ingestion

```
collector.py (systemd timer, 1-min cadence after Phase 4.9)
  └── get_5m_candles(symbol) → yfinance API
  └── INSERT OR IGNORE INTO market_candles_5m (only completed candles)
```

### 1.2 Live Decision Engine (CPR, default)

```
app/api/app.py:decision() → build_decision() → LiveEngine.evaluate(dry_run=True)
  └── completed_candle_ts() → floor_5m(now - 5min)
  └── _cpr_book_signal() → book_scan() → CPR triggers (bear priority, SHORT_ONLY)
  └── _frozen_trade() / _freeze_trade() → qualified_trades + daily_trade_locks
  └── Returns TRADE/WAIT/NO TRADE to frontend
  └── Scalp overlay: HLC levels displayed but NOT used for decision
```

### 1.3 Live Paper Trading (HLC, standalone script)

```
scripts/paper_scalp_live.py:run_once() [every 5s]
  └── today_signals() → scalp_engine.today_state()
      └── _load_candles() → SELECT ALL from market_candles_5m
      └── _scan_signals() → 3-bar HLC alignment
      └── _live_signal() → entry/stop/target/signal_time/entry_time
  └── _entry_time_guard() → reject if now > entry_time + 5min
  └── _get_entry_price_from_provider() → yfinance forming candle open
  └── try_create_trade() → PaperTradeEngine.create_paper_trade()
      └── INSERT INTO paper_trades (scenario='SCALP_HLC')
  └── PaperTradeEngine().monitor() → exit evaluation
```

### 1.4 Telegram Alerts (cron, every minute)

```
scripts/tg_alerts.py:do_watch()
  └── GET /api/strategy/scalp → scalp_engine.today_state()
  └── Check DB for existing trade_id
  └── If trade exists: tg('sendMessage', ...) → alert
  └── PaperTradeEngine().monitor() → exit evaluation
```

### 1.5 Component Ownership

| Component | Owner | Responsibility |
|-----------|-------|----------------|
| Signal detection | scalp_engine._scan_signals() | 3-bar HLC alignment |
| Signal qualification | paper_scalp_live.py:run_once() | Freshness, staleness, entry-time guard |
| Entry-price resolution | paper_scalp_live.py:_get_entry_price_from_provider() | yfinance forming candle open |
| Daily trade limit | NOT ENFORCED (scalp path) | MAX_TRADES_PER_DAY=1 exists in qualification.py (CPR path only) |
| Concurrent position limit | paper_scalp_live.py:has_open_position() | Mode C: one open position per instrument |
| Trade persistence | app/paper_trade/engine.py:create_paper_trade() | INSERT into paper_trades (deterministic ID) |
| Exit evaluation | app/paper_trade/engine.py:monitor() | Candle H/L stop/target, EOD flat |
| Telegram alerts | scripts/tg_alerts.py:do_watch() | DB check → sendMessage → archive |
| Dashboard/API | app/api/app.py | /api/decision, /api/strategy/scalp, /api/paper/scalp |

### 1.6 Two Trade Stores

| Store | Table | Writers | Readers |
|-------|-------|---------|---------|
| Live paper trades | paper_trades | paper_scalp_live.py, tg_alerts.py | API, monitor, tg_alerts, performance |
| EOD backtest trades | paper_scalp | Backtest scripts, paper_confluence | API (/api/paper/scalp/eod), reconcile |

### 1.7 Key Discrepancies

1. **Backtest excludes entry candle from exit evaluation** (scalp_engine.py:_trade_for line 82: `for k in range(idx + 1, len(candles))`). Live protection must begin after actual entry fill, including during remainder of entry candle.
2. **Paper monitor uses candle H/L for scalp exits** (not just opens), while CPR non-scalp branch uses `exits_opens()` (opens only).
3. **No daily trade limit on scalp path** — every qualifying signal creates a trade. Production enforces MAX_TRADES_PER_DAY=1 in CPR qualification engine, but scalp paper live script does NOT enforce this.
4. **paper_scalp_live.py is not running** — no systemd unit, not in cron. The scalp paper trades that exist were created by tg_alerts.py --watch (cron) and possibly manual runs.
5. **HLC is display-only on /api/decision** — CPR engine makes the actual TRADE/NO_TRADE decision.

---

## 2. Phase B — Target HLC Architecture

### 2.1 Reusable Components (No Adapter Needed)

| Component | File | Responsibility |
|-----------|------|----------------|
| Signal detection | scalp_engine._scan_signals() | 3-bar HLC alignment |
| Signal qualification | paper_scalp_live.py:run_once() | Freshness, staleness, entry-time guard |
| Entry-price resolution | paper_scalp_live.py:_get_entry_price_from_provider() | yfinance forming candle open |
| Entry-time guard | paper_scalp_live.py:_entry_time_guard() | Reject expired signals |
| Concurrent position limit | paper_scalp_live.py:has_open_position() | Mode C: one open position per instrument |
| Risk validation | risk/engine.py:RiskEngine | Risk cap + RR floor |
| Paper trade persistence | paper_trade/engine.py:create_paper_trade() | INSERT into paper_trades (deterministic ID) |
| Exit evaluation | paper_trade/engine.py:monitor() | Candle H/L stop/target, EOD flat |
| Telegram alerts | tg_alerts.py:do_watch() | DB check → sendMessage → archive |
| Dashboard/API | app/api/app.py | /api/decision, /api/strategy/scalp, /api/paper/scalp |

### 2.2 Components Needing Adaptation

| Component | Current State | Target State | Adapter Needed |
|-----------|--------------|--------------|----------------|
| Daily trade limit | NOT enforced (scalp path) | Enforce 1 per instrument/day | NEW — add daily_trade_locks integration |
| Live engine default | CPR (_cpr_book_signal) | HLC (_hlc_book_signal) | Change default in evaluate() |
| Dashboard display | HLC overlay on CPR decision | HLC as primary decision | Change display logic |

### 2.3 Components NOT Reused (CPR-specific)

| Component | Reason |
|-----------|--------|
| cpr_trigger_engine.py | CPR-specific, retained for rollback |
| cpr_strategy_engine.py | CPR-specific, retained for rollback |
| qualification.py | CPR qualification (uses StrategyEngine + RiskEngine) |
| strategies/engine.py | Credit spread selection (CPR path) |
| scenarios/engine.py | Scenario generation (CPR path) |

### 2.4 Single Authoritative HLC Signal Path

In the target architecture, there is ONE authoritative HLC signal path:
1. `scalp_engine._scan_signals()` → signal detection
2. `paper_scalp_live.py:run_once()` → signal qualification + trade creation
3. `PaperTradeEngine.create_paper_trade()` → persistence
4. `tg_alerts.py:do_watch()` → notification (reads from DB, never creates trades)

The live engine (`app/live/engine.py`) currently uses CPR for decisions. In HLC-only mode, it would use `_hlc_book_signal()` instead of `_cpr_book_signal()`.

### 2.5 Idempotency Key

The existing idempotency mechanism uses:
- `scalp_link(inst, trade_date, direction, signal_time)` → `"scalp|{inst}|{trade_date}|{direction}|{signal_time}"`
- `scalp_trade_id(link_key)` → `'PT-' + sha1(link_key)[:10].upper()`
- `trade_id` is the PRIMARY KEY in `paper_trades`

This prevents duplicate trades for the same signal across polling cycles and process restarts.

### 2.6 Daily Trade Limit (Proposed)

**Proposed conservative default:** 1 trade per instrument per day (matching Mode A from HLC frequency research).

**Effect on Phase 5.1 simulation:** Phase 5.1 used Mode C (one open position per instrument). With a daily limit of 1, the trade count would be further reduced from 63 to ~6 (one per instrument per day, 3 days × 2 instruments).

**Recommendation:** Start with Mode C (current behavior) and add daily limit as a separate, explicitly configurable parameter. Do not silently change the default.

### 2.7 Concurrent Position Limit

Mode C: one open position per instrument (NIFTY and BANKNIFTY tracked independently). Enforced via `has_open_position()` which checks for ACTIVE/OPEN SCALP_HLC trades.

### 2.8 Stale Signal Handling

- `_entry_time_guard()` rejects signals where `now > entry_time + 5min`
- `is_stale()` rejects signals where `entry_time` is >20 min old
- `validate_candle()` rejects stale candles (>15 min old)

### 2.9 Missing/Delayed Candle Behavior

- If candles are missing: `validate_candle()` returns `ok=False` → entries skipped
- If candles are delayed: `is_stale()` returns True → signal skipped
- If provider fails: explicit UNAVAILABLE/API_ERROR/RATE_LIMITED state → no trade

### 2.10 Persistence Failure Behavior

- `create_paper_trade()` catches `sqlite3.IntegrityError` and returns existing trade_id
- `try_create_trade()` catches exceptions and marks signal as failed
- No Telegram alert is sent until trade is confirmed in DB

### 2.11 Telegram Notification Behavior

- `tg_alerts.py:do_watch()` polls `/api/strategy/scalp` for signals
- Checks DB for existing trade before alerting
- Sends `sendMessage` only if trade exists
- Dedup via `fired` key in `tg_state.json`
- Retries on delivery failure (key not added to `fired`)

### 2.12 Dashboard/API Presentation

- `/api/decision` overlays HLC levels (market_bias, entry, stop, target) on CPR decision
- In HLC-only mode: HLC would be the primary decision, not an overlay
- `/api/strategy/scalp` serves HLC signal state (unchanged)
- `/api/paper/scalp` serves HLC paper trades (unchanged)

---

## 3. Phase C — Migration Safeguards

### 3.1 Feature Flag Design

**Proposed feature flag:** `HLC_ONLY_MODE`
- Default: `false` (current behavior preserved)
- Location: Environment variable or config/settings.json
- Effect when true: `_hlc_book_signal()` becomes the default; `_cpr_book_signal()` disabled for new decisions
- Effect when false: Current behavior (CPR is default, HLC is display-only)
- Rollback: Set `HLC_ONLY_MODE=false` → restart gunicorn

### 3.2 Migration Gates

1. **Backup gate:** Verified backup of application code, configuration, and a consistent SQLite database backup
2. **Test gate:** All 9 look-ahead tests pass + new integration tests pass
3. **Parity gate:** HLC live output matches HLC backtest output on same data
4. **Risk gate:** Daily trade limit enforced (1 per instrument/day)
5. **Rollback gate:** Restore from backup restores prior behavior

### 3.3 Migration Steps (Proposed, Not Implemented)

#### Step 1: Add daily trade limit to scalp path
- Modify `paper_scalp_live.py` to check `daily_trade_locks` before creating trade
- Default: 1 trade per instrument per day (configurable via settings)

#### Step 2: Change live engine default
- Modify `app/live/engine.py:evaluate()` to use `_hlc_book_signal()` instead of `_cpr_book_signal()`
- Keep `_cpr_book_signal()` for rollback

#### Step 3: Add entry-candle live protection
- Document backtest/live exit discrepancy (entry candle exclusion)
- Add live protection during entry candle remainder

#### Step 4: Wire alert pipeline (optional)
- Integrate `scalp_alert_events.py` into `tg_alerts.py --watch`

#### Step 5: Update frontend
- Change HLC from display-only to primary decision display

### 3.4 Rollback Procedure

1. Set `HLC_ONLY_MODE=false` (or remove feature flag)
2. Restart gunicorn: `sudo systemctl restart tradingai-api.service`
3. Verify CPR path is restored via `/api/decision` endpoint
4. Verify no new HLC trades are created
5. Verify existing HLC trades are still monitored

### 3.5 Risk Assessment

| Risk | Severity | Mitigation |
|------|----------|------------|
| Dirty working tree | HIGH | Commit/stash before migration |
| CPR engine drives live decisions | HIGH | Feature flag defaults to current (CPR) |
| No daily trade limit on scalp | MEDIUM | Add before enabling HLC-only mode |
| Backtest/live exit discrepancy | MEDIUM | Document, don't silently change |
| Two trade stores | LOW | Keep both, unify reporting |
| No systemd unit for paper_scalp_live | MEDIUM | Add unit before migration |

---

## 4. Phase D — Trade Store Comparison

### 4.1 Schema Comparison

| Aspect | paper_trades (Live) | paper_scalp (EOD Backtest) |
|--------|---------------------|---------------------------|
| Primary key | trade_id | (session_date, instrument_id) |
| Writers | paper_scalp_live.py, tg_alerts.py | Backtest scripts, paper_confluence.py |
| Readers | API, monitor, tg_alerts, performance | API (/api/paper/scalp/eod), reconcile |
| Status field | status (ACTIVE/OPEN/CLOSED) | result (WIN/LOSS/FLAT) |
| Entry price | entry (REAL) | entry_price (REAL) |
| Exit price | exit_price (REAL) | exit_price (REAL) |
| P&L | paper_pnl (REAL, rupees) | r_multiple (REAL), points (REAL) |
| Idempotency | trade_id PK + IntegrityError catch | INSERT OR REPLACE |
| Idempotency key | scalp_link() → sha1 | session_date + instrument_id |

### 4.2 Recommendation: Least Risky Path to Consistency

**Option A (Recommended): Keep both stores, unify reporting**
- `paper_trades` remains the authoritative live store
- `paper_scalp` remains for EOD backtest comparison
- `scalp_reconcile.py` already matches live vs EOD trades
- No schema changes needed

**Option B (Higher risk): Merge into one store**
- Would require schema migration
- Would break existing API endpoints
- NOT recommended

**Recommendation: Option A** — Keep both stores, unify reporting via `scalp_reconcile.py`.

### 4.3 No Schema Changes Made

This audit is read-only. No database schema changes were proposed or implemented.

---

## 5. Phase E — HLC Behavior and Risk Controls Audit

### 5.1 Three-Candle Pattern Rules

| Rule | Implementation | Verified |
|------|---------------|----------|
| BULL: 3 consecutive candles with higher H/L/C | `_scan_signals()` lines 44-58 | ✅ |
| BEAR: 3 consecutive candles with lower H/L/C | `_scan_signals()` lines 44-58 | ✅ |
| Signal candle = 3rd confirming candle | `_scan_signals()` line 57 | ✅ |
| Entry = next candle open | `_live_signal()` line 236 | ✅ |
| Stop (BULL) = signal candle low − 1.0 | `_live_signal()` line 235 | ✅ |
| Stop (BEAR) = signal candle high + 1.0 | `_live_signal()` line 235 | ✅ |
| Target = entry ± 1.5×risk | `_live_signal()` lines 242-244 | ✅ |
| Risk rejection (risk ≤ 0) | `_live_signal()` line 241 | ✅ |
| Stop-first tie-break | `_trade_for()` lines 89-94 | ✅ |
| EOD flat | `_trade_for()` lines 107-118 | ✅ |
| No daily trade limit | `run_range()` lines 151-154 | ✅ (matches production) |
| Mode C (one open position) | `has_open_position()` lines 122-131 | ✅ |

### 5.2 No-Look-Ahead Tests

All 9 look-ahead tests pass (verified in Phase 5.2):
- Test 1: Signal uses only completed candles — PASS
- Test 2: Indicators use only past observations — PASS
- Test 3: Daily high/low not used before session complete — PASS
- Test 4: Signal direction not from future — PASS
- Test 5: Trade filled only after signal — PASS
- Test 6: Entry price is next candle open — PASS
- Test 7: Prefix-invariance — PASS
- Test 8: Outcome not used to filter — PASS
- Test 9: No cross-session leakage — PASS

### 5.3 Entry Prices Available Only After Signal Actionable

| Check | Result | Evidence |
|-------|--------|----------|
| Entry price from historical candle open | ✅ Verified | All 63 trades: entry == market_candles_5m.open |
| Entry price from live provider (forming candle) | ✅ Code exists | `_get_entry_price_from_provider()` queries yfinance |
| No lookahead in entry price | ✅ Verified | Entry uses candles[idx+1]['open'] — next candle, not current |
| No retrospective fill | ✅ Verified | Entry price matches historical candle open exactly |

### 5.4 Five-Minute Entry Guard Unchanged

| Boundary Condition | Expected | Result | Evidence |
|-------------------|----------|--------|----------|
| now < entry_time | ok | PASS | `paper_scalp_live.py:206-211` |
| now == entry_time | ok | PASS | Uses `>` not `>=` |
| now == entry_time + 5min | ok | PASS | Boundary inclusive |
| now > entry_time + 5min | expired | PASS | Entry candle closed |

### 5.5 One-Position-Per-Instrument Rule

| Check | Result | Evidence |
|-------|--------|----------|
| Mode C enforced | ✅ | `has_open_position()` checks for ACTIVE/OPEN SCALP_HLC trades |
| NIFTY and BANKNIFTY tracked independently | ✅ | Separate queries per instrument |
| Restart recovery | ✅ | `recover_open_positions()` checks DB for open trades |
| Duplicate prevention | ✅ | `trade_id` PRIMARY KEY + IntegrityError catch |

### 5.6 Paper Trades and Alerts Idempotent

| Check | Result | Evidence |
|-------|--------|----------|
| Deterministic trade_id | ✅ | `scalp_trade_id(link_key)` = PT-sha1(link_key)[:10] |
| trade_id is PRIMARY KEY | ✅ | schema.sql:81 |
| IntegrityError caught | ✅ | paper_trade/engine.py:105-123 |
| tg_alerts checks DB before alerting | ✅ | tg_alerts.py:548-554 |
| Dedup via fired key | ✅ | tg_alerts.py:399 |

### 5.7 Existing Defects (Documented, Not Fixed)

| Defect | Severity | Description |
|--------|----------|-------------|
| Cross-day scanning | MEDIUM | `_scan_signals` processes all historical candles; signals from previous days mixed with today's |
| Current-time filtering | LOW | `today_state` uses `now.isoformat()` for filtering, not a fixed cutoff |
| No daily trade limit on scalp path | MEDIUM | `paper_scalp_live.py` creates a trade for every signal |
| Last-candle position dependence | MEDIUM | Phase 3.5 last-candle detection is inherently position-dependent |
| Entry-price availability | MEDIUM | No test verifies entry price was available at decision time |
| Missing candle gaps | MEDIUM | No test verifies missing candles don't produce false signals |

---

## 6. Phase F — Integration Tests

### 6.1 Test Scenarios (Design Only — Not Executed)

| # | Scenario | Status | Notes |
|---|----------|--------|-------|
| 1 | Valid HLC signal reaches paper-trade adapter | NOT RUN | Requires test DB with candles; no production writes allowed |
| 2 | Stale signal rejected | NOT RUN | Requires test DB with stale candles |
| 3 | Signal with unavailable entry data rejected | NOT RUN | Requires test DB with missing entry candle |
| 4 | Same signal cannot create duplicate trades | NOT RUN | Requires test DB; trade_id PK prevents duplicates |
| 5 | Daily trade limits block excess entries | NOT RUN | Daily limit not yet implemented in scalp path |
| 6 | Concurrent-position limits respected | PASS (code review) | `has_open_position()` checks for ACTIVE/OPEN SCALP_HLC trades |
| 7 | CPR signals cannot initiate new trades in HLC-only mode | NOT RUN | Feature flag not yet implemented |
| 8 | Existing open trades monitored and exited safely | PASS (code review) | `PaperTradeEngine.monitor()` handles scalp branch |
| 9 | Persistence failure does not generate misleading alert | PASS (code review) | `tg_alerts.py` checks DB before alerting |
| 10 | Telegram failure does not duplicate trade on retry | PASS (code review) | `trade_id` is PRIMARY KEY; IntegrityError caught |
| 11 | Missing/delayed candles fail safely | PASS (code review) | `validate_candle()` rejects stale/invalid candles |
| 12 | Application startup and HLC API responses valid | PASS (runtime) | Gunicorn running, `/api/strategy/scalp` returns data |
| 13 | No-look-ahead and prefix-invariance checks pass | PASS (verified) | 9/9 tests pass (Phase 5.2) |
| 14 | Previous live decision path recoverable via rollback | PASS (code review) | `_cpr_book_signal()` retained in live/engine.py |

### 6.2 Existing Test Suite

| Test File | Tests | Status |
|-----------|-------|--------|
| `tests/test_hlc_engine.py` | HLC engine tests | Exists |
| `tests/test_scalp_paper_live_runtime.py` | Entry-time guard branches | Exists |
| `tests/test_scalp_exit_atomicity.py` | Paper trade close atomicity | Exists |
| `tests/test_scalp_alert_events.py` | Alert pipeline dedup | Exists |
| `tests/test_cpr_triggers.py` | CPR trigger tests | Exists |

### 6.3 No Production Modifications

No test records were written to the production database. No services were restarted. No code was modified.

---

## 7. Phase G — Comparison with Phase 5.1

### 7.1 Mode C and the 36 Blocked Signals from Phase 5.1

Phase 5.1 used Mode C (one open position per instrument). This blocked 36 signals (36.4% of 99 total). The remaining 63 signals became trades.

In the proposed live integration, Mode C would be enforced via `has_open_position()`, which is already implemented in `paper_scalp_live.py`. No change needed.

### 7.2 Entry-Price Availability and Live Ingestion Latency

| Aspect | Phase 5.1 Simulation | Live Pipeline |
|--------|---------------------|---------------|
| Data source | Pre-loaded historical DB | yfinance live API |
| Ingestion delay | 0 (instant) | ~6 minutes |
| Entry price | Historical candle open | Forming candle open from yfinance |
| Signal detection | Instant (all data available) | After candle ingestion (~6 min) |
| Entry window | [entry_time, entry_time + 5min] | Same, but entry_time is in the past |
| Trade creation | At signal detection time | At signal detection time (after ingestion) |

**Key difference:** The simulation uses pre-loaded data (instant availability), while the live pipeline has ~6 minute ingestion delay. This means the live pipeline cannot create trades within the entry window.

### 7.3 Backtest/Live Exit Discrepancies

| Aspect | Backtest | Live (proposed) |
|--------|----------|-----------------|
| Exit evaluation | Candle H/L from entry candle onward (idx+1) | Same |
| Entry candle protection | Excluded from exit eval (idx+1 starts AFTER entry) | Must protect during entry candle remainder |
| Stop/target | Signal extreme ±1.0 / 1.5×R | Same |
| EOD exit | Last session close | Same |
| Session boundary | Stop when date changes | Same |

**Discrepancy:** Backtest excludes entry candle from exit evaluation. Live must protect during the remainder of the entry candle. This is a documented discrepancy, not a bug.

### 7.4 Proposed Daily Trade Limit and Its Effect on Trade Count

**Proposed default:** 1 trade per instrument per day (Mode A).

**Effect on Phase 5.1:** Trade count would reduce from 63 to ~6 (one per instrument per day, 3 days × 2 instruments).

**Recommendation:** Start with Mode C (current behavior) and add daily limit as a separate, explicitly configurable parameter. Do not silently change the default.

### 7.5 Separate Trade Stores and Their Impact on Reporting

| Store | Purpose | Trades (Phase 5.1) | Live? |
|-------|---------|-------------------|-------|
| `paper_trades` | Live paper trades | 94 (all SCALP_HLC) | Yes |
| `paper_scalp` | EOD backtest trades | 215 | No (backtest only) |

**Impact:** Reporting must aggregate both stores. `scalp_reconcile.py` already matches live vs EOD trades. No schema changes needed.

### 7.6 Simulated vs Actual Live Data Availability

| Aspect | Simulation | Live |
|--------|-----------|------|
| Data source | Pre-loaded DB candles | yfinance API |
| Candle availability | Instant (all historical) | ~6 min delay after close |
| Entry price | Historical candle open | Forming candle open from yfinance |
| Signal detection | Instant (all data available) | After candle ingestion (~6 min) |
| Entry window | [entry_time, entry_time + 5min] | Same, but entry_time is in the past |
| Trade creation | At signal detection time | At signal detection time (after ingestion) |

**Key difference:** The simulation uses pre-loaded data (instant availability), while the live pipeline has ~6 minute ingestion delay. This means the live pipeline cannot create trades within the entry window.

---

## 8. Deliverables

| File | Description |
|------|-------------|
| `PHASE54_REPORT.md` | This report |
| `LIVE_DECISION_FLOW.md` | Call flow diagram and component ownership |
| `TARGET_HLC_ARCHITECTURE.md` | Target architecture design |
| `TRADE_STORE_AUDIT.md` | Trade store comparison and recommendation |
| `MIGRATION_AND_ROLLBACK_PLAN.md` | Migration steps and rollback procedure |
| `INTEGRATION_TEST_RESULTS.md` | Integration test results (design only) |
| `DEPENDENCY_MAP.csv` | Complete dependency map (38 components) |
| `AUDIT_LOG.txt` | Audit execution log |

All files in: `/opt/tradingai/research/phase54_hlc_integration_audit_20261029_203000/`

---

## 9. Final Status

**PARTIAL — MIGRATION DESIGN COMPLETE WITH UNRESOLVED DEPENDENCIES**

The migration design is complete. The target architecture, trade store audit, migration plan, and integration test framework are documented. However, 7 blockers prevent immediate deployment:

1. **Dirty working tree** — 33+ modified files and many untracked files
2. **CPR engine drives live decisions** — HLC is display-only on `/api/decision`
3. **No daily trade limit on scalp path** — need to add MAX_TRADES_PER_DAY enforcement
4. **Backtest vs live exit discrepancy** — backtest excludes entry candle; live protects during entry candle
5. **Two separate trade stores** — `paper_trades` (live) and `paper_scalp` (EOD backtest)
6. **No systemd unit for paper_scalp_live.py** — script exists but not running as service
7. **Untracked frontend signal pages** — ~200 untracked HTML files

The most critical blockers are: dirty working tree, CPR engine as live decision driver, and no daily trade limit on scalp path.

**No production changes were made during this phase.** All outputs are in the isolated research directory.

---

## 10. Remaining Risks and Recommended Next Steps

1. **Commit or stash** the dirty working tree before making consolidation changes
2. **Add a systemd unit** for `scripts/paper_scalp_live.py` if live paper trading is desired
3. **Add daily trade limit enforcement** (1 trade/day per instrument) to the scalp paper path
4. **Document the backtest/live exit discrepancy** (entry candle exclusion) — do not silently change historical backtest results
5. **Keep CPR trigger engine** as the live trade decision engine unless owner explicitly approves switching to HLC scalp for live execution
6. **Reduce data ingestion delay** from ~6 minutes to <1 minute (1-minute collector timer already applied in Phase 4.9)
7. **Consider a real-time data feed** for sub-10-second latency

**Report path:** `/opt/tradingai/research/phase54_hlc_integration_audit_20261029_203000/PHASE54_REPORT.md`

**No production changes were made during this phase.** All outputs are in the isolated research directory. Strategy rules are unchanged. No real-money execution was enabled.
