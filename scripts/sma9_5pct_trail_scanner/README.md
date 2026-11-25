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
| Poll offset | 1.8 seconds in the aligned 5-second window |

## Rules

Entry (unchanged from the retired scanner, self-contained in the runner):

- Previous completed 5-minute option-premium close > SMA9.
- Current forming 5-minute option-premium open > SMA9.
- ATM CE and PE are evaluated independently; long only; at most one position
  per option.

Exits — **the only two conditions**:

1. `STOP_LOSS_5PCT`: LTP <= `round(entry x 0.95, 2)`. Fill is at that stop
   level.
2. `TRAIL_STOP_EXIT`: stop = `max(previous stop, round(HWM x 0.95, 2))`,
   ratcheted upward only. A stop strictly above entry that is breached fills
   at the stop level.

There is no activation threshold, points-based trail, breakeven lock,
candle-close exit, target, time-based exit or restart-recovery exit. A
restored open position simply resumes the two live stop checks with its saved
`hwm` and `stop`.

## Tests

```bash
python3 -m unittest discover -s scripts/sma9_5pct_trail_scanner/tests -v
```

The source guard test fails if any removed exit logic returns to the engine or
runner.
