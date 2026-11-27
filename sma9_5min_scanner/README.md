# SMA9 5min Scanner - Local 5s Polling Variant

BUY-ONLY ATM NIFTY CE/PE paper scanner. Entry gates are unchanged: previous
completed 5-minute candle CLOSE > SMA9 and the forming candle OPEN > SMA9;
LTP > SMA9 remains informational only.

- Strategy id: `sma9_5min`
- Database: `/opt/tradingai/database/sma9_5min.db`
- Live entrypoint: `app/live_sma9_5min_scanner.py`
- Tests: `tests/`

## Polling and exit policies

The scanner polls on exact wall-clock 5-second boundaries (`:00`, `:05`,
`:10`, ...). The former 300-second poll, `POLL_OFFSET_SEC`, `next_poll_time()`
and `poll_alignment` status field are gone; `poll_seconds` remains `5`.

Each open position carries a persisted `exit_policy`:

- `SL_TARGET_1_2` (all new entries): fixed 5% initial stop (`initial_stop`,
  never ratcheted) and `target_price = entry + 2 × (entry - initial_stop)`.
  The only exits are `STOP_LOSS_INITIAL` and `TARGET_1_2`, filled at the
  stored levels. No trailing stops, EOD flatten, restart same-candle recovery
  or stale-recovery exits.
- `LEGACY` (default for all pre-existing rows): the prior +5 trail/+2 lock,
  5% stop and restart entry-candle-close recovery are unchanged.

The fields are stored on `sma9_5min_open_positions` with safe migrations,
included in `Position.as_dict()`/`from_dict()` and per-option status. This is
a local source change only: no deploy, service restart or order placement.
