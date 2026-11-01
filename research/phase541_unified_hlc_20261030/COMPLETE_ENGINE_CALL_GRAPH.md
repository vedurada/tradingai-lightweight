# Phase 5.41 — Complete Engine Call Graph

## Verified Call Paths

### Canonical HLC Signal Generation
- Canonical implementation: `/opt/tradingai/app/research/scalp_engine.py`
- Signal scan: `scalp_engine._scan_signals(candles)` (3-bar HLC alignment)
- Live signal resolution: `scalp_engine._live_signal(candles, idx, direction, ...)`
- Trade construction: `scalp_engine._trade_for(candles, idx, direction)`
- Backtest: `scalp_engine.run_range` / `run_opens_range`

### Live Signal Path
- `/opt/tradingai/app/live/engine.py::_hlc_book_signal(instrument, candles, completed, ...)`
- Unified rulebook gate: `LiveEngine.evaluate` → `_hlc_only_mode()` → `_hlc_book_signal`.
- Feature flag: `HLC_ONLY_MODE` (default = HLC; fail-safe to HLC).

### Paper Trading Path
- `/opt/tradingai/app/paper_trade/engine.py` → scenario `SCALP_HLC`; exits via scalp rules (signal-candle-extreme stop, 1.5R target, STOP-first tie-break).

### Backtest Path
- `/opt/tradingai/app/research/scalp_engine.py::run_range` / `run_opens_range`.
- API: `/opt/tradingai/app/api/app.py` → `/api/backtest/cpr-triggers`, `/api/backtest/<run_id>`, etc.

### Telegram Alert Path
- `/opt/tradingai/scripts/tg_alerts.py` → from `/api/strategy/scalp` (canonical HLC) or persisted signals (scenario `SCALP_HLC`).

### API and Frontend Path
- `/opt/tradingai/app/api/app.py` → `/api/strategy/scalp` returns HLC signal (`strategy='SCALP_HLC_3BAR'`).
- Frontend: `/opt/tradingai/frontend/*.html` consume API endpoints.

## Consumer Classification (verified via source inspection)
- Live: canonical (`_hlc_book_signal`).
- Paper: canonical adapter with `SCALP_HLC` scenario.
- Backtest: canonical (`run_range`/`run_opens_range`).
- Telegram: canonical via API/persisted signal.
- API: canonical HLC for scalp signals (`strategy='SCALP_HLC_3BAR'`).

## Database Tables (verified)
- backtest_runs: 2293; backtest_decisions: 0; backtest_trades: 0; backtest_outcomes: 2272.
- scalp_signals: 29; paper_trades: 94; market_candles_5m: 16936; paper_trade_events: 33; trade_journal: 246.

## Status
AUDIT COMPLETE (call graph traced; Stage 1 inventory established)
