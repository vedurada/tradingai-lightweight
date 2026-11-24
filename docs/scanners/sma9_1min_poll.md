# `sma9_1min_poll` — SMA9 A+B entry, now polled every 5 seconds with ATR exits

**One line:** the original `sma9` A+B entry, unchanged, with a 5-second poll and
the `sma9_atr` v1.1.0 ATR stop/trail. The identity, history, API and dashboard
are unchanged.

- **Status:** active, v1.1.0 (upgraded in place on 2026-11-20)
- **Cadence:** every 5 seconds, aligned to the 5-second wall-clock boundary
- **Stop:** `clamp(0.70 × ATR14, 5%, 30% of entry)`, filled at the live LTP
- **Trail:** `peak − same ATR distance`, active once price is above entry; no fixed activation and no breakeven lock
- **First live day:** 2026-11-19 (v1.1.0 deployed 2026-11-20)

## Why v1.1.0

The scanner keeps its original id (`sma9_1min_poll`), DB, service, user, API and
page. Only behavior changed:

- The 60-second sample missed sub-minute stop and trail moves, so the runner now
  polls every 5 seconds like `sma9_atr`, filling stops at the live LTP.
- The old fixed 5% stop, 5-point trail, +5 activation and +6 breakeven lock are
  removed in favour of the volatility-scaled ATR stop and ATR-only trail used by
  `sma9_atr` v1.1.0.
- Entry stays A and B only. No rising-SMA9 filter, no new LTP gate and no daily
  regime gate were added.

## Entry

Unchanged from v1.0.0, evaluated on every 5-second poll:

```
condition_a = previous completed candle CLOSE > SMA9
condition_b = current forming candle OPEN  > SMA9
signal      = condition_a AND condition_b
entry       = paper BUY at round(live LTP, 2)
```

- Both conditions must hold. There is no previous-high breakout and **no
  separate LTP > SMA9 gate**; LTP > SMA9 is reported for information only.
- There is no rising-SMA9 filter: current SMA9 > prior SMA9 is not required.
- At most one entry per 5-minute candle per option.
- Entry window: `09:20 <= now < 15:15` IST.
- Scanning starts at 09:00 IST; the exchange publishes the first 5-minute
  candle at 09:15, so the first possible entry is 09:20. 09:00–09:15 is
  warm-up only: no entry is evaluated and no exit is managed.
- The scanner refuses to treat the previous completed candle as the forming one
  when the exchange has not published the current 5-minute candle yet, so a
  slow Kite response cannot create a phantom signal.
- CE and PE are evaluated independently.

## Exit

The initial stop and trail both come from the option premium's ATR(14) on
completed 5-minute candles:

```
distance  = clamp(0.70 × ATR14, 0.05 × entry, 0.30 × entry)
stop      = entry - distance
```

```
if ATR is unavailable: distance = 0.10 × entry (fallback)
if LTP <= stop:        exit at the ACTUAL live LTP   # STOP_LOSS_ATR
if LTP > entry:        trail_stop = peak - distance, ratcheted upward
if LTP <= trail_stop:  exit at the ACTUAL live LTP
else:                  hold
```

- The ATR distance is frozen at entry and reused as the trail width.
- The trail is active as soon as price makes a new high above entry. There is no
  fixed +5 activation and no +6 breakeven lock.
- Stops and trails fill at the sampled live LTP, never at the theoretical stop
  price.
- No target, no candle-close exit, no session-end square-off and no time-based
  exit.

## Migration of v1.0.0 state

The existing `sma9_1min_poll.db` keeps its history. The runner adds nullable ATR
columns to the trades and open-position tables. A legacy open position is
restored using `compute_stop(entry_price, None)`; the old `stop_price` was a
BE-locked trail, so it is replaced with the v1.1.0 ATR stop and trail state.

## Runtime

| Item | Value |
|---|---|
| Strategy id / type | `sma9_1min_poll` / `SMA9_1MIN_POLL_BUY_ONLY` |
| Version | 1.1.0 |
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
| Performance report | key `sma9_1min_poll`, label `SMA9 5S POLL ATR`, from 2026-11-19 |

Health thresholds used by the page/API: `ACTIVE` if the last scan is within
15 s, `STALE` beyond 15 s while the market is open, and `IDLE_MARKET_CLOSED`
within 180 s of the last scan when the market is closed.

## Ops

```bash
systemctl status tradingai-sma9-1min-poll-scanner
tail -f /opt/tradingai/logs/live_sma9_1min_poll_scanner.log

# fake clock/feed, temp DB; drives pre-market -> 09:00 -> 09:20 -> ATR exit
python3 /opt/tradingai/sma9_1min_poll_scanner/ops/dryrun_market_open.py
# read-only real-feed smoke test (no DB, no orders)
python3 /opt/tradingai/sma9_1min_poll_scanner/ops/real_feed_check.py
```

The unit is enabled at boot, `Restart=always`, and in `ALL_UNITS` of
`refresh_token.sh`. Its log line is `SMA9 5S POLL ATR scanner ready`; the first
scan starts at 09:00:00 and the first possible entry is at 09:20.

## Relationships

- `sma9` is the same A+B entry at 5 seconds, but with fixed 5% stop and 5-point
  trail.
- `sma9_atr` adds a daily NIFTY spot regime gate; this scanner does not.
- This scanner keeps the A+B entry only; the former `sma9_slope_atr` added a
  rising-SMA9 filter but was retired on 2026-11-24 (see [`retired.md`](retired.md)).
- It replaced `no_sma`; the old DB and dashboard remain on disk as archives
  (see [`retired.md`](retired.md)).
