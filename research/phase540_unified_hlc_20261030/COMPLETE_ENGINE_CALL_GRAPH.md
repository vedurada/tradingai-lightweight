# Phase 5.40 — Complete Engine Call Graph

## Verified Paths

### Live Signal Generation
`/opt/tradingai/app/live/engine.py` -> `_hlc_book_signal(instrument, candles, completed, ...)`
-> `/opt/tradingai/app/research/scalp_engine.py::_scan_signals(feed)`
-> `/opt/tradingai/app/research/scalp_engine.py::_live_signal(feed, idx, direction, ...)`

### Paper Trading
`/opt/tradingai/app/paper_trade/engine.py` -> consumes canonical HLC signal via adapter.

### Historical Backtest
`/opt/tradingai/app/research/scalp_engine.py::run_range / run_opens_range`

### Telegram Alerts
`/opt/tradingai/scripts/tg_alerts.py` -> persisted signal records.

### API
`/opt/tradingai/app/api/app.py` -> signal endpoints.

### Frontend
`/opt/tradingai/frontend/` -> consumes API-backed signal data.

## Status
AUDIT IN PROGRESS
