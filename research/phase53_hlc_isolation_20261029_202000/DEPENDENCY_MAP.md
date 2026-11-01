# Phase 5.3 — HLC Strategy Dependency Map

**Audit date:** 2026-10-29  
**Host:** webserver (Oracle VM)  
**Application root:** /opt/tradingai

---

## 1. HLC-Required Components

| Component | File | Classification | Evidence |
|-----------|------|---------------|----------|
| HLC Signal Engine | `app/research/scalp_engine.py` | HLC_REQUIRED | Canonical 3-bar HLC alignment trigger (lines 44-58: `_scan_signals`); used by live, paper, backtest, alerts |
| HLC Live Adapter | `app/live/engine.py` | HLC_REQUIRED | `_hlc_book_signal()` (line 578) is the default trade-decision engine; `_cpr_book_signal()` (line 321) retained for rollback |
| HLC Strategy Adapter | `app/strategies/scalp.py` | HLC_REQUIRED | Thin wrapper delegating to `scalp_engine` (today_state, run_backtest, first_trigger) |
| HLC Signal Store | `app/research/scalp_signal_store.py` | HLC_REQUIRED | Persistent signal identity in `scalp_signals` table (19 rows); deterministic SS-<sha1> IDs |
| HLC Validation | `app/research/scalp_validation.py` | HLC_REQUIRED | Candle validation helpers (validate_candle, latest_candle_ok) |
| HLC Reconcile | `app/research/scalp_reconcile.py` | HLC_REQUIRED | Reconciles live paper_trades vs EOD paper_scalp rows |
| Paper Trade Engine | `app/paper_trade/engine.py` | HLC_REQUIRED (shared) | Persists paper trades; scalp branch (lines 269-340) uses HLC stop/target; shared with CPR path |
| Paper Scalp Live | `scripts/paper_scalp_live.py` | HLC_REQUIRED | Live paper trading loop; uses `scalp_engine.today_signals()` |
| Telegram Alerts | `scripts/tg_alerts.py` | HLC_REQUIRED (shared) | Polls `/api/strategy/scalp`, creates paper trades, sends alerts |
| HLC Alert Events | `app/research/scalp_alert_events.py` | HLC_REQUIRED (optional) | P0.14 alert pipeline — NOT wired into live runtime (in-memory only) |

## 2. Shared Infrastructure (NOT strategy-specific)

| Component | File | Classification | Evidence |
|-----------|------|---------------|----------|
| Market Data Provider | `app/market/provider.py` | SHARED_INFRASTRUCTURE | yfinance data source for all strategies |
| Market Data Collector | `app/market/collector.py` | SHARED_INFRASTRUCTURE | Stores completed 5m candles for all strategies |
| Database Access | `app/core/db.py` | SHARED_INFRASTRUCTURE | get_conn(), DB_PATH |
| Config | `app/core/config.py` | SHARED_INFRASTRUCTURE | instruments, settings |
| Decision View | `app/decision/view.py` | SHARED_INFRASTRUCTURE | Read-only decision composer |
| Paper Trade Monitor | `app/paper_trade/engine.py` | SHARED_INFRASTRUCTURE | Monitor + exit evaluation (scalp + CPR branches) |
| Risk Engine | `app/risk/engine.py` | SHARED_INFRASTRUCTURE | Risk cap validation |
| Scenario Engine | `app/scenarios/engine.py` | SHARED_INFRASTRUCTURE | Scenario candidate generation |
| Qualification Engine | `app/core/qualification.py` | SHARED_INFRASTRUCTURE | Trade qualification (used by CPR path) |
| Strategies Engine | `app/strategies/engine.py` | SHARED_INFRASTRUCTURE | Credit spread selection (used by CPR path) |
| API Routes | `app/api/app.py` | SHARED_INFRASTRUCTURE | All API endpoints |
| NSE Calendar | `app/market/nse_calendar.py` | SHARED_INFRASTRUCTURE | Trading day detection |
| Events Calendar | `app/market/events_calendar.py` | SHARED_INFRASTRUCTURE | Scheduled event risk overlay |

## 3. Unrelated Strategy Components (Candidates for Retirement)

