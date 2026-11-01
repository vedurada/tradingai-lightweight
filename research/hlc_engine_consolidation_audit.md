# HLC Engine Consolidation Audit — Phase 1 (Read-Only)

**Repository:** `/opt/tradingai` (VM: `ubuntu@129.159.224.81`)
**Branch:** `production-2026-10-01` (tracking `origin/production-2026-10-01`)
**Audit date:** 2026-10-28
**Constraint:** No files, databases, services, crontabs, or Git state were modified during this phase.

---

## 1. Git State (Pre-Change Baseline)

| Item | Value |
|---|---|
| Active branch | `production-2026-10-01` |
| Remote tracking | `origin/production-2026-10-01` (up to date) |
| Working tree | **DIRTY** — 33+ modified files, many untracked |
| HEAD commit | `7da4b21 feat(scalp): add 1m scalp backtest script` |
| Recent scalp commits | `9889653` (daily-bar scalp), `0ac0192` (ScanLP engine + store + reconcile + live adapter) |

### Modified tracked files (relevant to consolidation)
- `app/research/scalp_engine.py` — canonical HLC 3-bar engine
- `app/research/scalp_signal_store.py` — persistent signal identity
- `app/api/app.py` — API routes (scalp overlay on decision, scalp backtest/paper routes)
- `app/paper_trade/engine.py` — paper trade persistence + monitor (includes scalp branch)
- `app/strategies/scalp.py` — thin strategy adapter
- `scripts/paper_scalp_live.py` — live paper trading loop
- `scripts/tg_alerts.py` — Telegram alerts (watch mode polls scalp API)
- `scripts/paper_confluence.py` — paper confluence/topup
- `scripts/build_alerts_page.py` — alerts page builder
- `scripts/apply_strategy_note.py`, `scripts/signal_articles.py`
- `frontend/scalp.html`, `frontend/signals.html`, `frontend/signal-flow.html`, `frontend/index.html`, `frontend/indices/nifty.html`, `frontend/indices/banknifty.html`, `frontend/paper.html`, `frontend/backtest.html`, `frontend/methodology.html`, `frontend/tools.html`, `frontend/how-to-use-*.html`, `frontend/learn.html`, `frontend/how-to-use-website.html`, `frontend/rss.xml`, `frontend/free-backtesting-tool.html`

### Untracked new files (relevant to consolidation)
- `app/research/scalp_alert_events.py` — P0.14 alert event pipeline (NOT wired into live runtime)
- `tests/test_scalp_alert_events.py`, `tests/test_scalp_exit_atomicity.py`, `tests/test_scalp_paper_live_runtime.py`
- `research/multi_indicator_confirmation_backtest.py` (+ results CSV/JSON)
- `research/trend_reversal_continuation_backtest.py` (+ results)
- `scripts/scalp_3candle_preserve.py`
- `frontend/scalp_5m_chart.html`, `frontend/scalp_5m_chart_banknifty.html`
- `frontend/signals/plain/2026-*-*_H1_*.html` (daily scalp signal HTML pages, Jul–Oct 2026)
- `frontend/multi_indicator_confirmation_trades.csv`, `frontend/multi_indicator_confirmation_results.json`

---

## 2. Complete Inventory of Existing Engines

| # | Engine | File | Purpose | Status |
|---|---|---|---|---|
| 1 | **Scalp HLC 3-Bar** | `app/research/scalp_engine.py` | 3-bar HLC alignment trigger, next-open entry, ±1pt stop, 1.5R target | **Canonical candidate** |
| 2 | **CPR Trigger** | `app/research/cpr_trigger_engine.py` | CPR-based triggers, weekly gate, 0.5% stop / 2% target, no-chase BEAR re-anchor | **Current live trade decision engine** |
| 3 | **Backtest** | `app/research/backtest.py` | Historical backtest engine (separate from scalp) | Active |
| 4 | **Paper Trade** | `app/paper_trade/engine.py` | Paper trade persistence + monitor (scalp branch + CPR exits_opens branch) | Active |
| 5 | **Strategies Adapter** | `app/strategies/scalp.py` | Thin wrapper around scalp_engine | Active |
| 6 | **Alert Pipeline** | `app/research/scalp_alert_events.py` | P0.14 idempotent alert events (in-memory, NOT wired to live) | Not wired |
| 7 | **Signal Store** | `app/research/scalp_signal_store.py` | Persistent signal identity in `scalp_signals` table | Active |
| 8 | **Validation** | `app/research/scalp_validation.py` | Candle validation helpers | Active |
| 9 | **Reconcile** | `app/research/scalp_reconcile.py` | Reconciles live paper trades vs EOD backtest | Active |
| 10 | **Live Engine** | `app/live/engine.py` | CPR-book trigger — drives `/api/decision` | Active (live decisions) |
| 11 | **Live Paper Replay** | `app/research/live_paper_replay.py` | Replay helper | Reference |

