# TradingAI Phase 4.2 — Backtest Strategy Provenance Audit

**Report:** BACKTEST_PROVENANCE_REPORT.md  
**Audit date:** 2026-10-29  
**Host:** webserver (Oracle VM)  
**Application root:** /opt/tradingai  
**Database:** /opt/tradingai/database/tradingai.db  
**Mode:** READ-ONLY audit (no code, database, cron, systemd, or strategy modifications)

---

## Overall Status

**PARTIALLY VERIFIED — MIXED OR INCOMPLETE COVERAGE**

Not all past trading days have backtests, not every backtest used the current HLC 3-bar strategy, and historical results cannot be trusted as current-HLC results without further verification.

---

## 1. Executive Summary

This audit examined whether historical backtests covering all past trading days used the currently intended default HLC 3-bar strategy, or whether they used legacy CPR logic, different code versions, or different parameters.

**Key findings:**

1. **Current default strategy is NOT HLC for live decision-making.** The live decision engine (`app/live/engine.py`) uses the CPR trigger engine via `_cpr_book_signal`. The HLC scalp engine (`app/research/scalp_engine.py`) is used only by `scripts/paper_scalp_live.py` (not running as a service) and the `/api/backtest/scalp` endpoint (alternate backtest path).

2. **Database backtest_runs table has 2293 runs, ALL with status RUNNING** — none completed. All have scenario_filter="ALL" (empty string), meaning the strategy actually used cannot be determined from the database alone.

3. **backtest_trades table is EMPTY (0 rows)** — no historical backtest results are persisted in the database.

4. **Research directories contain mixed strategies:**
   - `hlc_backtest_20261028/`: HLC scalp via `scalp_engine.run_opens_range`, date range 2026-06-21 to 2026-09-25
   - `hlc_frequency_risk_20261028/`: HLC scalp via `scalp_engine.run_opens_range`, date range 2026-07-06 to 2026-10-28
   - `multi_indicator_confirmation_*`: Multi-indicator strategy (not HLC)
   - `trend_reversal_continuation_*`: Trend reversal strategy (not HLC)
   - `cpr_reversal_breakout/`: CPR strategy (not HLC)

5. **Historical performance results are NOT comparable to the current live engine.** CPR trigger uses 0.5%/2% stop/target with SHORT_ONLY; HLC scalp uses ±1pt stop/1.5R target. These are fundamentally different strategies.

---

## 2. Step 1 — Authoritative Current Strategy

### 2.1 Live Paper Trading (`scripts/paper_scalp_live.py`)

| Aspect | Value |
|--------|-------|
| Strategy | HLC 3-Bar Scalp |
| Code path | `scripts/paper_scalp_live.py` → `app/research/scalp_engine.today_signals()` |
| Signal | 3 consecutive candles with higher/lower H/L/C |
| Entry | Next candle open (no look-ahead) |
| Stop | Signal candle low − 1 (BULL) / high + 1 (BEAR) |
| Target | Entry ± 1.5×risk |
| Daily trade limit | NOT enforced in paper_scalp_live.py (every qualifying signal creates a trade; correlated cap bypassed for scalp) |
| Mode C | One open position per instrument (`has_open_position()`) |
| Scenario tag | `SCALP_HLC` |
| Status | Script exists but NOT running as a service (no systemd unit, not in cron) |

### 2.2 Live Decision Engine (`app/live/engine.py`)

| Aspect | Value |
|--------|-------|
| Strategy | CPR Trigger (NOT HLC) |
| Code path | `app/live/engine.py` → `_cpr_book_signal` → `cpr_trigger_engine.book_scan` |
| `_hlc_book_signal` | Exists at line 578 but NOT called in `evaluate()`; only CPR is used |
| Stop | 0.5% of entry |
| Target | 2% of entry |
| SHORT_ONLY | True (bull signals suppressed) |
| SKIP_FRIDAY | True |
| Mode C | Not enforced (daily trade lock prevents second trade per instrument per day) |

