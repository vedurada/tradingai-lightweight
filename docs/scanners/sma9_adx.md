# `sma9_adx` — SMA9 + ADX(14) premium scanner

**One line:** a 5-second paper scanner that buys ATM CE/PE when the previous
completed option candle closes above SMA9 **and** ADX(14) on completed option
candles is above 20, then uses the same `sma9` exits: a 5% initial stop plus a
5-point trailing stop that activates at +5 points with a one-time breakeven lock.

- **Status:** fully deployed on the VM — scanner service running, own DB, API, dashboard and performance-report entry live
- **Cadence:** every 5 seconds during market hours
- **Stop:** 5% of entry premium; `sma9`-style trail (activate +5, ratchet HWM - 5 points, BE lock +2 at +6)
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
sl_price = round(entry * 0.95, 2)          # checked every poll
hwm      = max(hwm, LTP)

if hwm - entry >= 5 and stop is None:  stop = entry       # trail activates
if hwm - entry >= 5 and stop is not None:
    stop = max(stop, hwm - 5)                             # ratchet up only
if not be_locked and hwm - entry >= 6:
    stop = max(stop or entry, entry + 2); be_locked = True
if stop is not None and stop > entry and LTP <= stop:
    exit at stop                                          # TRAIL_STOP_EXIT
elif LTP <= sl_price:
    exit at sl_price                                      # STOP_LOSS_5PCT
else: hold
```

- Initial stop is 5% below the entry premium; the trail stop starts unset.
- The trail activates once the premium is 5 points above entry, then ratchets
  to HWM - 5 points and never ratchets down.
- A one-time breakeven lock at entry + 2 points engages once HWM - entry >= 6.
- Only a strictly profitable stop (`stop > entry`) can trigger a trail exit.
  A breakeven stop does not exit; there is no candle-close exit in the live runner.
- No target, no time-based exit, no expiry forced exit.
- `hwm`, `stop` and `be_locked` are persisted on every poll, so a restart resumes
  the same state rather than rolling it back.

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

- Shares the 5-second cadence, isolation model and exit rules with `sma9`, but
  replaces the forming-open gate with ADX(14) > 20.
- `pattern_scanner` also trades premium, but detects entries on NIFTY spot
  candles and exits on premium ATR from completed 5m bars.
- Other SMA variants keep their existing entry rules and identities.
