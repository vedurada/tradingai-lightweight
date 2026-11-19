# `sma9_atr` — SMA9 entry with a volatility-scaled stop

**One line:** the `sma9` entry, but the initial stop is sized from the option
premium's own ATR instead of a fixed 5%, so cheap contracts are not stopped out
by normal noise.

- **Status:** active, v1.0.0
- **Cadence:** every 5 seconds, offset 0
- **Stop:** `clamp(0.70 × ATR14, 5%, 30% of entry)`, filled at the live LTP
- **Trail:** unchanged `sma9` trail (5-point width)
- **First live day:** 2026-11-19

## Why it exists

The fixed 5% stop shrinks in absolute points as an option premium decays, while
ATM premium noise stays roughly constant (~11–15 points). On 2026-11-17
(0 DTE) the 5% stop was 2.34 points against ~14 points of 5-minute noise: 68%
of trades stopped out, and 39 of 65 losing trades sat inside losing streaks.
ATR scaling keeps the stop outside the noise band on cheap contracts and close
to the old 5% distance on expensive ones.

`sma9_atr` changes **only** the stop distance. Entry, trail and holding period
are identical to `sma9`, so a comparison between the two isolates the effect of
the stop model.

## Entry

Identical to `sma9`, using the option's own 5-minute candles:

```
condition_a = previous completed candle CLOSE > SMA9
condition_b = current forming candle OPEN  > SMA9
signal      = condition_a AND condition_b
entry       = paper BUY at round(live LTP, 2)
```

No previous-high breakout and no separate LTP > SMA9 gate. At most one entry
per 5-minute candle per option; entry window `09:20 <= now < 15:15` IST; CE and
PE independent. Scanning starts at 09:00 IST; the first signal candle is 09:15,
so the first possible entry is 09:20. 09:00–09:15 is warm-up only: no entry
is evaluated and no exit is managed.

## Stop

```
atr      = mean True Range of the option premium over the last 14 completed 5m candles
distance = clamp(0.70 * atr, 0.05 * entry, 0.30 * entry)
stop     = entry - distance
```

- The ATR is computed once, at entry, and frozen. It is stored as
  `atr_at_entry`, and the resulting distance as `stop_price` / `stop_k` /
  `stop_distance_pct` / `stop_source`.
- If LTP <= stop, the trade closes at the **actual live LTP**, not the
  theoretical stop price (`STOP_LOSS_ATR`). A fast move through the stop is
  recorded at the price the scanner actually saw.
- With fewer than 15 completed candles the stop falls back to 10% of entry
  (`stop_source='fallback_pct'`).
- The ATR uses the rolling last 14 completed candles from a 45-day fetch; it is
  not reset per day. At 09:15–09:20 it is still yesterday's 14 true ranges; the
  first entry around 09:21 includes the overnight-gap true range.

## Trail

Unchanged from `sma9` — the ATR affects only the floor:

```
hwm = max(hwm, LTP)
if hwm - entry >= 5.0:
    stop = max(stop, hwm - 5.0)        # breakeven then ratchet
if hwm - entry >= 6.0 and not be_locked:
    stop = max(stop, entry + 2.0)      # one-time breakeven lock
    be_locked = True

if stop > entry and LTP <= stop: exit at LTP   # TRAIL_STOP_EXIT
else: hold
```

No target, no candle-close exit, no session-end square-off.

## Runtime

| Item | Value |
|---|---|
| Strategy id / type | `sma9_atr` / `SMA9_ATR_STOP_BUY_ONLY` |
| Code | `/opt/tradingai/sma9_atr_scanner/` |
| Entrypoint | `app/live_sma9_atr_scanner.py` |
| Engine | `app/sma9_atr_engine.py` |
| User / unit | `sma9` / `tradingai-sma9-atr-scanner.service` |
| DB | `/opt/tradingai/database/sma9_atr.db` |
| Tables | `sma9_atr_trades`, `sma9_atr_open_positions`, `sma9_atr_scan_state` |
| Log | `/opt/tradingai/logs/live_sma9_atr_scanner.log` |
| API | `/api/sma9-atr/*` (8 read-only endpoints) |
| Dashboard | `/live/sma9-atr/` |
| Performance report | key `sma9_atr`, label `SMA9 ATR`, from 2026-11-19 |

It runs as the existing `sma9` user but shares no code, DB, state or unit with
`sma9`.

## State and restart behaviour

Persisted in `sma9_atr_open_positions`: `atr_at_entry`, `stop_price`,
`stop_k`, `stop_distance_pct`, `stop_source`, `hwm`, `trail_stop`,
`be_locked`.

- Same-day restart resumes the exact stop and high-water mark.
- A position from an earlier session is closed at the current LTP with
  `STALE_RECOVERY_EXIT` rather than carried overnight.

## Ops

```bash
systemctl status tradingai-sma9-atr-scanner
tail -f /opt/tradingai/logs/live_sma9_atr_scanner.log

# fake clock/feed, temp DB: pre-market -> 09:00 -> 09:20 entry -> ATR stop ->
# re-entry -> restart recovery
python3 /opt/tradingai/sma9_atr_scanner/ops/dryrun_market_open.py

# real Kite path, writes nothing
python3 /opt/tradingai/sma9_atr_scanner/ops/real_feed_check.py
```

The unit is enabled, `Restart=always`, and in `ALL_UNITS` of
`refresh_token.sh`.

## Relationships

- `sma9` is the same strategy with a fixed 5% stop.
- `sma9_1min_atr` adds the 1-minute cadence and uses the ATR distance as the
  trail width as well.
- `sma9_1min_poll` keeps the 5% stop at the 1-minute cadence.