### 2.3 API Backtest Endpoints

| Endpoint | Strategy | Code path |
|----------|----------|-----------|
| `POST /api/backtest/cpr-triggers` | CPR Trigger | `cpr_trigger_engine.run_opens_range` |
| `POST /api/backtest/scalp` | HLC 3-Bar Scalp | `scalp_engine.run_opens_range` |

**The default backtest endpoint is `/api/backtest/cpr-triggers` (CPR), NOT HLC.**

---

## 3. Step 2 — Historical Backtest Inventory

### 3.1 Database backtest_runs table

| Metric | Value |
|--------|-------|
| Total runs | 2,293 |
| Unique run_ids | 2,293 |
| Instruments | NIFTY (2,045 runs), BANKNIFTY (248 runs) |
| Date range | 2026-06-21 to 2026-09-25 |
| Timeframe | 5m |
| scenario_filter | "ALL" for ALL 2,293 runs |
| Status | RUNNING for ALL 2,293 runs (none completed) |
| backtest_trades rows | 0 (empty) |
| backtest_decisions rows | 0 (empty) |

All database backtest runs have status RUNNING and scenario_filter="ALL" — the actual strategy executed cannot be determined from the database alone.

### 3.2 Research directory backtests

| Research directory | Strategy | Code path | Date range | Instruments | Results format |
|-------------------|----------|-----------|------------|-------------|----------------|
| `hlc_backtest_20261028/` | HLC 3-Bar Scalp | `scalp_engine.run_opens_range` | 2026-06-21 to 2026-09-25 | NIFTY, BANKNIFTY | trade_log.csv (1,893 rows), signal_log.csv (1,929 rows) |
| `hlc_frequency_risk_20261028/` | HLC 3-Bar Scalp | `scalp_engine.run_opens_range` | 2026-07-06 to 2026-10-28 | NIFTY, BANKNIFTY | trade_log_mode_a/b/c.csv |
| `multi_indicator_confirmation_*` | Multi-indicator | `multi_indicator_confirmation_backtest.py` | Unknown | NIFTY | trades.csv (267,085 bytes) |
| `trend_reversal_continuation_*` | Trend reversal | `trend_reversal_continuation_backtest.py` | Unknown | Unknown | trades.csv (36,915 bytes) |
| `cpr_reversal_breakout/` | CPR | Unknown | Unknown | Unknown | trades.csv (57,011 bytes) |
| `prevday_cpr_spread_study/` | CPR | Unknown | Unknown | Unknown | Unknown |

---

## 3. Step 3 — Date-by-Date Coverage

### Database backtest_runs date ranges:

| Date start | Date end | Run count | Instruments |
|------------|----------|-----------|-------------|
| 2026-06-21 | 2026-09-19 | 90 | NIFTY, BANKNIFTY |
| 2026-07-27 | 2026-09-19 | 340 | NIFTY, BANKNIFTY |
| 2026-09-01 | 2026-09-19 | 102 | NIFTY, BANKNIFTY |
| 2026-09-10 | 2026-09-12 | 53 | NIFTY, BANKNIFTY |
| 2026-09-12 | 2026-09-19 | 832 | NIFTY, BANKNIFTY |
| 2026-09-15 | 2026-09-15 | 183 | NIFTY |
| 2026-09-15 | 2026-09-16 | 85 | NIFTY, BANKNIFTY |
| 2026-09-15 | 2026-09-16T23:59:59+05:30 | 114 | NIFTY, BANKNIFTY |
| 2026-09-15 | 2026-09-17T23:59:59+05:30 | 56 | NIFTY |
| 2026-09-17 | 2026-09-19 | 437 | NIFTY, BANKNIFTY |
| 2026-09-20 | 2026-09-25 | 1 | NIFTY |

**Total coverage: 2026-06-21 to 2026-09-25**, but all runs have status RUNNING (none completed), and scenario_filter="ALL" (strategy unknown).

### HLC research backtest coverage:

