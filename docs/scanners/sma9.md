# `sma9` — baseline SMA9 premium scanner

**One line:** buy ATM CE or PE when the option's previous 5-minute candle
closed above its 9-period SMA and the forming candle opened above it.

- **Status:** active, v2.7.0, locked tree
- **Cadence:** every 5 seconds, offset 0
- **Stop:** fixed 5% of entry premium, after a 5-point trail
- **First live day:** pre-dates the 2026-11 scanner expansion

## Why it exists

`sma9` is the reference strategy. Every other premium scanner is a deliberate
variation of it, so its rules are the baseline used to judge whether a variant
adds value. It is intentionally simple: one trend filter on the option premium,
no breakout confirmation, no volatility scaling.

## Entry

For each ATM CE and ATM PE independently, using that option's own 5-minute
candles:

```
condition_a = previous completed candle CLOSE > SMA9
condition_b = current forming candle OPEN  > SMA9
signal      = condition_a AND condition_b
entry       = paper BUY at round(live LTP, 2)
```

- Both conditions must hold. There is **no separate LTP > SMA9 gate**.
- Entry can fire on any 5-second poll while the signal holds.
- At most one entry per 5-minute candle per option.
- Entry window: `09:20 <= now < 15:15` IST.
- Scanning starts at 09:00 IST; the exchange publishes the first 5-minute
  candle at 09:15, so the first possible entry is 09:20. 09:00–09:15 is
  warm-up only: no entry is evaluated and no exit is managed.
- CE and PE are evaluated independently; both may be open at once.
- The 09:15 candle is never entered.

## Exit

Evaluated on every 5-second poll, **trail first**, then the fixed floor:

```
hwm = max(hwm, LTP)
if hwm - entry >= 5.0:
    stop = entry                       # first activation: breakeven
    stop = max(stop, hwm - 5.0)        # ratchet up only
if hwm - entry >= 6.0 and not be_locked:
    stop = max(stop, entry + 2.0)      # one-time breakeven lock
    be_locked = True

if stop > entry and LTP <= stop:  exit at LTP       # TRAIL_STOP_EXIT
elif LTP <= round(entry * 0.95, 2): exit at that level  # STOP_LOSS_5PCT
else: hold
```

- Exit price for the trail is the **actual sampled LTP** at the breach, not the
  ideal stop level (this models slippage).
- The trail is evaluated before the 5% stop, so a profitable trail lock always
  wins.
- No target, no candle-close exit, no session-end square-off.
- `hwm`, `stop` and `be_locked` are persisted in the open-position row, so a
  restart resumes the exact trail.

## Runtime

| Item | Value |
|---|---|
| Strategy id / type | `sma9_only` / `SMA9_BUY_ONLY` |
| Code | `/opt/tradingai/sma9_scanner/` (root-owned, immutable) |
| Entrypoint | `app/live_sma9_scanner.py` |
| Engine | `app/sma9_engine.py` |
| User / unit | `sma9` / `tradingai-sma9-scanner.service` |
| DB | `/opt/tradingai/database/sma9.db` |
| Tables | `sma9_trades`, `sma9_open_positions`, `sma9_scan_state` |
| Log | `/opt/tradingai/logs/live_sma9_scanner.log` |
| API | `/api/sma9/*` (9 read-only endpoints) |
| Dashboard | `/live/sma9/` |
| Performance report | key `sma9`, label `SMA9` |

## Ops

```bash
systemctl status tradingai-sma9-scanner
tail -f /opt/tradingai/logs/live_sma9_scanner.log

# tree is immutable — verify before and after any change
sudo /opt/tradingai/sma9_scanner/ops/verify_integrity.sh
sudo /opt/tradingai/sma9_scanner/ops/status.sh
lsattr /opt/tradingai/sma9_scanner/app/live_sma9_scanner.py   # expect 'i'
```

The unit is enabled at boot, `Restart=always`, and in `ALL_UNITS` of
`refresh_token.sh`, so a daily token refresh restarts it.

## Relationships

- `sma9_high` adds a previous-candle-high breakout.
- `sma9_atr` replaces the 5% floor with an ATR-scaled stop.
- `sma9_trail` is a self-contained copy of this entry with the same trail.
