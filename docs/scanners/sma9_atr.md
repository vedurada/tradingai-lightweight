# `sma9_atr` — SMA9 entry, daily regime gate and ATR-only trail

**One line:** the `sma9` entry, but entries are allowed only in the direction of
a daily NIFTY spot regime, the initial stop is sized from the option premium's
own ATR, and the trail uses that same ATR distance instead of a fixed 5 points.

- **Status:** active, v1.1.0
- **Cadence:** every 5 seconds, offset 0
- **Stop:** `clamp(0.70 × ATR14, 5%, 30% of entry)`, filled at the live LTP
- **Trail:** `peak − ATR distance`, active once price is above entry; no fixed
  5-point activation and no breakeven lock
- **Regime:** BULLISH → CE only, BEARISH → PE only, NEUTRAL → no new entries;
  refreshed every 15 minutes from completed 5-minute NIFTY spot candles
- **First live day:** 2026-11-19 (v1.1.0 applied 2026-11-20)

## Why v1.1.0

On 19–20 Nov 2026 the index rose +255 and +336 points, but CE entry PnL across
the fleet was strongly positive while PE PnL was negative every day. The shared
fixed `TRAIL = 5 / ACTIVATE = 5 / BE +6 → +2` also closed 89–95% of trail trades
as winners at an average of only 4–6 points, leaving most of the trend on the
table. This scanner now filters the wrong side of the day and lets winners trail
at the option's own volatility width. No other scanner was changed.

## Entry

Identical SMA9 signal to `sma9`, using the option's own 5-minute candles:

```
condition_a = previous completed candle CLOSE > SMA9
condition_b = current forming candle OPEN  > SMA9
signal      = condition_a AND condition_b
entry       = paper BUY at round(live LTP, 2)  -- only if the regime allows this option
```

No previous-high breakout and no separate LTP > SMA9 gate. At most one entry
per 5-minute candle per option; entry window `09:20 <= now < 15:15` IST.
Scanning starts at 09:00 IST; the first signal candle is 09:15, so the first
possible entry is 09:20. 09:00–09:15 is warm-up only: no entry is evaluated and
no exit is managed.

## Daily regime gate

Evaluated from 09:20 IST onwards, using **completed** 5-minute NIFTY spot
candles only (never the forming candle):

```
price  = last completed spot close
vwap   = volume-weighted average of today's completed spot closes
         (typical-price average when index candles have zero volume)
ema9   = EMA(9) over all completed spot history
```

| Regime | Condition | Entries |
|---|---|---|
| BULLISH | `price > vwap` and `price > ema9` and `ema9 rising` | CE only |
| BEARISH | `price < vwap` and `price < ema9` and `ema9 falling` | PE only |
| NEUTRAL | mixed signals or insufficient candles | none |

The gate is cached for `REGIME_RECHECK_MINUTES = 15` and requires at least one
completed session candle plus 10 completed candles in total. It is reported in
`/api/sma9-atr/status` as `regime` and per option as `entry_allowed` /
`gate_reason`. **Exits are never gated**: an open CE or PE position is managed
by its stops even if the regime flips to NEUTRAL or the opposite direction. If
spot regime candles cannot be fetched, the scanner fails closed to NEUTRAL and
reports the error.

## Stop

```
atr      = mean True Range of the option premium over the last 14 completed 5m candles
distance = clamp(0.70 * atr, 0.05 * entry, 0.30 * entry)
stop     = entry - distance
```

- The ATR is computed once, at entry, and frozen. The resulting distance is
  stored as `trail_distance` (and the source fields `atr_at_entry`,
  `stop_price`, `stop_k`, `stop_distance_pct`, `stop_source`).
- If LTP <= stop, the trade closes at the **actual live LTP**, not the
  theoretical stop price (`STOP_LOSS_ATR`). A fast move through the stop is
  recorded at the price the scanner actually saw.
- With fewer than 15 completed candles the stop falls back to 10% of entry
  (`stop_source='fallback_pct'`).
- The ATR uses the rolling last 14 completed candles from a 45-day fetch; it is
  not reset per day. At 09:15–09:20 it is still yesterday's 14 true ranges; the
  first entry around 09:21 includes the overnight-gap true range.

## Trail (ATR only)

```
distance = trail_distance captured at entry
hwm      = max(hwm, LTP)

if hwm > entry:
    stop = max(stop, hwm - distance)   # ratchet only upward

if LTP <= stop: exit at LTP            # TRAIL_STOP_EXIT
else: hold
```

- There is no `ACTIVATE = 5`, no `BE_LOCK_PROFIT = 6` and no
  `BE_LOCK_STOP = 2` on this scanner. Any new high above entry activates the
  trail at the ATR width.
- The trail never ratchets down. Before price has moved above entry the initial
  ATR stop is the only exit, so a losing trade is never labelled as a trail
  exit.
- No target, no candle-close exit, no session-end square-off.

## Runtime

| Item | Value |
|---|---|
| Strategy id / type | `sma9_atr` / `SMA9_ATR_STOP_BUY_ONLY` |
| Strategy version | `1.1.0` |
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

Persisted in `sma9_atr_open_positions`: `atr_at_entry`, `stop_price`, `stop_k`,
`stop_distance_pct`, `stop_source`, `trail_distance`, `hwm`, `trail_stop`,
`be_locked`. The `be_locked` column is retained only so v1.0.0 rows can be
restored; it is no longer used.

- Same-day restart resumes the exact stop, trail distance and high-water mark.
- A position from an earlier session is closed at the current LTP with
  `STALE_RECOVERY_EXIT` rather than carried overnight.
- `init_db()` adds `trail_distance` to existing v1.0.0 tables idempotently.

## Ops

```bash
systemctl status tradingai-sma9-atr-scanner
tail -f /opt/tradingai/logs/live_sma9_atr_scanner.log

# offline unit tests (engine + regime)
python3 /opt/tradingai/sma9_atr_scanner/tests/test_sma9_atr_engine.py

# fake clock/feed, temp DB: pre-market -> 09:00 -> BULLISH gate at 09:20 ->
# CE entry -> ATR stop -> re-entry -> restart recovery
python3 /opt/tradingai/sma9_atr_scanner/ops/dryrun_market_open.py

# real Kite path, writes nothing, also verifies the spot regime
python3 /opt/tradingai/sma9_atr_scanner/ops/real_feed_check.py
```

The unit is enabled, `Restart=always`, and in `ALL_UNITS` of
`refresh_token.sh`.

## Relationships

- `sma9` is the same entry with a fixed 5% stop and the shared 5-point trail;
  it has no regime gate.
- `sma9_5s_atr` uses the ATR distance as its trail width at a 5-second cadence,
  but keeps the other shared trail conditions and has no regime gate.
- `sma9_1min_poll` keeps the 5% stop at the 1-minute cadence.
- All other scanners are untouched by v1.1.0.
