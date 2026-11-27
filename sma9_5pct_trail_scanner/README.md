# `sma9_5pct_trail` scanner

Full standalone identity for the renamed SMA9 Trail scanner. The retired
`sma9_trail` service remains disabled and its dashboard/DB are left untouched
for reference.

## Identity

| Item | Value |
|---|---|
| Strategy id | `sma9_5pct_trail` |
| Strategy type | `SMA9_5PCT_TRAIL_BUY_ONLY` |
| Strategy version | `3.0.0` |
| Public slug | `sma9-5pct-trail` |
| Dashboard | `/live/sma9-5pct-trail/` |
| Launcher deep link | `/live/scalp/?s=sma9-5pct-trail` (`?s=sma9-trail` aliases here) |
| API | `/api/sma9-5pct-trail/*` |
| DB | `/opt/tradingai/database/sma9_5pct_trail.db` |
| Tables | `sma9_5pct_trail_trades`, `sma9_5pct_trail_open_positions`, `sma9_5pct_trail_scan_state` |
| Service | `tradingai-sma9-5pct-trail-scanner.service` |
| User | `sma95pcttrail` |
| Code | `/opt/tradingai/sma9_5pct_trail_scanner/` |
| Python path | `/opt/tradingai/sma9_5pct_trail_lib` |
| Broker alias | `sma9_5pct_trail` (mStock) |
| Polling | Exact wall-clock 5-second boundaries (`:00`, `:05`, ...); no offset |

## Rules

Entry (self-contained in the runner):

- Previous completed 5-minute option-premium close > SMA9.
- Current forming 5-minute option-premium open > SMA9.
- Wilder `DI+ > DI-` on the same completed 5-minute premium candles. The forming
  candle is excluded from both SMA9 and DI; entries are skipped until DI(14) is
  available (at least 28 completed bars). This is an additional AND gate and
  does not change the two SMA conditions.
- ATM CE and PE are evaluated independently; long only; at most one position
  per option.

Exits are selected by the persisted `exit_policy` on each open position:

- `LEGACY` (all pre-existing rows, the default for restored old rows):
  1. `STOP_LOSS_5PCT`: LTP <= `round(entry x 0.95, 2)`. Fill is at that stop
     level.
  2. `TRAIL_STOP_EXIT`: stop = `max(previous stop, round(HWM x 0.95, 2))`,
     ratcheted upward only. A stop strictly above entry that is breached fills
     at the stop level.
- `SL_TARGET_1_2` (all new entries): only `STOP_LOSS_INITIAL` at the fixed 5%
  entry stop and `TARGET_1_2` at
  `round(entry + 2 x (entry - initial_stop), 2)`. Both fill at the stored
  level. The initial stop is never ratcheted, the HWM is not updated and there
  is no EOD, stale or restart-recovery exit.

There is no activation threshold, points-based trail, breakeven lock,
candle-close or time-based exit under either policy. A restored open position
resumes with its saved policy, `hwm`, `stop`, `initial_stop` and `target_price`.

## Tests

```bash
python3 -m unittest discover -s scripts/sma9_5pct_trail_scanner/tests -v
```

The source guard test fails if any removed exit logic returns to the engine or
runner.
