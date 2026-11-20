# `sma9_5s_atr` — SMA9 with a rising-average filter, ATR stop and ATR-only trail

**One line:** the SMA9 entry plus a rising-SMA9 filter, an ATR-scaled stop and
an ATR-only trail, now sampled every **5 seconds**. It replaces the retired
`no_sma_trail`.

- **Status:** active, v1.1.0
- **Cadence:** every 5 seconds, aligned to the 5-second wall-clock boundary
- **Identity:** renamed from `sma9_1min_atr` on 2026-11-20; old DB/code kept as archive
- **Stop:** `clamp(0.70 × ATR14, 5%, 30% of entry)`, filled at the live LTP
- **Trail:** `peak − same ATR distance`, active once price is above entry; no fixed activation and no breakeven lock
- **First live day:** 2026-11-19 (v1.1.0 deployed 2026-11-20)

## Why v1.1.0

- The scanner was renamed from `sma9_1min_atr` to `sma9_5s_atr` so the `1min`
  label no longer contradicts the 5-second cadence. The old DB was copied into
  the new one, and the old service/API/page were retired as archives.
- The 60-second sample missed sub-minute stop and trail moves, so the poll is
  now 5 seconds like `sma9_atr`.
- The old +5 activation / +6 breakeven lock produced small, frequent winners
  and ignored the contract's own volatility. The trail is now purely the ATR
  distance frozen at entry, the same rule as `sma9_atr` v1.1.0.
- Entry gains an explicit rising-average filter: **current SMA9 > prior SMA9**
  (the 9-candle average ending one completed candle earlier). This is a genuine
  extra filter: rolling the window changes the average by `(new close − dropped
  close) / 9`, so a close above the average (condition A) does not guarantee a
  rising average. A real-feed check found A/B true with C false.

## Entry

For each of ATM CE and ATM PE, from that option's own 5-minute candles:

```
condition_a = previous completed candle CLOSE > SMA9
condition_b = current forming candle OPEN  > SMA9
condition_c = current SMA9 > prior SMA9      # 10 completed candles required
signal      = condition_a AND condition_b AND condition_c
entry       = paper BUY at round(live LTP, 2)
```

- No previous-high breakout and no separate **LTP > SMA9** gate; LTP > SMA9 is
  reported for information only.
- At most one entry per 5-minute candle per option.
- Entry window: `09:20 <= now < 15:15` IST. CE and PE independent.
- Scanning starts at 09:00 IST; 09:00–09:15 is warm-up only: no entry is
  evaluated and no exit is managed.
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
- ATR is the rolling last 14 completed candles from a 45-day fetch. The trail
  distance is frozen at entry and does not re-scale later.

## Trail

```
hwm = max(hwm, LTP)
if hwm > entry:
    stop = max(stop, hwm - distance)   # same ATR distance, frozen at entry
exit when LTP <= stop                  # TRAIL_STOP_EXIT at the LTP
```

- No fixed +5 activation and no +6 breakeven lock.
- The stop can never ratchet down.
- Until price moves above entry the initial ATR stop is the only exit, so a
  losing trade is never labelled as a trail exit.
- No target, no candle-close exit, no session-end square-off.

## Runtime

| Item | Value |
|---|---|
| Strategy id / type | `sma9_5s_atr` / `SMA9_5S_ATR_STOP_BUY_ONLY` |
| Strategy version | `1.1.0` |
| Code | `/opt/tradingai/sma9_5s_atr_scanner/` |
| Entrypoint | `app/live_sma9_5s_atr_scanner.py` |
| Engine | `app/sma9_5s_atr_engine.py` |
| User / unit | `sma95satr` / `tradingai-sma9-5s-atr-scanner.service` |
| DB | `/opt/tradingai/database/sma9_5s_atr.db` |
| Tables | `sma9_5s_atr_trades`, `sma9_5s_atr_open_positions`, `sma9_5s_atr_scan_state` |
| Log | `/opt/tradingai/logs/live_sma9_5s_atr_scanner.log` |
| API | `/api/sma9-5s-atr/*` (8 read-only endpoints) |
| Dashboard | `/live/sma9-5s-atr/` |
| Performance report | key `sma9_5s_atr`, label `SMA9 5S ATR`, from 2026-11-19 |

## State and restart behaviour

Persisted in `sma9_5s_atr_open_positions`: `atr_at_entry`, `stop_price`,
`stop_k`, `stop_distance_pct`, `stop_source`, `trail_distance`, `hwm`,
`trail_stop`, `prev_sma9`, `condition_c` and legacy `be_locked`.

- Same-day restart resumes the trade and **rebuilds the trail from the frozen
  ATR distance** under the ATR-only rule; the old BE-lock state is discarded.
- v1.0.0 databases are migrated in place: `prev_sma9`, `condition_c` and
  (for trades) `trail_distance` columns are added idempotently.
- A position from an earlier session is closed at the current LTP with
  `STALE_RECOVERY_EXIT` rather than carried.

## Ops

```bash
systemctl status tradingai-sma9-5s-atr-scanner
tail -f /opt/tradingai/logs/live_sma9_5s_atr_scanner.log

# fake clock/feed, temp DB: pre-market -> 09:00 -> 09:20 entry -> ATR stop ->
# re-entry -> ATR trail ratchet -> restart recovery -> stale prior-day position
python3 /opt/tradingai/sma9_5s_atr_scanner/ops/dryrun_market_open.py

# real Kite path, writes nothing
python3 /opt/tradingai/sma9_5s_atr_scanner/ops/real_feed_check.py
```

The unit is enabled, `Restart=always`, and in `ALL_UNITS` of `refresh_token.sh`.
The launcher button is **SMA9 5S ATR**.

Health thresholds used by the page/API: `ACTIVE` if the last scan is within
15 s, `STALE` beyond 15 s while the market is open, and `IDLE_MARKET_CLOSED`
within 180 s of the last scan when the market is closed.

## Relationships

- `sma9_atr` — same ATR stop / ATR-only trail, 5-second cadence, plus a daily
  NIFTY spot regime gate; no rising-SMA9 filter.
- `sma9_1min_poll` — 60-second cadence, fixed 5% stop and 5-point trail.
- `no_sma_trail` — retired predecessor; its DB and page remain as archives
  (see [`retired.md`](retired.md)).
