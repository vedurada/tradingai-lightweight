# `sma9_high_trail` — self-contained HIGH entry with a 5-point trail

**One line:** owns the `sma9_high` entry (SMA9 plus a previous-high breakout)
and the trailing exit in one process.

- **Status:** active, v2.1.0
- **Cadence:** every 5 seconds, offset 3.0 s
- **Stop:** fixed 5% of entry premium, after a 5-point trail

## Why it exists

It is the trailing-exit counterpart of `sma9_high`: only buy when the premium
is actually breaking the previous candle's high, then let a trailing stop
capture the move. Like `sma9_trail`, it is now fully self-contained — it
evaluates its own entry signal instead of consuming the base scanner's
position. `consumed_base_trades` remains as a legacy table only.

## Entry

Per option (CE and PE independent), from that option's own 5-minute candles:

```
condition_a = previous completed candle CLOSE > SMA9
condition_c = current forming candle OPEN  > SMA9
condition_b = live LTP > previous completed candle HIGH
signal      = condition_a AND condition_c AND condition_b
entry       = paper BUY at round(live LTP, 2)
```

- All three conditions must hold on the same poll.
- No separate LTP > SMA9 gate; B is the breakout.
- At most one entry per 5-minute candle per option.
- Entry window: `09:20 <= now < 15:15` IST.

## Exit

Trail first, then the 5% floor:

```
hwm = max(hwm, LTP)
if hwm - entry >= 5.0:
    stop = max(entry, hwm - 5.0)       # breakeven then ratchet up only
if hwm - entry >= 6.0 and not be_locked:
    stop = max(stop, entry + 2.0)      # one-time breakeven lock
    be_locked = True

if stop > entry and LTP <= stop:  exit at LTP            # TRAIL_STOP_EXIT
elif LTP <= round(entry * 0.95, 2): exit at that level   # STOP_LOSS_5PCT
else: hold
```

- Trail exit fills at the **actual sampled LTP**.
- Trail is checked before the 5% floor.
- No target, no candle-close exit, no session-end square-off.
- Trail state is persisted across restarts.

## Runtime

| Item | Value |
|---|---|
| Strategy id / type | `sma9_high_trail` / `SMA_HIGH_BUY_ONLY` |
| Code | `/opt/tradingai/sma9_high_trail_scanner/` |
| Entrypoint | `app/live_sma9_high_trail_scanner.py` |
| Engine | `app/sma9_high_trail_engine.py` |
| User / unit | `sma9trailhigh` / `tradingai-sma9_high_trail-scanner.service` |
| DB | `/opt/tradingai/database/sma9_high_trail.db` |
| Tables | `sma9_high_trail_trades`, `sma9_high_trail_open_positions`, `sma9_high_trail_scan_state`, legacy `consumed_base_trades` |
| Log | `/opt/tradingai/logs/live_sma9_high_trail_scanner.log` |
| API | `/api/sma9-high-trail/*` (9 read-only endpoints) |
| Dashboard | `/live/sma9-high-trail/` |
| Performance report | key `sma9_high_trail`, label `SMA9 HIGH Trail` |

## Ops

```bash
systemctl status tradingai-sma9_high_trail-scanner
tail -f /opt/tradingai/logs/live_sma9_high_trail_scanner.log
```

One batched spot+CE+PE quote per 5-second tick; historical candles only when a
new 5-minute candle appears or at exit. The unit is enabled, `Restart=always`,
and in `ALL_UNITS` of `refresh_token.sh`.

## Relationships

- `sma9_high` — same entry, trail is secondary to the fixed stop.
- `sma9_trail` — same exit, plain SMA9 entry.
