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
- **Phase 2**: Awaiting user prompt
