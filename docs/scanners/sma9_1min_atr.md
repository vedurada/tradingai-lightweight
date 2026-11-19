# `sma9_1min_atr` — 1-minute SMA9 entry with an ATR stop and ATR trail

**One line:** the `sma9_1min_poll` entry plus the `sma9_atr` stop, with the ATR
distance also used as the trail width. It replaces the retired `no_sma_trail`.

- **Status:** active, v1.0.0
- **Cadence:** every 60 seconds, aligned to the minute
- **Stop:** `clamp(0.70 × ATR14, 5%, 30% of entry)`, filled at the live LTP
- **Trail:** same +5 / +6 shape, but the ratchet width is the ATR distance
- **First live day:** 2026-11-19

## Why it exists

It is the combination the other two variants motivate:

- `sma9_1min_poll` proves the SMA9 entry still works when sampled once a
  minute, with 12× less Kite traffic and no sub-minute noise.
- `sma9_atr` proves a volatility-scaled stop survives cheap-premium days better
  than a fixed 5% stop.

`sma9_1min_atr` takes the 1-minute entry and replaces **both** the stop floor
and the trail width with the option's own ATR distance, so the exit envelope
scales with the contract instead of being fixed in points or percent.

It occupies the slot of the retired `no_sma_trail` scanner. It is fully
isolated: own code tree, DB, service user, unit, log, API namespace and page.
No other scanner is read, written or restarted by it.

## Entry

Identical to `sma9_1min_poll`, evaluated once per minute:

```
condition_a = previous completed candle CLOSE > SMA9
condition_b = current forming candle OPEN  > SMA9
signal      = condition_a AND condition_b
entry       = paper BUY at round(live LTP, 2)
```

- Both conditions only. There is **no previous-high breakout** and **no
  separate LTP > SMA9 gate**; LTP > SMA9 is reported for information only.
- At most one entry per 5-minute candle per option.
- Entry window: `09:20 <= now < 15:15` IST. CE and PE independent.
- Scanning starts at 09:00 IST; the exchange publishes the first 5-minute
  candle at 09:15, so the first possible entry is 09:20.
- The scanner waits for the exchange to publish the current 5-minute candle
  before evaluating the forming candle, so a boundary cannot create a
  zero-duration trade.

## Stop

```
atr      = mean True Range of the option premium over the last 14 completed 5m candles
distance = clamp(0.70 * atr, 0.05 * entry, 0.30 * entry)   # frozen at entry
stop     = entry - distance
```

- Stored as `atr_at_entry`, `stop_price`, `stop_k`, `stop_distance_pct`,
  `stop_source` and `trail_distance`.
- If LTP <= stop, the trade closes at the **actual live LTP**
  (`STOP_LOSS_ATR`), not the theoretical stop.
- Fewer than 15 completed candles → 10% of entry
  (`stop_source='fallback_pct'`).
- ATR is the rolling last 14 completed candles from a 45-day fetch, not reset
  per day. At 09:15–09:20 it is yesterday's 14 true ranges; the first entry
  around 09:21 includes the overnight-gap true range. The trail distance is
  frozen at entry and does not re-scale later.

## Trail

The +5 activation and +6 breakeven lock are kept, but the ratchet width is the
ATR distance:

```
hwm = max(hwm, LTP)
if hwm - entry >= 5.0:
    stop = max(stop, hwm - distance)   # activation and ratchet in the same poll
if hwm - entry >= 6.0 and not be_locked:
    stop = max(stop, entry + 2.0)      # one-time breakeven lock
    be_locked = True

if stop > entry and LTP <= stop: exit at LTP   # TRAIL_STOP_EXIT
else: hold
```

- Because the poll is 60 seconds, activation and the ratchet are applied in the
  **same** tick. A single sample that jumps past +5 immediately gets
  `peak − distance` instead of sitting at breakeven until the next minute.
- A wide ATR trail can never undo the tighter +6 breakeven lock (`max`).
- If `trail_distance` is somehow missing, the engine falls back to a 5-point
  width.
- No target, no candle-close exit, no session-end square-off.

## Runtime

| Item | Value |
|---|---|
| Strategy id / type | `sma9_1min_atr` / `SMA9_1MIN_ATR_STOP_BUY_ONLY` |
| Code | `/opt/tradingai/sma9_1min_atr_scanner/` |
| Entrypoint | `app/live_sma9_1min_atr_scanner.py` |
| Engine | `app/sma9_1min_atr_engine.py` |
| User / unit | `sma91matr` / `tradingai-sma9-1min-atr-scanner.service` |
| DB | `/opt/tradingai/database/sma9_1min_atr.db` |
| Tables | `sma9_1min_atr_trades`, `sma9_1min_atr_open_positions`, `sma9_1min_atr_scan_state` |
| Log | `/opt/tradingai/logs/live_sma9_1min_atr_scanner.log` |
| API | `/api/sma9-1min-atr/*` (8 read-only endpoints) |
| Dashboard | `/live/sma9-1min-atr/` |
| Performance report | key `sma9_1min_atr`, label `SMA9 1MIN ATR`, from 2026-11-19 |

## State and restart behaviour

Persisted in `sma9_1min_atr_open_positions`: `atr_at_entry`, `stop_price`,
`stop_k`, `stop_distance_pct`, `stop_source`, `trail_distance`, `hwm`,
`trail_stop`, `be_locked`. The ratchet is written on every poll.

- Same-day restart resumes the exact stop and high-water mark.
- A position from an earlier session is closed at the current LTP with
  `STALE_RECOVERY_EXIT` rather than carried.

## Ops

```bash
systemctl status tradingai-sma9-1min-atr-scanner
tail -f /opt/tradingai/logs/live_sma9_1min_atr_scanner.log

# fake clock/feed, temp DB: pre-market -> 09:00 -> 09:20 entry -> ATR stop ->
# re-entry -> ATR trail ratchet -> restart recovery -> stale prior-day position
python3 /opt/tradingai/sma9_1min_atr_scanner/ops/dryrun_market_open.py

# real Kite path, writes nothing
python3 /opt/tradingai/sma9_1min_atr_scanner/ops/real_feed_check.py
```

The unit is enabled, `Restart=always`, and in `ALL_UNITS` of
`refresh_token.sh`. The launcher button is **SMA9 1MIN ATR**.

Health thresholds used by the page/API: `ACTIVE` if the last scan is within
90 s, `STALE` beyond 90 s, `IDLE` when the market is closed and the last scan
is within 180 s.

## Relationships

- `sma9_1min_poll` — same entry and cadence, fixed 5% stop and 5-point trail.
- `sma9_atr` — same stop, 5-second cadence, 5-point trail.
- `no_sma_trail` — retired predecessor; its DB and page remain as archives
  (see [`retired.md`](retired.md)).