| Component | File | Classification | Evidence |
|-----------|------|---------------|----------|
| CPR Trigger Engine | `app/research/cpr_trigger_engine.py` | UNRELATED_STRATEGY | CPR-based triggers, weekly gate, 0.5% stop/2% target. Used by live engine `_cpr_book_signal` (retained for rollback). NOT used by HLC. |
| CPR Strategy Engine | `app/research/cpr_strategy_engine.py` | UNRELATED_STRATEGY | CPR calculation, classification, pivot levels. Used by CPR path only. |
| CPR Gap Walkforward | `app/research/cpr_gap_walkforward_engine.py` | UNRELATED_STRATEGY | CPR gap walk-forward backtest. No HLC dependency. |
| Contrarian Analyzer | `app/research/contrarian_analyzer.py` | UNRELATED_STRATEGY | Contrarian analysis. No HLC dependency. |
| PrevDay Price Action | `app/research/prevday_price_action_engine.py` | UNRELATED_STRATEGY | Prev-day price action. No HLC dependency. |
| Backtest Engine | `app/research/backtest.py` | UNRELATED_STRATEGY | Historical backtest engine (uses QualificationEngine + StrategyEngine). No HLC dependency. |
| Live Paper Replay | `app/research/live_paper_replay.py` | UNRELATED_STRATEGY | Replay helper using CPR trigger engine. No HLC dependency. |
| Live Sim | `app/research/live_sim.py` | UNRELATED_STRATEGY | Simulation using QualificationEngine. No HLC dependency. |
| Replay | `app/research/replay.py` | UNRELATED_STRATEGY | Replay using QualificationEngine. No HLC dependency. |
| Paper Confluence | `scripts/paper_confluence.py` | UNRELATED_STRATEGY | Paper confluence/topup using CPR triggers. No HLC dependency. |
| Engine Walkforward | `scripts/engine_walkforward.py` | UNRELATED_STRATEGY | Walk-forward using CPR trigger engine. No HLC dependency. |
| Signal Articles | `scripts/signal_articles.py` | UNRELATED_STRATEGY | Signal article generation using CPR triggers. No HLC dependency. |
| Shadow Contrarian | `scripts/shadow_contrarian.py` | UNRELATED_STRATEGY | Shadow contrarian analysis. No HLC dependency. |
| Veto Score | `scripts/veto_score.py` | UNRELATED_STRATEGY | Veto scoring. No HLC dependency. |
| Veto Paper Book | `scripts/veto_paper_book.py` | UNRELATED_STRATEGY | Veto paper book. No HLC dependency. |

## 4. Strategy Registration Points

| Location | Function | Strategy Registered | HLC? |
|----------|----------|-------------------|------|
| `app/api/app.py:155-187` | `decision_view()` | Scalp HLC overlay (display-only) | YES (overlay) |
| `app/api/app.py:1204` | `scalp_signal()` | HLC 3-Bar Scalp | YES |
| `app/api/app.py:1224` | `run_scalp_backtest()` | HLC 3-Bar Scalp | YES |
| `app/api/app.py:416` | `run_cpr_trigger_backtest()` | CPR Trigger | NO (legacy) |
| `app/api/app.py:864` | `cpr_trigger_signal()` | CPR Trigger | NO (legacy) |
| `app/live/engine.py:784` | `evaluate()` | HLC 3-Bar Scalp (default) | YES |
| `app/live/engine.py:321` | `_cpr_book_signal()` | CPR Trigger (retained) | NO (rollback) |
| `app/paper_trade/engine.py:269` | `monitor()` | Scalp branch (HLC) + CPR branch | BOTH |
| `scripts/paper_scalp_live.py:153` | `try_create_trade()` | HLC 3-Bar Scalp | YES |
| `scripts/tg_alerts.py:378` | `do_watch()` | HLC 3-Bar Scalp (polls `/api/strategy/scalp`) | YES |

## 5. Database Tables

| Table | Strategy | Status |
|-------|----------|--------|
| `scalp_signals` | HLC 3-Bar Scalp | Active |
| `paper_trades` (scenario='SCALP_HLC') | HLC 3-Bar Scalp | Active |
| `paper_scalp` | HLC 3-Bar Scalp (EOD backtest) | Active |
| `qualified_trades` | CPR/QualificationEngine (legacy) | Retained for rollback |
| `daily_trade_locks` | CPR/QualificationEngine (legacy) | Retained for rollback |
| `paper_align` | CPR Trigger (legacy) | Retained for rollback |
| `paper_align_veto` | CPR Trigger (legacy) | Retained for rollback |
| `backtest_runs` | Mixed (all RUNNING, scenario_filter="ALL") | Not usable |
| `backtest_trades` | Empty (0 rows) | Not usable |

