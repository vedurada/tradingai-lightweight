# SMA9 1-Minute ATR Scanner (standalone)

A paper-trading scanner that combines the **SMA9 entry** of
`sma9_1min_poll` with the **ATR-scaled stop** of `sma9_atr`, polled **once per
minute**, and trails at an ATR-scaled distance instead of a fixed 5 points.
It replaces the retired `no_sma_trail` scanner slot.

* Directory: `/opt/tradingai/sma9_1min_atr_scanner`
* Database: `/opt/tradingai/database/sma9_1min_atr.db`
* Service: `tradingai-sma9-1min-atr-scanner.service`
* Log: `/opt/tradingai/logs/live_sma9_1min_atr_scanner.log`
* Strategy id: `sma9_1min_atr`
* Tables: `sma9_1min_atr_trades`, `sma9_1min_atr_open_positions`,
  `sma9_1min_atr_scan_state`
* Dashboard: `/live/sma9-1min-atr/`
* API: `/api/sma9-1min-atr/*`

It does not read, write, or restart any existing scanner. Paper only: no
broker order is ever placed.

## Entry (same as sma9_1min_poll)

At each 1-minute poll, for each of ATM CE and ATM PE, from that option's own
5-minute candles:

* A) previous **completed** candle CLOSE > SMA9
* B) current **forming** candle OPEN > SMA9

Both must hold. Entry is a paper BUY at the live LTP on the first 1-minute
poll that sees A and B. There is no previous-high breakout condition and no
separate LTP > SMA9 gate. At most one entry per 5-minute candle; entries are
allowed only between 09:20 and 15:15 IST.

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

2. **ATR-scaled trailing stop** — the shape is the same as the other
   scanners (+5 activates, +6 locks entry + 2), but the ratchet distance is
   the ATR distance fixed at entry:

   ```
   once peak - entry >= 5:
       stop = max(stop, peak - distance)      # distance from the entry stop
   once peak - entry >= 6:
       stop = max(stop, entry + 2)            # one-time breakeven lock
   exit when LTP <= stop and stop > entry     # TRAIL_STOP_EXIT at the LTP
   ```

   Activation and the ratchet are applied in the **same** poll, so a 60-second
   sample that jumps from below +5 to +13 immediately gets `peak - distance`
   rather than sitting at breakeven until the next minute.

3. No time-based or candle-close exit; a position is held until the ATR stop
   or the trail fires.

## State and restart

Open positions persist the entry, ATR, initial stop, ATR trail distance,
high-water mark, current trail stop and breakeven flag. A same-session
restart resumes the same trade and the same trail; it does not reset the peak,
close at the entry candle's close, or re-enter the candle. A position left
over from an earlier session is closed at the current LTP with
`STALE_RECOVERY_EXIT` on startup. The database is WAL-mode with a busy timeout
so the read-only API can query it while the scanner writes.

## Run

```
sudo systemctl status tradingai-sma9-1min-atr-scanner
sudo journalctl -u tradingai-sma9-1min-atr-scanner -n 50
tail -f /opt/tradingai/logs/live_sma9_1min_atr_scanner.log
```

## Verify

```
python3 tests/test_sma9_1min_atr_engine.py
sudo python3 ops/dryrun_market_open.py
sudo python3 ops/real_feed_check.py      # read-only, real Kite data
```

The dry run uses a throw-away database and a fake feed; it never touches the
live DB or the broker. Set `SMA9_1MIN_ATR_RUNNER` to test a local copy of the
runner instead of the deployed one.

On the first live day, `ops/post_open_check.sh [HH:MM]` waits until the given
IST time (default 09:22), then samples the unit, log, heartbeat cadence, ATR
stop/trail state, trades, open positions and API into
`/tmp/post_open_sma91matr_<date>.log`.

## Why

`no_sma_trail` entered on a previous-5m-high breakout and trailed at a fixed 5
points. This scanner keeps the SMA9 entry that already works, scales both the
stop and the trail to the option's own volatility, and samples once a minute
so the two ATR scanners (`sma9_atr`, 5s, and this one, 60s) can be compared
without changing either one.