---

## 3. File Paths and Entry Points for Every Engine

### 3.1 Scalp HLC 3-Bar Engine — `app/research/scalp_engine.py`

**Public API:**
- `run_opens_range(instrument, date_start, date_end, variant='plain', stop_pct=0.005, target_pct=0.02)` → backtest over date range
- `run_range(instrument, date_start, date_end)` → internal backtest
- `today_state(instrument, now_ist=None, variant='plain')` → today's live signal state
- `today_signals(instrument, now_ist=None, variant='plain')` → list of today's signals
- `scalp_signal(*a, **k)` → alias for `today_state`
- `decay_win(direction, entry, exit_px, r_multiple, instrument)` → decay-tolerant win/loss

**Internal:**
- `_load_candles(instrument)` — loads all 5m candles from `market_candles_5m`
- `_features(candles)` — computes H/L/C deltas between consecutive candles
- `_scan_signals(candles)` — finds 3-bar alignment signals
- `_trade_for(candles, idx, direction)` — simulates one trade (entry, stop, target, exit)
- `_live_signal(candles, idx, direction, inst, day_iso, variant)` — live signal dict

**Rules (from code):**
- Signal: 3 consecutive candles where each has higher H/L/C than previous (BULL) or lower H/L/C (BEAR)
- Entry: next candle's open (`candles[idx+1]['open']`)
- Stop (BULL): signal candle low − 1.0; Stop (BEAR): signal candle high + 1.0
- Risk = \|entry − stop\|; Target = entry ± 1.5 × risk
- Exit: scan completed candles after entry candle; stop-first tie-break on same candle
- EOD: if neither level hit, exit at last session candle's close
- Invalid risk (≤0) → trade rejected
- Session boundary: stop scanning when candle date changes

### 3.2 CPR Trigger Engine — `app/research/cpr_trigger_engine.py`

**Public API:**
- `run_opens_range(instrument, date_start, date_end, variant='plain', stop_pct=0.005, target_pct=0.02)`
- `today_state(instrument, now_ist=None, variant='aligned')`

**Rules:** CPR-based triggers (breakout above TC, below BC, etc.), weekly gate, bear priority, no-chase BEAR re-anchor. **Different from HLC scalp.**

### 3.3 Paper Trade Engine — `app/paper_trade/engine.py`

**Class:** `PaperTradeEngine`
- `create_paper_trade(qualified_trade, link_key=None)` — persists paper trade
- `monitor(instrument_id)` — next-bar, no-lookahead exit evaluation

**Scalp branch (lines 269–340):** When `is_scalp` (scenario == 'SCALP_HLC' or 'SCALP' in strategy):
- Evaluates candle H/L (not just opens) for stop/target hits
- STOP-first tie-break on same candle
- EOD flat at 15:25 close if still open after 15:30 IST
- **Bypasses** the correlated-position cap (`max_positions_per_direction`) for scalp trades

**Non-scalp branch:** Uses `exits_opens()` from `cpr_trigger_engine` — 0.5% stop / 2% target on next-bar opens only.

### 3.4 Strategies Adapter — `app/strategies/scalp.py`

```python
class ScalpEngine:
    def today_state(self, instrument, now_ist=None, variant='plain')
    def run_backtest(self, instrument, date_start, date_end, variant='plain')
    def first_trigger(self, candles)
```
Thin wrapper delegating to `scalp_engine`.

### 3.5 Alert Pipeline — `app/research/scalp_alert_events.py`