## 6. Cron and Systemd

| Mechanism | Schedule | Strategy | Status |
|-----------|----------|----------|--------|
| `tradingai-market-data.timer` | Every 1 min (changed from 5 min) | Infrastructure (data collection) | Active |
| `tradingai-api.service` | Always on | All (serves API) | Active |
| `tradingai-paper-scalp-live.service` | Always on | HLC 3-Bar Scalp | Inactive (no service file) |
| Cron: `tg_alerts.py --watch` | `* 9-15 * * 1-5` | HLC 3-Bar Scalp | Active |
| Cron: `tg_alerts.py --reconcile` | `10 9 * * 1-5` | HLC 3-Bar Scalp | Active |
| Cron: `paper_confluence.py --topup` | `45 15 * * 1-5` | CPR Trigger | Active (legacy) |

## 7. Frontend References

| File | Strategy Referenced | Status |
|------|-------------------|--------|
| `frontend/nifty.html` | HLC (via `/api/strategy/scalp`) | Active |
| `frontend/banknifty.html` | HLC (via `/api/strategy/scalp`) | Active |
| `frontend/scalp.html` | HLC 3-Bar Scalp | Active |
| `frontend/signals.html` | HLC (via TAIRULE) | Active |
| `frontend/signal-flow.html` | HLC (via TAIRULE) | Active |
| `frontend/backtest.html` | CPR Trigger + HLC | Active (both) |
| `frontend/paper.html` | Paper trades (mixed) | Active |
| `frontend/index.html` | HLC alerts | Active |
| `frontend/methodology.html` | HLC rules | Active |

## 8. Files That Cannot Be Retired (Shared or Unknown)

| File | Reason |
|------|--------|
| `app/research/cpr_trigger_engine.py` | Used by live engine for rollback; paper_trade engine monitor; paper_confluence |
| `app/research/cpr_strategy_engine.py` | Used by `/api/strategy/cpr` endpoint and intraday session |
| `app/research/backtest.py` | Used by replay.py and `/api/backtest/validation` |
| `app/core/qualification.py` | Used by live engine (constructor) even though not in default evaluate path |
| `app/strategies/engine.py` | Used by qualification.py (credit spread selection) |
| `app/research/scalp_alert_events.py` | Not wired into live runtime (P0.14, in-memory only) — safe to retire but low value |
| `app/research/live_paper_replay.py` | Replay helper — may be used by tests |
| `app/research/live_sim.py` | Simulation helper — may be used by tests |
| `app/research/replay.py` | Replay engine — used by `/api/research/replay` endpoint |
| `app/research/contrarian_analyzer.py` | Unknown dependencies — needs further inspection |
| `app/research/prevday_price_action_engine.py` | Unknown dependencies — needs further inspection |
| `app/research/cpr_gap_walkforward_engine.py` | Unknown dependencies — needs further inspection |

## 9. Proposed Deletion Manifest (Phase E)

| # | File | Strategy | Importers | Retire? | Evidence |
|---|------|----------|-----------|---------|----------|
| 1 | `app/research/backtest.py` | QualificationEngine (CPR) | `replay.py`, `live_sim.py` | NO — shared | Used by replay endpoint |
| 2 | `app/research/cpr_trigger_engine.py` | CPR Trigger | `live/engine.py`, `paper_trade/engine.py`, `paper_confluence.py`, `signal_articles.py` | NO — rollback + shared | Used by live engine (rollback), monitor, paper_confluence |
| 3 | `app/research/cpr_strategy_engine.py` | CPR Strategy | `app/api/app.py` (`/api/strategy/cpr`) | NO — API endpoint | Used by cpr_strategy endpoint |
| 4 | `app/research/cpr_gap_walkforward_engine.py` | CPR Walkforward | `app/api/app.py` (`/api/backtest/cpr-walkforward`) | NO — API endpoint | Used by cpr-walkforward endpoint |
| 5 | `app/research/contrarian_analyzer.py` | Contrarian | Unknown | NO — unknown deps | Need further inspection |
| 6 | `app/research/prevday_price_action_engine.py` | Prev-day PA | Unknown | NO — unknown deps | Need further inspection |
| 7 | `app/research/scalp_alert_events.py` | HLC Alert (P0.14) | Tests only | MAYBE — not wired | In-memory only, not in production |
| 8 | `app/research/live_paper_replay.py` | CPR Replay | Unknown | NO — unknown deps | Need further inspection |
| 9 | `app/research/live_sim.py` | CPR Sim | Unknown | NO — unknown deps | Need further inspection |
| 10 | `app/research/replay.py` | CPR Replay | `app/api/app.py` | NO — API endpoint | Used by `/api/research/replay` |
| 11 | `scripts/paper_confluence.py` | CPR Confluence | Cron (15:45) | NO — scheduled job | Active cron job |
| 12 | `scripts/engine_walkforward.py` | CPR Walkforward | Manual | NO — manual script | May be used by operators |
| 13 | `scripts/signal_articles.py` | CPR Signals | Cron (15:45) | NO — scheduled job | Active cron job |
| 14 | `scripts/shadow_friday.py` | CPR Shadow | Manual | NO — manual script | May be used by operators |
| 15 | `scripts/veto_paper_book.py` | CPR Veto | Cron (15:52) | NO — scheduled job | Active cron job |
| 16 | `scripts/veto_score.py` | CPR Veto | Cron (15:52) | NO — scheduled job | Active cron job |

