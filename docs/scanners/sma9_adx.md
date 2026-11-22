# `sma9_adx` — SMA9 + ADX(14) premium scanner

**One line:** a 5-second paper scanner that buys ATM CE/PE when the previous
completed option candle closes above SMA9 **and** ADX(14) on completed option
candles is above 20, then exits on a 5% initial stop or a 5% HWM trailing stop.

- **Status:** fully deployed on the VM — scanner service running, own DB, API, dashboard and performance-report entry live
- **Cadence:** every 5 seconds during market hours
- **Stop:** fixed 5% of entry premium, ratcheted to HWM - 5%
- **First live day:** 2026-11-22

## Why it exists

The baseline `sma9` entry uses the previous close above SMA9 together with the
forming candle's open above SMA9. This variant replaces the forming-open gate
with a trend-strength filter: Wilder ADX(14) computed on the option's own
completed 5-minute premium candles. It asks whether the premium is trending,
not merely above its short moving average. `sma9` remains untouched.

## Entry

Both conditions must hold, identically for CE and PE:

```
condition_a = previous completed candle CLOSE > SMA9
condition_b = ADX(14) on completed candles > 20
signal      = condition_a AND condition_b
entry       = paper BUY at round(live LTP, 2)
```

- Entry window: `09:20 <= now < 15:15` IST.
- Scanning starts at 09:00 IST; 09:00–09:15 is warm-up only.
- At most one entry per 5-minute candle per option; CE and PE are independent.
- The forming candle is never used for SMA9 or ADX — only completed bars.
- `confirmation` (`LTP > SMA9`) is reported for context but does **not** gate
  the signal.
- ADX needs at least `2 * ADX_PERIOD` completed bars; before that, no entry.

### ADX(14)

Wilder smoothing on completed option-premium 5m bars:

```
TR  = max(high-low, |high-prev_close|, |low-prev_close|)
+DM = high-prev_high   when positive and greater than -DM, else 0
-DM = prev_low-low     when positive and greater than +DM, else 0
+DI = 100 * smoothed(+DM) / smoothed(TR)
-DI = 100 * smoothed(-DM) / smoothed(TR)
DX  = 100 * |+DI - -DI| / (+DI + -DI)
ADX = Wilder-smoothed mean of DX
```

The first TR/+DM/-DM sums are seeded over 14 bars, then smoothed with the
`prev - prev/14 + current` recurrence. Direction (+DI vs -DI) is irrelevant:
only trend *strength* matters, so CE and PE use the same threshold.

## Exit

```
initial_stop = round(entry * 0.95, 2)
hwm          = max(hwm, LTP)
trail_stop   = round(hwm * 0.95, 2)
stop         = max(initial_stop, trail_stop)

if stop > initial_stop and LTP <= stop:  exit at stop   # TRAIL_STOP_EXIT
elif LTP <= initial_stop:                exit at stop   # STOP_LOSS_5PCT
else: hold
```

- Initial stop is 5% below the entry premium.
- Once the premium rises, the stop ratchets to HWM - 5% and never ratchets down.
- A losing trade always exits on the 5% initial stop, never on the trail.
- No target, no candle-close exit, no time-based exit, no expiry forced exit.
- `hwm` and `stop` are persisted on every poll, so a restart resumes the same
  ratchet rather than rolling it back.

## Runtime

| Item | Value |
|---|---|
| Strategy id / type | `sma9_adx` / `SMA9_ADX_BUY_ONLY` |
| Code | `/opt/tradingai/sma9_adx_scanner/` |
| Entrypoint | `app/live_sma9_adx_scanner.py` |
| Engine | `app/sma9_adx_engine.py` |
| User / unit | `sma9adx` / `tradingai-sma9-adx-scanner.service` |
| DB | `/opt/tradingai/database/sma9_adx.db` |
| Tables | `sma9_adx_trades`, `sma9_adx_open_positions`, `sma9_adx_scan_state` |
| Log | `/opt/tradingai/logs/live_sma9_adx_scanner.log` |
| DB env override | `SMA9_ADX_DB_PATH` |
| API | `/api/sma9-adx/*` (read-only, deployed) |
| Dashboard | `/live/sma9-adx/` (deployed) |
| Performance report | key `sma9_adx`, label `SMA9 ADX` (deployed) |
| Broker mapping | `live_sma9_adx_scanner.py` → `mstock` |

The live-status payload exposes `adx_period` (14), `adx_threshold` (20.0), each
option's `adx` value and both condition flags; open positions and closed trades
persist `adx` / `adx_value`.

## Safety

- Paper only. No `place_order`, `order_id`, or broker write path.
- Broker access goes through the read-only gateway facade.
- The API and dashboard open the scanner DB in read-only mode.
- The scanner owns its DB, tables, log, service user, and status namespace.

## Relationships

- Shares the 5-second cadence and isolation model with `sma9`, but replaces the
  forming-open gate with ADX(14) > 20 and uses a 5% HWM trail.
- `pattern_scanner` also trades premium, but detects entries on NIFTY spot
  candles and exits on premium ATR from completed 5m bars.
- Other SMA variants keep their existing entry rules and identities.