**P0.14 — NOT wired into any live runtime.** In-memory default store; SQLiteEventStore for tests only.
- `AlertPipeline.process_signal(signal, trade_creator)` — idempotent signal confirmation + trade creation
- `AlertProvider` protocol (MockProvider, TelegramProvider — dry-run only, no live send)

### 3.6 Signal Store — `app/research/scalp_signal_store.py`

Table: `scalp_signals` (19 rows)
- `record_signal(conn, ...)` — insert with deterministic ID `SS-<sha1(instrument|candle_ts|direction|level)>`
- `mark_traded(conn, signal_id, trade_id)` — status → TRADED
- `mark_failed(conn, signal_id, reason)` — keeps status NEW for retry
- `mark_expired(conn, signal_id, reason)` — status → EXPIRED
- `recover_new_signals(conn)` — returns NEW signals for recovery
- `find_existing_trade(conn, instrument, trade_date)` — checks paper_trades for existing

### 3.7 Validation — `app/research/scalp_validation.py`

- `validate_candle(c, prev, now)` — timestamp, OHLC validity, gap checks, session bounds
- `latest_candle_ok(candles)` — validates last candle vs previous

### 3.8 Reconcile — `app/research/scalp_reconcile.py`

- `reconcile(conn)` — matches live paper_trades (SCALP_HLC) with EOD paper_scalp rows by (instrument, date, direction)

### 3.9 Live Engine — `app/live/engine.py`

**NOT the HLC scalp engine.** Uses `_cpr_book_signal` → `book_scan` from `cpr_trigger_engine`. Drives `/api/decision/<symbol>`. The scalp engine is applied only as a **display overlay** in `app/api/app.py:155–187`.

### 3.10 Scripts

| Script | Purpose | Runtime |
|---|---|---|
| `scripts/paper_scalp_live.py` | Live paper trading loop (5s poll), creates scalp signals + trades | **NOT running** (no systemd unit) |
| `scripts/tg_alerts.py --watch` | Telegram alerts for scalp signals (polls `/api/strategy/scalp`) | Cron: every minute 09–15 Mon–Fri |
| `scripts/tg_alerts.py --reconcile` | Morning repair / backfill | Cron: 10:09 Mon–Fri |
| `scripts/paper_confluence.py --topup` | Paper topup | Cron: 15:45 Mon–Fri |
| `scripts/build_alerts_page.py` | Builds alerts HTML page | Called by tg_alerts |

---

## 4. Runtime Service and Scheduler Dependencies

### Systemd Services

| Service | File | Status | Notes |
|---|---|---|---|
| `tradingai-api.service` | `/etc/systemd/system/tradingai-api.service` | **active** | gunicorn 2 workers × 4 threads on 127.0.0.1:8000 |
| `tradingai-market-data.service` | `/etc/systemd/system/tradingai-market-data.service` | **inactive** | Market data collector (oneshot) |
| `tradingai-watchdog.service` | `/etc/systemd/system/tradingai-watchdog.service` | **inactive** | Self-heal probe (oneshot, timer every 2 min) |

**No systemd unit exists for `scripts/paper_scalp_live.py`.** It is not running as a service.

### Timers

| Timer | Schedule | Status |
|---|---|---|
| `tradingai-watchdog.timer` | Every 2 min | Active (but service inactive) |
| `tradingai-market-data.timer` | Mon–Fri 09:1x/10–15:xx/5 | Active |

### Cron Jobs (relevant to scalp/HLC)

| Schedule | Command |
|---|---|
| `* 9-15 * * 1-5` | `scripts/tg_alerts.py --watch` (every minute during market hours) |
| `10 9 * * 1-5` | `scripts/tg_alerts.py --reconcile` |
| `45 15 * * 1-5` | `scripts/paper_confluence.py --topup` |
| `5 16 * * 1-5` | `scripts/build_replay.py` |
| `50 15 * * 1-5` | `scripts/learn_losses.py --include-today` |
| `52 15 * * 1-5` | `scripts/veto_paper_book.py` + `scripts/veto_score.py --decay` |

### Running Processes

Only gunicorn workers for the API are running. No `paper_scalp_live.py` or `tg_alerts.py --watch` process is currently active (they run via cron).

---

## 5. Database Tables and Data Ownership

