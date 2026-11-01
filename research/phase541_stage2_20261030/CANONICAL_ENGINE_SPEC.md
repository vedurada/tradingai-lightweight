# Phase 5.41 Stage 2 — Canonical HLC Engine Spec

## Canonical Implementation
- `/opt/tradingai/app/research/scalp_engine.py`

## Functions
- `_scan_signals(candles)`: 3-bar HLC alignment (consecutive candles with higher/lower H/L/C).
- `_live_signal(candles, idx, direction, inst, day_iso, variant)`: resolves live signal.
- `_trade_for(candles, idx, direction)`: constructs trade (stop/target/risk, forward scan exit, EOD).
- `run_range(instrument, date_start, date_end)`: backtest over range.
- `run_opens_range(instrument, date_start, date_end, variant, stop_pct, target_pct)`: backtest opens.

## Signal Identity
- strategy: 'Scalp HLC 3-bar'; scenario: 'SCALP_HLC'; level H1_UP/H1_DOWN.

## Status
AUDIT COMPLETE