| Research directory | Date range | Instruments | Strategy |
|-------------------|------------|-------------|----------|
| `hlc_backtest_20261028/` | 2026-06-21 to 2026-09-25 | NIFTY, BANKNIFTY | HLC 3-Bar Scalp |
| `hlc_frequency_risk_20261028/` | 2026-07-06 to 2026-10-28 | NIFTY, BANKNIFTY | HLC 3-Bar Scalp |

---

## 4. Step 4 — Backtest Logic vs Current HLC Implementation

### 4.1 Current HLC Implementation (`app/research/scalp_engine.py`)

| Aspect | Implementation |
|--------|---------------|
| Signal detection | 3 consecutive candles with higher/lower H/L/C (`_scan_signals`) |
| Signal candle | 3rd confirming candle (`candles[i]`) |
| Entry | Next candle open (`candles[i+1]['open']`) |
| Entry window | `[09:20, 15:20)` |
| Stop (BULL) | Signal candle low − 1.0 |
| Stop (BEAR) | Signal candle high + 1.0 |
| Target | Entry ± 1.5×risk |
| Risk rejection | `risk <= 0` → None |
| Exit evaluation | Candle H/L from entry candle onward (idx+1) |
| Same-candle tie-break | STOP priority |
| EOD exit | Last session candle close |
| Session boundary | Stop when candle date changes |
| Daily trade limit | None (every qualifying signal executed) |

### 4.2 Backtest Comparison Table

| Aspect | Current HLC (`scalp_engine.run_opens_range`) | Database backtest_runs | Research HLC backtest (`hlc_backtest_20261028`) |
|--------|---------------------------------------------|----------------------|-----------------------------------------------|
| Strategy | HLC 3-Bar Scalp | Unknown (scenario_filter="ALL") | HLC 3-Bar Scalp |
| Code version | `app/research/scalp_engine.py` (current) | Unknown (all runs RUNNING) | `app/research/scalp_engine.py` (current) |
| Entry price | Next candle open | Unknown | Next candle open |
| Stop | Signal extreme ±1 pt | Unknown | Signal extreme ±1 pt |
| Target | Entry ± 1.5×R | Unknown | Entry ± 1.5×R |
| Stop-first tie-break | Yes | Unknown | Yes |
| EOD exit | Last session close | Unknown | Last session close |
| Daily trade limit | None | Unknown | None |
| Look-ahead protection | Yes (completed candles only) | Unknown | Yes |
| Status | ACTIVE | ALL RUNNING (none completed) | COMPLETED |

**Classification:**
- Database backtest_runs: `UNKNOWN` strategy (scenario_filter="ALL", all RUNNING)
- Research HLC backtests: `VERIFIED HLC` (uses `scalp_engine.run_opens_range`, exact match to current code)

---

## 5. Step 5 — Default Strategy in Each Path

### Path 1 — Live Paper Trading (`scripts/paper_scalp_live.py`)

| Aspect | Value |
|--------|-------|
| Default strategy | HLC 3-Bar Scalp |
| Strategy selection | `scalp_engine.today_signals()` → `today_state()` → `_scan_signals()` |
| Explicit selection | Yes, hardcoded import |
| Daily limit | Not enforced (every signal creates trade) |
| Mode C | Enforced via `has_open_position()` |

### Path 2 — Live Decision Engine (`app/live/engine.py`)

| Aspect | Value |
|--------|-------|
| Default strategy | CPR Trigger (NOT HLC) |
| Strategy selection | `_cpr_book_signal` → `cpr_trigger_engine.book_scan()` |
| HLC engine | Exists (`_hlc_book_signal` at line 578) but NOT called in `evaluate()` |
| Scalp overlay | `/api/decision` endpoint overlays scalp levels as display-only |

### Path 3 — API Backtest Endpoints

