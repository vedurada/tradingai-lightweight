# Phase 5.22 — Production State Before/After

## Before

- Gunicorn PIDs: 802784, 824977, 829484
- DB integrity: ok
- paper_trades: 94
- scalp_signals: 29
- paper_scalp: 217
- market_candles_5m: 16,936
- Service: active (running)
- HLC_ONLY_MODE: not set

## After

- Gunicorn PIDs: 802784, 824977, 829484 (unchanged)
- DB integrity: ok (unchanged)
- paper_trades: 94 (unchanged)
- scalp_signals: 29 (unchanged)
- paper_scalp: 217 (unchanged)
- market_candles_5m: 16,936 (unchanged)
- Service: active (running, not restarted)
- HLC_ONLY_MODE: staged in service file (not yet active in running process)

## Changes Made

- app/live/engine.py: default changed from True to False
- /etc/systemd/system/tradingai-api.service: added Environment=HLC_ONLY_MODE=true

## Changes NOT Made

- No service restart or reload
- No database writes
- No configuration activation
- No production alerts or trades
