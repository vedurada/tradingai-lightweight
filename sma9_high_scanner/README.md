# SMA9 HIGH Scanner - Locked, Independent Source

BUY-ONLY ATM NIFTY CE/PE paper scanner. Entry rule:

1. previous completed 5-minute candle **CLOSE > SMA9 HIGH** (computed from
   the 9 completed candles ending at that candle), and
2. live option **LTP > previous completed candle HIGH**.

The entry may fire at any 5-second poll while all conditions hold.
No broker order is ever placed.

- Strategy id: `sma9_high`
- Dashboard: `https://tradingai.in/live/sma9-high/`
- Database: `/opt/tradingai/database/sma9_high.db`
- Service: `tradingai-sma9-high-scanner.service` (user `sma9high`)
- Code lock: `sudo ops/verify_integrity.sh`

## Exit policies and polling (local change)

The live scanner polls on exact wall-clock 5-second boundaries (`:00`, `:05`,
`:10`, ...); there is no staggered poll offset. Each open position carries a
persisted `exit_policy`:

- `SL_TARGET_1_2` (all new entries): fixed 5% initial stop (`initial_stop`,
  never ratcheted) and `target_price = entry + 2 × (entry - initial_stop)`.
  Only `STOP_LOSS_INITIAL` and `TARGET_1_2` exits apply, filled at the stored
  levels: no trailing stops, EOD flatten, restart same-candle recovery or
  stale-recovery exits.
- `LEGACY` (default for all pre-existing rows): unchanged prior trail/stop
  and restart entry-candle-close recovery.

Entry gates are unchanged (A: previous close > SMA9 HIGH, C: forming open >
SMA9 HIGH, B: LTP > previous candle HIGH, with `condition_c`/`prev_high`
preserved). The new fields are stored on `sma9_high_open_positions` with safe
migrations and reported in per-option status. Local source change only: no
deploy, service restart or order placement.
