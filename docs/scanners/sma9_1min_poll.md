# `sma9_1min_poll` — SMA9 sampled once a minute

**One line:** the `sma9` entry and the `sma9` exits, but the forming candle is
sampled once per wall-clock minute instead of every 5 seconds.

- **Status:** active, v1.0.0
- **Cadence:** every 60 seconds, aligned to the minute
- **Stop:** fixed 5% of entry premium, after a 5-point trail
- **First live day:** 2026-11-19 (replaced the retired `no_sma`)

## Why it exists

The 5-second scanners produce a lot of Kite traffic and react to every
intra-minute tick, including noise that reverses before the candle closes.
`sma9_1min_poll` keeps the proven SMA9 rule but makes one decision per minute:
12× fewer quote calls per scanner and no reaction to sub-minute spikes. The
trade-off is explicit — a spike between two polls is not seen, so a stop can be
filled later and worse than a 5-second scanner would have filled it.

It occupies the slot of the retired `no_sma` previous-high breakout scanner.

## Entry

Identical to `sma9`, evaluated once per minute:

```
condition_a = previous completed candle CLOSE > SMA9
condition_b = current forming candle OPEN  > SMA9
signal      = condition_a AND condition_b
entry       = paper BUY at round(live LTP, 2)
```

- Both conditions must hold. There is no previous-high breakout and **no
  separate LTP > SMA9 gate**; LTP > SMA9 is reported for information only.
- At most one entry per 5-minute candle per option.
- Entry window: `09:20 <= now < 15:15` IST.
- The scanner refuses to treat the previous completed candle as the forming one
  when the exchange has not published the current 5-minute candle yet, so a
  slow Kite response cannot create a phantom signal.
- CE and PE are evaluated independently.

## Exit

Same trail and fixed floor as `sma9`, evaluated on the 60-second cadence:

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

No target, no candle-close exit, no session-end square-off. Because the poll is
once a minute, the stop and trail are checked 12× less often than on `sma9`;
this is a deliberate property of the strategy, not a defect.

## Runtime

| Item | Value |
|---|---|
| Strategy id / type | `sma9_1min_poll` / `SMA9_1MIN_POLL_BUY_ONLY` |
| Code | `/opt/tradingai/sma9_1min_poll_scanner/` |
| Entrypoint | `app/live_sma9_1min_poll_scanner.py` |
| Engine | `app/sma9_1min_poll_engine.py` |
| PYTHONPATH | `/opt/tradingai/sma9_1min_poll_scanner:/opt/tradingai/sma9_lib` |
| User / unit | `sma91m` / `tradingai-sma9-1min-poll-scanner.service` |
| DB | `/opt/tradingai/database/sma9_1min_poll.db` |
| Tables | `sma9_1min_poll_trades`, `sma9_1min_poll_open_positions`, `sma9_1min_poll_scan_state` |
| Log | `/opt/tradingai/logs/live_sma9_1min_poll_scanner.log` |
| API | `/api/sma9-1min-poll/*` (8 read-only endpoints) |
| Dashboard | `/live/sma9-1min-poll/` |
| Performance report | key `sma9_1min_poll`, label `SMA9 1MIN`, from 2026-11-19 |

## Ops

```bash
systemctl status tradingai-sma9-1min-poll-scanner
tail -f /opt/tradingai/logs/live_sma9_1min_poll_scanner.log

# fake clock/feed, temp DB; drives pre-market -> 09:15 -> 09:20 entry -> exit
python3 /opt/tradingai/sma9_1min_poll_scanner/ops/dryrun_market_open.py
```

The unit is enabled at boot, `Restart=always`, and in `ALL_UNITS` of
`refresh_token.sh`. Its log line is `SMA9 1MIN POLL ready`; the first
post-open scan is at 09:15:00 and the first possible entry at 09:20.

## Relationships

- `sma9` is the same strategy at a 5-second cadence.
- `sma9_1min_atr` keeps this entry but swaps in the ATR stop and ATR trail.
- It replaced `no_sma`; the old DB and dashboard remain on disk as archives
  (see [`retired.md`](retired.md)).
