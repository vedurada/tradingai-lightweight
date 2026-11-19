# `sma9_high` — SMA9 with a previous-high breakout

**One line:** `sma9` entry **plus** a live premium break above the previous
completed candle's high, so the scanner only buys strength, not a flat open
above the average.

- **Status:** active, v1.8.0, locked tree
- **Cadence:** every 5 seconds, offset 2.4 s
- **Stop:** fixed 5% of entry premium, after a 5-point trail

## Why it exists

`sma9` can enter while the forming candle is still inside the previous
candle's range — above the SMA but showing no actual upside. `sma9_high`
requires the premium to trade through the prior high, filtering those weak
setups. It is the strict sibling of `sma9` and the base strategy for the
`HIGH` family.

## Entry

For each ATM CE and ATM PE independently, using that option's own 5-minute
candles:

```
condition_a = previous completed candle CLOSE > SMA9
condition_c = current forming candle OPEN  > SMA9
condition_b = live LTP > previous completed candle HIGH
signal      = condition_a AND condition_c AND condition_b
entry       = paper BUY at round(live LTP, 2)
```

- All three conditions must hold on the same poll.
- There is **no separate LTP > SMA9 confirmation gate**; the SMA conditions are
  A and C, and B is the breakout.
- Entry can fire on any 5-second poll while the signal holds.
- At most one entry per 5-minute candle per option.
- Entry window: `09:20 <= now < 15:15` IST. CE and PE independent.
- Scanning starts at 09:00 IST; the exchange publishes the first 5-minute
  candle at 09:15, so the first possible entry is 09:20. 09:00–09:15 is
  warm-up only: no entry is evaluated and no exit is managed.

## Exit

Identical to `sma9` — trail first, then the fixed 5% floor:

```
hwm = max(hwm, LTP)
if hwm - entry >= 5.0:
    stop = max(entry, hwm - 5.0)       # breakeven then ratchet
if hwm - entry >= 6.0 and not be_locked:
    stop = max(stop, entry + 2.0)      # one-time breakeven lock
    be_locked = True

if stop > entry and LTP <= stop:  exit at LTP            # TRAIL_STOP_EXIT
elif LTP <= round(entry * 0.95, 2): exit at that level   # STOP_LOSS_5PCT
else: hold
```

No target, no candle-close exit, no session-end square-off. Trail state is
persisted in the open-position row.

## Runtime

| Item | Value |
|---|---|
| Strategy id / type | `sma9_high` / `SMA9_HIGH_BUY_ONLY` |
| Code | `/opt/tradingai/sma9_high_scanner/` (root-owned, immutable) |
| Entrypoint | `app/live_sma9_high_scanner.py` |
| Engine | `app/sma9_high_engine.py` |
| User / unit | `sma9high` / `tradingai-sma9-high-scanner.service` |
| DB | `/opt/tradingai/database/sma9_high.db` |
| Tables | `sma9_high_trades`, `sma9_high_open_positions`, `sma9_high_scan_state` |
| Log | `/opt/tradingai/logs/live_sma9_high_scanner.log` |
| API | `/api/sma9-high/*` (9 read-only endpoints) |
| Dashboard | `/live/sma9-high/` |
| Performance report | key `sma9_high`, label `SMA9 HIGH` |

## Ops

```bash
systemctl status tradingai-sma9-high-scanner
tail -f /opt/tradingai/logs/live_sma9_high_scanner.log
sudo /opt/tradingai/sma9_high_scanner/ops/verify_integrity.sh
```

The unit is enabled at boot, `Restart=always`, and in `ALL_UNITS` of
`refresh_token.sh`. It also has an enabled `tradingai-sma9-high-integrity.timer`
that re-verifies the locked tree.

## Relationships

- `sma9` is the same strategy without the breakout condition B.
- `sma9_high_trail` is a self-contained copy of this entry with the same trail.
- `sma9_1min_poll` / `sma9_1min_atr` deliberately use the plain `sma9` entry,
  not this stricter one.
