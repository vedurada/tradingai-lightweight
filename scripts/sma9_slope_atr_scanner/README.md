# SMA9 ATR Scanner (standalone, 5-second poll)

A paper-trading scanner that uses the **SMA9 entry** with a rising-average
filter and the **ATR-scaled stop / ATR-only trail** of `sma9_atr`. It was
renamed from `sma9_1min_atr` to `sma9_slope_atr` on 2026-11-20: the strategy id,
DB, service, user, log, API and dashboard all moved to the new identity, and the
old scanner was retired as an archive. The strategy behavior is v1.1.0: a
**5-second poll**, ATR-only trail and rising-SMA9 entry filter. It replaces the
retired `no_sma_trail` scanner slot.

* Directory: `/opt/tradingai/sma9_slope_atr_scanner`
* Database: `/opt/tradingai/database/sma9_slope_atr.db`
* Service: `tradingai-sma9-slope-atr-scanner.service`
* Log: `/opt/tradingai/logs/live_sma9_slope_atr_scanner.log`
* Strategy id: `sma9_slope_atr` (v1.1.0)
* Tables: `sma9_slope_atr_trades`, `sma9_slope_atr_open_positions`,
  `sma9_slope_atr_scan_state`
* Dashboard: `/live/sma9-slope-atr/`
* API: `/api/sma9-slope-atr/*`

It does not read, write, or restart any existing scanner. Paper only: no
broker order is ever placed.

## Entry

At each 5-second poll, for each of ATM CE and ATM PE, from that option's own
5-minute candles:

* A) previous **completed** candle CLOSE > SMA9
* B) current **forming** candle OPEN > SMA9
* C) current SMA9 > previous SMA9 (the 9-candle average is rising)

All three must hold. `SMA9 > LTP` is reported as information only and is not a
gate. At most one entry per 5-minute candle; entries are allowed only between
09:20 and 15:15 IST. Scanning starts at 09:00; 09:00–09:15 is warm-up only.
The exchange must have published the current forming candle before it is used.

C is a genuine extra filter: when the 9-candle window rolls, the average
changes by `(new close − dropped close) / 9`, so a close above the average
(condition A) does not guarantee that the average rose. Real-feed checks show
cases with A and B true but C false.

## Exit

1. **ATR-scaled initial stop**

   ```
   atr      = mean True Range of the option premium over 14 completed 5m candles
   distance = clamp(0.70 * atr, 5% * entry, 30% * entry)
   stop     = entry - distance
   ```

   When LTP <= stop, the trade is closed at the **actual live LTP**, not at
   the theoretical stop price (`STOP_LOSS_ATR`). If ATR is unavailable (fewer
   than 15 completed candles), the stop falls back to 10% of entry and
   `stop_source = 'fallback_pct'`.

2. **ATR-only trailing stop** — no fixed +5 activation and no breakeven lock:

   ```
   once peak > entry:
       stop = max(stop, peak - distance)   # same ATR distance, frozen at entry
   exit when LTP <= stop                   # TRAIL_STOP_EXIT at the LTP
   ```

   The stop can never ratchet down. Until price moves above entry, the initial
   ATR stop is the only exit, so a losing trade is never labelled as a trail
   exit.

3. No time-based or candle-close exit; a position is held until the ATR stop
   or the trail fires.

## State and restart

Open positions persist the entry, ATR, initial stop, ATR trail distance,
high-water mark and current trail stop. A same-session restart resumes the
same trade and rebuilds the trail from the ATR distance under the v1.1.0 rule;
the old breakeven-lock state is discarded. A position left over from an
earlier session is closed at the current LTP with `STALE_RECOVERY_EXIT` on
startup. The database is WAL-mode with a busy timeout so the read-only API can
query it while the scanner writes.

## Run

```
sudo systemctl status tradingai-sma9-slope-atr-scanner
sudo journalctl -u tradingai-sma9-slope-atr-scanner -n 50
tail -f /opt/tradingai/logs/live_sma9_slope_atr_scanner.log
```

## Verify

```
python3 tests/test_sma9_slope_atr_engine.py
sudo python3 ops/dryrun_market_open.py
sudo python3 ops/real_feed_check.py      # read-only, real Kite data
```

The dry run uses a throw-away database and a fake feed; it never touches the
live DB or the broker. Set `SMA9_SLOPE_ATR_RUNNER` to test a local copy of the
runner instead of the deployed one.

On the first live day, `ops/post_open_check.sh [HH:MM]` waits until the given
IST time (default 09:22), then samples the unit, log, heartbeat cadence, ATR
stop/trail state, trades, open positions and API into
`/tmp/post_open_sma9slopeatr_<date>.log`.

## Why

`no_sma_trail` entered on a previous-5m-high breakout and trailed at a fixed 5
points. This scanner keeps the SMA9 entry, scales both the stop and the trail
to the option's own volatility, and now samples every 5 seconds like
`sma9_atr`. Its identity was kept unchanged so the existing database history,
dashboard and API continue to work.