**Conclusion:** Most CPR-related files cannot be retired because they are actively used by the live engine, API endpoints, cron jobs, or have unknown dependencies. Only `scalp_alert_events.py` is a candidate for retirement (P0.14, not wired into live runtime).

## 10. Blockers Preventing Safe Migration

| Blocker | Severity | Description |
|---------|----------|-------------|
| **Dirty working tree** | HIGH | 33+ modified files and many untracked files. Migration changes could conflict with uncommitted work. |
| **CPR engine drives live decisions** | HIGH | `app/live/engine.py` uses CPR trigger as default. HLC is display-only on `/api/decision`. Making HLC the default trade engine requires changing the live decision pipeline. |
| **No daily trade limit on scalp path** | MEDIUM | `paper_scalp_live.py` creates a trade for every signal. The correlated cap is bypassed for scalp. Need to add `MAX_TRADES_PER_DAY = 1` enforcement. |
| **Backtest vs live exit discrepancy** | MEDIUM | Backtest excludes entry candle from exit eval; live must protect during entry candle. Must document, not silently change. |
| **Two separate trade tables** | LOW | `paper_trades` (live) and `paper_scalp` (EOD backtest) are separate. Reconciliation is via `scalp_reconcile.py`. |
| **No systemd unit for paper_scalp_live.py** | MEDIUM | The scalp paper trading loop is not running as a service. It exists only as a script, not invoked by cron. |
| **Untracked frontend signal pages** | LOW | ~200 untracked `frontend/signals/plain/2026-*-*_H1_*.html` files exist but are not in Git. |

## 11. Recommendation

**Proceed with Phase 2 and 3, but with prerequisites:**

1. **Commit or stash** the dirty working tree before making consolidation changes.
2. **Add a systemd unit** for `scripts/paper_scalp_live.py` if live paper trading is desired.
3. **Add daily trade limit enforcement** (1 trade/day per instrument) to the scalp paper path.
4. **Document the backtest/live exit discrepancy** (entry candle exclusion) — do not silently change historical backtest results.
5. **Keep CPR trigger engine** as the live trade decision engine unless owner explicitly approves switching to HLC scalp for live execution.

The HLC engine is already the canonical signal specification for display, backtest, and paper trading APIs. What remains is unifying the daily-limit enforcement, entry-candle protection, and optionally wiring the alert pipeline — all without changing the HLC trading rules themselves.

**Do NOT retire:** CPR trigger engine (live decisions), `app/live/engine.py` (live decision pipeline), `app/paper_trade/engine.py` (shared infrastructure), `market_candles_5m` (shared data source), `app/core/qualification.py` (used by live engine constructor), `app/strategies/engine.py` (used by qualification).

## 12. Final Status

**PARTIAL — HLC ISOLATED; SOME RETIREMENTS DEFERRED**

The three-candle HLC implementation is already isolated in `app/research/scalp_engine.py` and `app/strategies/scalp.py`. Most unrelated strategy files cannot be safely retired because they are actively used by the live engine, API endpoints, cron jobs, or have unknown dependencies. Only `scalp_alert_events.py` (P0.14, not wired into live runtime) is a candidate for retirement.

**No production changes were made during this audit.** All findings are based on read-only inspection of deployed code, configuration, and database contents on the Oracle VM.
