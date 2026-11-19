# SMA9 1-Minute Poll Scanner

A paper-trading scanner with the **SMA9 entry rule** and the **same exits as
SMA9**, but polled **once per minute** instead of every 5 seconds. It replaces
the retired `no_sma` (previous-5m-high breakout) scanner slot.

* Directory: `/opt/tradingai/sma9_1min_poll_scanner`
* Database: `/opt/tradingai/database/sma9_1min_poll.db`
* Service: `tradingai-sma9-1min-poll-scanner.service`
* Log: `/opt/tradingai/logs/live_sma9_1min_poll_scanner.log`
* Strategy id: `sma9_1min_poll`
* Tables: `sma9_1min_poll_trades`, `sma9_1min_poll_open_positions`,
  `sma9_1min_poll_scan_state`
* Dashboard: `/live/sma9-1min-poll/`
* API: `/api/sma9-1min-poll/*`

It does not read, write, or restart any existing scanner. Paper only: no
broker order is ever placed.

## Entry (SMA9 only)

At each 1-minute poll, for each of ATM CE and ATM PE, from that option's own
5-minute candles:

* A) previous **completed** candle CLOSE > SMA9
* B) current **forming** candle OPEN > SMA9

Both must hold. Entry is a paper BUY at the live LTP on the first 1-minute
poll that sees A and B. There is no previous-high breakout condition and no
separate LTP > SMA9 gate.

At most one entry per 5-minute candle. Entries are allowed only between
09:20 and 15:15 IST, and the scanner refuses to evaluate the previous candle
as if it were forming when the exchange has not published the current candle
yet.

## Exit

1. **Fixed stop loss:** LTP <= entry - 5% of entry premium. The trade is
   closed at the theoretical stop price (`STOP_LOSS_5PCT`), matching SMA9.
2. **Trailing stop:** +5 activates breakeven, then ratchets at peak - 5; a
   one-time breakeven lock at +6 moves the stop to entry + 2. Fills at the
   live LTP (`TRAIL_STOP_EXIT`).
3. No time-based or candle-close exit; a position is held until the stop or
   the trail fires.

Stop-loss and trail are evaluated on the forming candle **once per minute**,
aligned to the wall-clock minute (`:00`). That is the only behavioural
difference from the 5-second SMA9 scanner: a 60s sample can miss an
intra-minute spike that a 5s scanner would have stopped on, and can hold a
position across a 5-minute boundary.

## State and restart

Open positions persist the entry, high-water mark, trail stop and breakeven
flag. A same-session restart resumes the same trade and the same trail; it does
not reset the peak, close at the entry candle's close, or re-enter the candle.
A position left over from an earlier session is not carried: it is closed at
the current LTP with `STALE_RECOVERY_EXIT` on startup. The database is WAL-mode
with a busy timeout so the read-only API can query it while the scanner
writes.

## Run

```
sudo systemctl status tradingai-sma9-1min-poll-scanner
sudo journalctl -u tradingai-sma9-1min-poll-scanner -n 50
tail -f /opt/tradingai/logs/live_sma9_1min_poll_scanner.log
```

## Verify

```
python3 tests/test_sma9_1min_poll_engine.py
sudo python3 ops/dryrun_market_open.py
```

The dry run uses a throw-away database and a fake feed; it never touches the
live DB or the broker.

## Why a separate scanner

`no_sma` was a different strategy (prev-high breakout, 5s poll) and its
history is not comparable to SMA9. Keeping this scanner isolated preserves
both histories and lets the 60s cadence be compared against the 5s SMA9
scanner without changing either one.

## Siblings

- `sma9_atr` — same SMA9 entry at the 5-second cadence, with a
  volatility-scaled (ATR) stop instead of the fixed 5% floor.
- `sma9_1min_atr` — this entry and cadence plus the ATR stop, with the ATR
  distance also used as the trail width.

Full per-scanner documentation: `docs/scanners/README.md` in the repo
(deployed at `/opt/tradingai/docs/scanners/`).
