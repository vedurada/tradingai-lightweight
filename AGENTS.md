# TradingAI.in — OpenCode Agent Instructions

Read before every phase. Provides project context, constraints, and operational guidance.

---

## Project Overview

TradingAI.in — AI-Assisted Market Intelligence Platform for Indian equities (NIFTY, BANKNIFTY, FINNIFTY, SENSEX). Full-stack trading intelligence: market data, AI outlook, options intelligence, strategy generation, backtesting, portfolio, and educational content.

## Repository

- **Workspace**: `/Users/satya/remove_workspace/tradingai.in_live_VM/`
- **VM Repo**: `/opt/tradingai/` (129.159.224.81)
- **Branch**: `tradingai.in_live_VM` (workspace), `main` (VM, 15 commits ahead of origin)
- **Default branch for changes**: `tradingai.in_live_VM` — commit and push here before syncing to VM via `deploy-vm.sh`

## Frozen Model Files (DO NOT MODIFY)

These files are model-layer boundary. Any change to them requires a new Phase decision:

- `backend/regime.py`
- `backend/strategies.py`
- `backend/indicators.py`
- `backend/options.py`
- `backend/outlook.py`
- `backend/scenarios.py`
- `backend/ai_outlook.py`
- `backend/backtest.py`

## Key Constraints

1. **Model boundary**: Never modify frozen model files. Pre-commit hook enforces this.
2. **Observational monitoring**: Monitoring must not modify strategy, regime, or confidence values.
3. **Immutability of AI predictions**: Once an AI outlook is generated, it must not be overwritten.
4. **No bare except**: Forbidden in non-test code. Pre-commit hook checks.
5. **No print in non-test code**: Forbidden. Pre-commit hook checks.
6. **Error response schema**: All errors must use `error_response()` with `code`, `message`, `timestamp` fields.
7. **CORS**: Production origins only — `https://tradingai.in`, `https://www.tradingai.in`.
8. **Debug mode**: Must be False in production.
9. **Data completeness**: All data-dependent endpoints must return `data_completeness` flags, even when data is unavailable (use `DATA UNAVAILABLE` quality level, not crash).
10. **Portfolio isolation**: One API key cannot access another user's portfolio.

## VM Specifications

- **Server**: Ubuntu 22.04, 2 CPU, 956MB RAM (564MB available), 45GB disk, Swap 2GB
- **API**: Gunicorn (3 workers) on 127.0.0.1:8000, systemd managed
- **Nginx**: Serves from `/var/www/tradingai.in/html/`, reverse proxy to API on :8000
- **DB**: SQLite at `/opt/tradingai/database/tradingai.db` (WAL mode, busy_timeout=10000)
- **Logs**: `/opt/tradingai/logs/` (must exist)
- **GROQ API Key**: `/etc/tradingai/groq.env` (must be mode 600)

## Current DB State (as of 2026-09-15)

DB populated via `data_fetcher_db.py` (ran during Phase 0 audit). 19 of 41 tables have data. 23 tables still empty (non-critical — handled by cron backfill).

- `/api/price/NIFTY` → 200, LIVE, price ~23118
- `/api/price/BANKNIFTY` → 200, LIVE
- `/api/price/FINNIFTY` → 200, LIVE
- `/api/price/SENSEX` → 200, LIVE
- `/api/vix` → 200, LIVE, ~13.27
- `/api/NIFTY` → 200, data_completeness all true
- `/api/health` → 200, status ok, ready true
- `/api/metrics` → 200, process-local
- `/api/market` → 200, data_quality GOOD

**If DB becomes empty again**: Run on VM:
```bash
cd /opt/tradingai/backend
SKIP_LLM=1 python3 data_fetcher_db.py
```

**If you need more historical data**: Run on VM:
```bash
cd /opt/tradingai/backend
python3 backfill_yearly.py
python3 backfill_indices_10y.py --period 10y
python3 backfill_outlooks.py --days 3650 --overwrite
```

## Testing

- **Framework**: pytest
- **Total tests**: ~921 across 34+ test files (856 original + 65 Phase 1)
- **Test directories**: `tests/`
- **Run all**: `python3 -m pytest tests/ -q`
- **Run specific**: `python3 -m pytest tests/test_options.py -v`
- **14 Phase 3 tests**: `python3 -m pytest tests/test_phase3.py -v`
- **18 Phase 4 tests**: `python3 -m pytest tests/test_phase4.py -v`
- **17 Phase 5 tests**: `python3 -m pytest tests/test_phase5.py -v`
- **13 Phase 6 tests**: `python3 -m pytest tests/test_phase6.py -v`
- **20 Phase 7 tests**: `python3 -m pytest tests/test_phase7.py -v`
- **6 known failures** (data-dependent, DB empty): see `docs/AUDIT_REPORT.md`

## Deployment

- **Script**: `deploy-vm.sh` (must run from workspace with SSH key)
- **Steps**: rsync → install deps → sync webroot → init DB + fetch data → systemd restart → health gate → prerender snapshot → nginx config re-assert
- **Rollback**: `ops/rollback.sh` (git checkout, reinstall, restart, health check)

## Architecture Notes