| Table | Schema File | Rows | Owner / Writer | Reader |
|---|---|---|---|---|
| `market_candles_5m` | `schema.sql` | 5,996 (NIFTY), 5,996 (BANKNIFTY) | `app/market/collector.py` | All engines (read-only) |
| `scalp_signals` | `scalp_signal_store.py` CREATE_SQL | 19 | `scripts/paper_scalp_live.py` (`record_signal`) | API, signal store |
| `paper_trades` | `schema.sql` | — | `PaperTradeEngine.create_paper_trade()` | API, monitor, reconcile |
| `paper_scalp` | `schema.sql` | 215 | Backtest/EOD process | API `/api/paper/scalp/eod`, reconcile |
| `scalp_alert_events` | `scalp_alert_events.py` (SQLiteEventStore, temp file only) | 0 (not in main DB) | AlertPipeline (tests only) | Not in production |

**Key observation:** `scalp_signals` and `paper_scalp` are separate tables. `paper_trades` stores both SCALP_HLC and non-scalp trades. There is no unified trade table — live trades and EOD backtest trades live in different tables and are reconciled via `scalp_reconcile.py`.

---

## 6. Existing API and UI Dependencies

### API Routes (`app/api/app.py`)

| Route | Method | Engine | Purpose |
|---|---|---|---|
| `/api/strategy/scalp` | GET | `scalp_engine.today_state` | Today's scalp signal state |
| `/api/strategy/scalp-triggers` | GET | `scalp_engine.today_state` | Alias for above |
| `/api/backtest/scalp` | POST | `scalp_engine.run_opens_range` | Historical backtest |
| `/api/backtest/scalp-triggers` | POST | `scalp_engine.run_opens_range` | Alias for above |
| `/api/paper/scalp` | GET | `paper_trades` table (SCALP_HLC) | Live scalp paper trades |
| `/api/paper/scalp/eod` | GET | `paper_scalp` table | EOD backtest trades |
| `/api/paper/scalp/reconciled` | GET | `scalp_reconcile.reconcile()` | Reconciled live + EOD view |
| `/api/<symbol>/decision` | GET | `live_engine` + **scalp overlay** | Live decision with scalp display overlay |

**Critical:** The `/api/decision` endpoint overlays scalp levels (`market_bias`, `entry`, `stop`, `target`) on top of the CPR-engine decision — but the CPR engine still makes the actual TRADE/NO_TRADE decision. Scalp is **display-only** on this endpoint.

### Frontend Pages

| Page | Scalp Dependency |
|---|---|
| `frontend/scalp.html` | Scalp results page (HLC 3-bar) |
| `frontend/signals.html` | Signal notes with TAIRULE scalp rule |
| `frontend/signal-flow.html` | Signal flow diagram with scalp steps |
| `frontend/indices/nifty.html` | Displays scalp overlay from API decision |
| `frontend/indices/banknifty.html` | Displays scalp overlay from API decision |
| `frontend/index.html` | Homepage alert cards |
| `frontend/paper.html` | Paper trades table |
| `frontend/backtest.html` | Backtest results |
| `frontend/methodology.html` | Strategy rules documentation |
| `frontend/scalp_5m_chart.html` (untracked) | Scalp 5m chart |
| `frontend/scalp_5m_chart_banknifty.html` (untracked) | Scalp 5m chart (BANKNIFTY) |

All 8+ frontend pages embed the same TAIRULE div describing the scalp HLC 3-bar rule ("effective 2026-10-26").

---

## 7. Exact Differences Between HLC Backtest, Paper-Trading Engine, Monitor, and Alert Logic

