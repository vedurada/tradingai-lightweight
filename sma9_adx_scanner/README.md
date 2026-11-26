# `sma9_adx` — isolated paper scanner source tree

Paper-only NIFTY ATM CE/PE scanner. No broker write path: every fill is a
simulated BUY recorded in SQLite.

## Rules

- **Entry (all required):** previous completed option 5m candle close > SMA9
  **and** Wilder ADX(14) > 30 **and** +DI > -DI on completed option 5m candles.
  The forming bar is never used. CE and PE are evaluated independently.
- **Exit:** initial stop = entry - 5%; once the premium rises, the stop ratchets
  to HWM - 5% and never ratchets down. No candle-close or time-based exit.

## Files

| Path | Purpose |
|---|---|
| `app/sma9_adx_engine.py` | Pure strategy engine (ADX, evaluation, stop/trail state machine) |
| `app/live_sma9_adx_scanner.py` | 5-second live runner + SQLite state |
| `ops/tradingai-sma9-adx-scanner.service` | systemd unit (user `sma9adx`) |
| `tests/test_sma9_adx_engine.py` | Offline engine checks (no network/DB) |

## Runtime

- DB: `/opt/tradingai/database/sma9_adx.db` (`SMA9_ADX_DB_PATH`)
- Tables: `sma9_adx_trades`, `sma9_adx_open_positions`, `sma9_adx_scan_state`
- API: `/api/sma9-adx/*` (read-only)
- Dashboard: `/live/sma9-adx/`
- Log: `/opt/tradingai/logs/live_sma9_adx_scanner.log`

See `docs/scanners/sma9_adx.md` and `SCANNERS.md` §5.8 for full details.