- Frontend: Vanilla HTML/CSS/JS, no framework. SPA-style with `index.html` as entry point.
- API: Flask via `backend/api_server.py`, served by gunicorn.
- AI Engine: LLM-based (Groq) for outlook generation, frozen model files for regime/strategy/indicators.
- Data: SQLite for storage, yfinance for price fallback, NSE APIs for Indian market data.
- Learning Architecture (Phase 7+): User feedback → Trade Journal → Personal Trading Intelligence (separate from TradingAI Market Intelligence).

## Phase Status

- **Phase 0**: ✅ COMPLETE — Audit done, fixes applied, 856 tests passing
- **Phase 1**: ✅ COMPLETE — Production foundation, 921/921 tests passing
- **Phase 2**: ✅ COMPLETE — Market intelligence engine, 983/983 tests passing
- **Phase 3**: ✅ COMPLETE — Options Intelligence Engine, 997/997 tests passing
- **Phase 4**: ✅ COMPLETE — Intraday AI Market Outlook & Trade Setup Engine, 1012/1012 tests passing
- **Phase 5**: ✅ COMPLETE — Historical AI Replay, 1032/1032 tests passing
- **Phase 6**: ✅ COMPLETE — Live Intraday + Price-Tick Experience, 1045/1045 tests passing
- **Phase 7**: In Progress — Deterministic Strategy Backtesting, 1065/1065 tests passing

## Phase 5 Components

- `backend/replay_engine.py` — Timestamp-by-timestamp replay with strict no-lookahead
- `replay_day()` — Takes 5m candles + prev close → list of ReplaySnapshot at each step
- `ReplaySnapshot` — Immutable snapshot: timestamp, market_state, gap, trade_setup, what_ai_knew, what_ai_did_not_know
- `backend/api_server.py` — Added `/api/replay/<symbol>/<date>` endpoint
- `history/replay.html` — Daily replay page with timeline
- Strict no-lookahead: at each timestamp, only data ≤ that timestamp is used
- Every snapshot preserves: timestamp, indicators version, data quality, evidence

## Phase 6 Components

- `backend/quote_tracker.py` — Quote tracking: per-quote metadata + aggregate cadence
- `QuoteTracker.receive()` — Records quote with: previous_price, price_change, update_interval_ms, quote_age_ms, source
- `QuoteTracker.get_telemetry()` — Aggregate: avg/median/min/max interval, quote age, source
- `backend/api_server.py` — Added `/api/quote/track/<symbol>` and `/api/quote/telemetry/<symbol>` endpoints
- `trade.html` — Live prices with blink-on-change (not timer), LIVE/STALE indicator, quote age, mobile-first
- Blink rule: UP when price increases, DOWN when decreases, no blink when unchanged
- Respects prefers-reduced-motion, animates only changed price

- `backend/options_state.py` — OptionsState object (immutable, per-symbol)
- `backend/options_normalizer.py` — Chain processor using frozen OptionsEngine
- `backend/api_server.py` — Added `/api/options/state/<symbol>` endpoint
- `options-mobile.html` — Mobile-first options UI template
- FINNIFTY: Scoped to historical data only, NOT available as live product (404 for `/api/options/state/FINNIFTY`, 404 for `/api/trade-setup/FINNIFTY`)

## Phase 4 Architecture

Trade lifecycle: DETECTED → TRIGGER → CONFIRMATION → ENTRY_WINDOW → ACTIVE → COMPLETE

Inputs: Market State + Gap Analysis + Options State → TradeSetup

- `detect_trade_setup()` returns TradeSetup with 6 lifecycle stages
- Each stage has: status, timestamp, evidence, uncertainty, levels, reason
- Trade readiness: GO (entry window active), WAIT (conditions forming), NO_SETUP (no trade warranted)
- Evidence-based, never guarantees outcomes
- AI explicitly returns WAIT when conditions aren't ready

## Phase 7 Components

Deterministic Strategy Backtesting Engine — Entry/Exit simulator, cost model, performance engine, AI separation.

### One engine, three environments
- LIVE uses `TradeSetup` from Phase 4
- REPLAY uses `TradeSetup` from Phase 4 + Phase 5 snapshot format
- BACKTEST uses `TradeSetup` from Phase 4 + Phase 5 snapshot format + Entry/Exit simulation

### Core Components
- **Entry/Exit Simulator**: Entry on GO + ENTRY_WINDOW ACTIVE + valid levels; exit on target hit, invalidation hit, or EOD close. Uses closing prices (no intra-day ticks).
- **Cost Model**: Brokerage (₹20/side), slippage (0.5 bps), exchange fee (0.03%), GST (18% on brokerage+slippage), stamp charge (0.003%). No negative costs.
- **Trade Record**: Immutable namedtuple with 22+ fields including costs, P&L, R-multiples.
- **Performance Engine**: Win rate, profit factor, net P&L, max drawdown, equity curve, R-multiples (best/worst/avg), time-of-day patterns.

### Key Design Decisions
- AI NEVER calculates backtest numbers (deterministic engine computes P&L; AI can only explain results)
- `total_trades` includes all trades; `completed_trades` filters STILL_OPEN
- Reuses Phase 4 trade setup data, Phase 5 snapshot format
- Strict no-lookahead inherited from Phase 5