| Aspect | Backtest (`scalp_engine.run_range`) | Paper Monitor (`paper_trade.engine.monitor` scalp branch) | Live Alerts (`tg_alerts.py --watch`) | Paper Live Script (`paper_scalp_live.py`) |
|---|---|---|---|---|
| **Trigger** | 3-bar HLC alignment on all historical candles | N/A (trades already persisted) | 3-bar HLC via `/api/strategy/scalp` | 3-bar HLC via `today_signals()` |
| **Entry reference** | Next candle open (historical) | Stored entry from paper_trades | Next candle open (from API) | Next candle open (from API) |
| **Stop** | Signal candle low − 1 (BULL), high + 1 (BEAR) | Stored stop from paper_trades | Stored stop from API | Stored stop from signal |
| **Target** | Entry + 1.5×R | Stored target from paper_trades | Stored target from API | Stored target from signal |
| **Exit evaluation** | Candle H/L after entry candle | Candle H/L after entry_time (opens strictly after) | N/A (alerts only, no exit) | Candle H/L via `monitor()` |
| **Same-candle stop/target** | STOP priority | STOP priority | N/A | N/A |
| **EOD exit** | Last session close | Last close after 15:30 IST | N/A | N/A |
| **Session boundary** | Stop when date changes | Only candles on entry date | Entry cutoff 15:25 | Entry cutoff 15:25 |
| **Daily trade limit** | None (all signals) | Correlated cap **bypassed** for scalp | One alert per signal (state dedup) | **No daily limit enforced** — creates trade for every signal |
| **Signal persistence** | None (transient) | `paper_trades` table | `paper_trades` + `tg_state.json` | `scalp_signals` + `paper_trades` |
| **Duplicate prevention** | None | PRIMARY KEY on trade_id | `tg_state.json` fired list | `scalp_signals` UNIQUE + status check |
| **Restart recovery** | N/A | `recover_open_positions()` not in monitor | `tg_state.json` fired list | `recover_open_positions()` + `recover_new_signals()` |
| **Risk rejection** | Risk ≤ 0 → None | N/A (stored values) | N/A | `_entry_time_guard()` rejects missing/expired |

### Key Discrepancies

1. **Backtest excludes entry candle from exit evaluation** (line `for k in range(idx + 1, len(candles))`). Live protection must begin after actual entry fill, including during remainder of entry candle. **This is a documented discrepancy per the project spec.**

2. **Paper monitor uses candle H/L for scalp exits** (not just opens), while the CPR non-scalp branch uses `exits_opens()` (opens only). This is an intentional difference per the approved scalp spec.

3. **No daily trade limit in backtest** — every 3-bar signal becomes a trade. Production enforces `MAX_TRADES_PER_DAY = 1` in the CPR qualification engine, but the scalp paper live script does NOT enforce this (it creates a trade for every signal, relying only on the correlated cap which is bypassed for scalp).

4. **`paper_scalp_live.py` is not running** — no systemd unit, not in cron. The scalp paper trades that exist were created by `tg_alerts.py --watch` (cron) and possibly manual runs.

---

## 8. Engines That Can Safely Be Retired (with Evidence)

| Engine | Can Retire? | Evidence |
|---|---|---|
| `app/research/backtest.py` | **NO** — separate backtest engine, may have other callers | Need to verify all callers before retirement |
| CPR trigger engine | **NO** — currently drives live trade decisions via `app/live/engine.py` | Owner rule: never change strategy rules; CPR is the live decision engine |
| `app/research/scalp_alert_events.py` | **MAYBE** — P0.14, NOT wired into live runtime, in-memory only | No production dependencies; but keeping is low-risk |
| Legacy SMA20 percentage levels | **YES** (already retired per code comment in app/api/app.py:155) | Code comment says "not the legacy SMA20 percentage levels" |
| Old `frontend/signals/plain/*_R1.html`, `*_PDH.html`, `*_BRK_*.html` | **YES** — deleted in working tree (replaced by H1_UP/H1_DOWN scalp pages) | Git shows these deleted; new H1_* pages are untracked |

**Do NOT retire:** CPR trigger engine (live decisions), `app/live/engine.py` (live decision pipeline), `app/paper_trade/engine.py` (shared infrastructure), `market_candles_5m` (shared data source).

---

## 9. Proposed Migration Sequence

### Phase 1 — Audit (COMPLETE)
Documented above. No changes made.

### Phase 2 — Canonical Specification
HLC 3-bar rules as specified in the project (already matches `scalp_engine.py` exactly).

### Phase 3 — Implementation Steps

**Step 3a: Establish canonical module**
- `app/research/scalp_engine.py` is already the canonical module. No extraction needed.
- Verify `app/strategies/scalp.py` delegates correctly (it does).

