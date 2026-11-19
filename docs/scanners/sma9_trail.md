# `sma9_trail` — self-contained SMA9 entry with a 5-point trail

**One line:** owns the `sma9` entry **and** the trailing exit in one process;
it no longer waits for another scanner to open a position.

- **Status:** active, v2.1.0
- **Cadence:** every 5 seconds, offset 1.2 s
- **Stop:** fixed 5% of entry premium, after a 5-point trail

## Why it exists

This is the "pure trail" version of the baseline strategy: the same entry as
`sma9`, with the trail as the primary exit. Historically the `*_trail` scanners
consumed the base scanner's open position over HTTP and only managed the exit.
That coupling is gone — the current engine evaluates its own signal from live
5-minute option candles, so `sma9_trail` is a fully independent strategy that
can be compared with `sma9` on identical entries.

`consumed_base_trades` still exists in the DB as a legacy artefact from the
old design; it is not used for entry.

## Entry

Per option (CE and PE independent), from that option's own 5-minute candles:

```
condition_a = previous completed candle CLOSE > SMA9
condition_b = current forming candle OPEN  > SMA9
signal      = condition_a AND condition_b
entry       = paper BUY at round(live LTP, 2)
```

- Both conditions must hold; no previous-high breakout and no separate
  LTP > SMA9 gate.
- At most one entry per 5-minute candle per option.
- Entry window: `09:20 <= now < 15:15` IST.
- Scanning starts at 09:00 IST; the exchange publishes the first 5-minute
  candle at 09:15, so the first possible entry is 09:20. 09:00–09:15 is
  warm-up only: no entry is evaluated and no exit is managed.

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

- The trail exit uses the **actual sampled LTP** at the breach.
- The trail is checked before the 5% floor, so a profitable lock wins.
- No target, no candle-close exit, no session-end square-off.
- `hwm`, `stop` and `be_locked` are persisted, so a restart resumes the trail.

## Runtime

| Item | Value |
|---|---|
| Strategy id / type | `sma9_trail` / `SMA_BUY_ONLY` |
| Code | `/opt/tradingai/sma9_trail_scanner/` |
| Entrypoint | `app/live_sma9_trail_scanner.py` |
| Engine | `app/sma9_trail_engine.py` |
| User / unit | `sma9trail` / `tradingai-sma9_trail-scanner.service` |
| DB | `/opt/tradingai/database/sma9_trail.db` |
| Tables | `sma9_trail_trades`, `sma9_trail_open_positions`, `sma9_trail_scan_state`, legacy `consumed_base_trades` |
| Log | `/opt/tradingai/logs/live_sma9_trail_scanner.log` |
| API | `/api/sma9-trail/*` (9 read-only endpoints) |
| Dashboard | `/live/sma9-trail/` |
| Performance report | key `sma9_trail`, label `SMA9 Trail` |

Note the unit name uses an underscore (`tradingai-sma9_trail-scanner`) while the
API/dashboard slug uses a hyphen (`sma9-trail`).

## Ops

```bash
systemctl status tradingai-sma9_trail-scanner
tail -f /opt/tradingai/logs/live_sma9_trail_scanner.log
```

Rate-limit profile: one batched spot+CE+PE quote per 5-second tick, historical
candles only when a new 5-minute candle appears or at exit. The unit is
enabled, `Restart=always`, and in `ALL_UNITS` of `refresh_token.sh`.

## Relationships

- `sma9` — same entry, trail is secondary to the fixed stop.
- `sma9_high_trail` — same exit, stricter HIGH entry.
- The old "consume the base scanner" design is documented only as history; do
  not rely on `consumed_base_trades` for current behaviour.