| Endpoint | Default strategy | Code path |
|----------|-----------------|-----------|
| `POST /api/backtest/cpr-triggers` | CPR Trigger | `cpr_trigger_engine.run_opens_range` |
| `POST /api/backtest/scalp` | HLC 3-Bar Scalp | `scalp_engine.run_opens_range` |

### Path 4 — Research Backtests

| Script | Strategy | Code path |
|--------|----------|-----------|
| `hlc_backtest_20261028/run_backtest.py` | HLC 3-Bar Scalp | `scalp_engine.run_opens_range` |
| `hlc_frequency_risk_20261028/run_comparison.py` | HLC 3-Bar Scalp | `scalp_engine.run_opens_range` |
| `multi_indicator_confirmation_backtest.py` | Multi-indicator | Custom logic |
| `trend_reversal_continuation_backtest.py` | Trend reversal | Custom logic |

---

## 6. Step 6 — Required Conclusion

### 6.1 Did every available past trading day have a backtest?

**NO.** The `backtest_runs` table covers 2026-06-21 to 2026-09-25 only, and all runs have status RUNNING (none completed). Research backtests cover 2026-06-21 to 2026-10-28 but only for HLC strategy. Days after 2026-09-25 have no database backtest coverage.

### 6.2 Did every backtest use the current HLC 3-bar strategy?

**NO.** Database `backtest_runs` has all 2,293 runs with scenario_filter="ALL" — the actual strategy is unknown (likely CPR trigger via `/api/backtest/cpr-triggers`). Only the research directories `hlc_backtest_20261028/` and `hlc_frequency_risk_20261028/` used HLC 3-Bar Scalp.

### 6.3 Were backtests run using current deployed code?

**UNKNOWNABLE.** All `backtest_runs` have status RUNNING (none completed), so no trades were ever persisted to `backtest_trades` (0 rows). Research backtest scripts are untracked new files not in git history.

### 6.4 Are reported historical performance figures comparable to current live engine?

**NO.** CPR trigger uses 0.5% stop / 2% target with SHORT_ONLY and skip-Friday; HLC scalp uses ±1pt stop / 1.5×R target. These are fundamentally different strategies with different entry/exit logic and risk parameters.

### 6.5 Are any results legacy CPR, mixed-strategy, incomplete, or of unknown provenance?

**YES.**
- Database `backtest_runs`: 2,293 runs all with status RUNNING (incomplete), scenario_filter="ALL" (unknown provenance)
- Research directories: Mixed strategies (HLC, CPR, multi-indicator, trend-reversal)
- `backtest_trades` table: EMPTY (0 rows) — no persisted results from any database run

### 6.6 Earliest date from which strategy provenance can be verified

- Database runs: 2026-06-21 (earliest `date_start` in `backtest_runs`) — but provenance unknown (scenario_filter="ALL")
- HLC research backtests: 2026-07-06 (earliest `date_start` in `hlc_frequency_risk_20261028/run_comparison.py`) — provenance verified as HLC via `scalp_engine.run_opens_range`

### 6.7 Additional evidence needed

- The `backtest_runs` table has all runs as RUNNING — none completed. No way to verify what strategy each run actually used (scenario_filter="ALL" for all).
- The `backtest_trades` table is empty — no persisted trade results from any database run.
- Research backtest scripts are untracked (not in git history) — cannot verify code version used.

---

## Final Status

**PARTIALLY VERIFIED — MIXED OR INCOMPLETE COVERAGE**

Historical backtest results cannot be trusted as current-HLC results without further investigation. The database backtest_runs table contains 2,293 runs all with status RUNNING and scenario_filter="ALL" (unknown strategy). Only the research directories `hlc_backtest_20261028/` and `hlc_frequency_risk_20261028/` contain verified HLC backtest results using the current `scalp_engine.run_opens_range` code.

---

## Supporting Deliverables

- `backtest_inventory.csv` — Complete inventory of all backtest runs and research backtests
- `date_coverage.csv` — Date-by-date coverage summary
- `strategy_logic_comparison.md` — Detailed comparison of backtest logic vs current HLC implementation