**Step 3b: Unify paper trading to use scalp_engine for signal generation**
- `scripts/paper_scalp_live.py` already uses `scalp_engine.today_signals()` and `scalp_engine._live_signal()` equivalent.
- `scripts/tg_alerts.py --watch` already polls `/api/strategy/scalp` which calls `scalp_engine.today_state()`.
- Both are aligned already.

**Step 3c: Add daily trade limit enforcement to scalp**
- Currently missing in `paper_scalp_live.py` and `tg_alerts.py`.
- Need to add: one trade per day per instrument, persisted across restarts (use `daily_trade_locks` table or `scalp_signals` status).

**Step 3d: Add entry-candle live protection**
- Backtest excludes entry candle from exit evaluation; live must protect during remainder of entry candle.
- Document this discrepancy; do not silently change historical backtest.

**Step 3e: Wire alert pipeline (optional)**
- `scalp_alert_events.py` is not wired. If alerts are to use it, integrate `AlertPipeline` into `tg_alerts.py --watch`.

### Rollback Procedure
1. Git: `git stash` or `git checkout -- <files>` to restore pre-change state
2. Database: No schema changes planned in Phase 3 (only code changes), so no DB rollback needed
3. Services: Restart `tradingai-api.service` if API code changed
4. Cron: No cron changes needed if no new schedules added

### Verification Tests
Existing tests:
- `tests/test_scalp_alert_events.py` — alert pipeline dedup
- `tests/test_scalp_exit_atomicity.py` — paper trade close atomicity
- `tests/test_scalp_paper_live_runtime.py` — entry-time guard branches

New tests needed (Phase 5):
- 3-bar bullish/bearish alignment
- No look-ahead bias
- Next-candle entry reference
- Stop/risk/1.5R target correctness
- Invalid risk rejection
- Same-candle stop/target ambiguity
- Entry-candle live protection
- Session-end exits
- One-trade-per-day enforcement
- Duplicate signal/order prevention
- Restart recovery

---

## 10. Blockers Preventing Safe Migration

| Blocker | Severity | Description |
|---|---|---|
| **Dirty working tree** | HIGH | 33+ modified files and many untracked files. Migration changes could conflict with uncommitted work. |
| **No systemd unit for paper_scalp_live.py** | MEDIUM | The scalp paper trading loop is not running as a service. It exists only as a script, not invoked by cron. |
| **CPR engine drives live decisions** | HIGH | `app/live/engine.py` uses CPR trigger, not HLC scalp. Scalp is display-only on `/api/decision`. Making HLC the default trade engine requires changing the live decision pipeline. |
| **No daily trade limit on scalp path** | MEDIUM | `paper_scalp_live.py` creates a trade for every signal. The correlated cap is bypassed for scalp. Need to add `MAX_TRADES_PER_DAY = 1` enforcement. |
| **Backtest vs live exit discrepancy** | MEDIUM | Backtest excludes entry candle from exit eval; live must protect during entry candle. Must document, not silently change. |
| **Two separate trade tables** | LOW | `paper_trades` (live) and `paper_scalp` (EOD backtest) are separate. Reconciliation is via `scalp_reconcile.py`. |
| **Untracked frontend signal pages** | LOW | ~200 untracked `frontend/signals/plain/2026-*-*_H1_*.html` files exist but are not in Git. |

---

## Recommendation

**Proceed to Phase 2 and 3**, but with these prerequisites:

1. **Commit or stash** the dirty working tree before making consolidation changes.
2. **Add a systemd unit** for `scripts/paper_scalp_live.py` if live paper trading is desired.
3. **Add daily trade limit enforcement** (1 trade/day per instrument) to the scalp paper path.
4. **Document the backtest/live exit discrepancy** (entry candle exclusion) — do not silently change historical backtest results.
5. **Keep CPR trigger engine** as the live trade decision engine unless owner explicitly approves switching to HLC scalp for live execution. The project spec says "Make HLC the default" but also "Do not silently alter its trading rules" and "Never enable live broker order placement without explicit approval."

The HLC engine is already the canonical signal specification for display, backtest, and paper trading APIs. What remains is unifying the daily-limit enforcement, entry-candle protection, and optionally wiring the alert pipeline — all without changing the HLC trading rules themselves.
