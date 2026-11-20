# SMA9 5S Poll Scanner (identity retained)

A paper-trading scanner that keeps the original `sma9_1min_poll` identity but,
from v1.1.0, polls every **5 seconds** and uses the `sma9_atr` v1.1.0 exit model.
The entry rule is unchanged: A and B only, with no LTP gate, no rising-SMA9
filter and no regime gate. The old fixed 5% stop, 5-point trail, +5 activation
and +6 breakeven lock are removed.

* Directory: `/opt/tradingai/sma9_1min_poll_scanner`
* Database: `/opt/tradingai/database/sma9_1min_poll.db`
* Service: `tradingai-sma9-1min-poll-scanner.service`
* User: `sma91m`
* Log: `/opt/tradingai/logs/live_sma9_1min_poll_scanner.log`
* Strategy id: `sma9_1min_poll` (v1.1.0)
* Strategy type: `SMA9_1MIN_POLL_BUY_ONLY`
* Tables: `sma9_1min_poll_trades`, `sma9_1min_poll_open_positions`,
  `sma9_1min_poll_scan_state`
* Dashboard: `/live/sma9-1min-poll/`
* API: `/api/sma9-1min-poll/*`

The name, DB, service, user, API and page are unchanged. On 2026-11-20 the
behavior was upgraded in place: 60-second cadence -> 5-second cadence and
fixed SL/trail -> ATR stop/trail. Existing trade history stays in the same DB;
nullable ATR columns are added by an idempotent migration. No other scanner is
read, written or restarted. Paper only: no broker order is ever placed.

## Entry

At each 5-second poll, for each of ATM CE and ATM PE, from that option's own
5-minute candles:

* A) previous **completed** candle CLOSE > SMA9
* B) current forming candle OPEN > SMA9
* signal = A **and** B; paper BUY at `round(live LTP, 2)`

Both must hold. There is **no separate LTP > SMA9 gate**, no rising-SMA9
condition and no previous-high breakout. At most one entry per 5-minute candle
per option. CE and PE are evaluated independently.

Scanning starts at 09:00 IST, but the exchange publishes the first 5-minute
candle at 09:15. 09:00–09:15 is warm-up only: no entry is evaluated and no exit
is managed. Entries are allowed from 09:20 up to 15:15. There is no
candle-close exit and no time-based exit.

## Exit

The initial ATR stop and the ATR trail both use the option premium's ATR(14)
computed from completed 5-minute candles:

```text
distance = clamp(0.70 × ATR14, 5% × entry, 30% × entry)
stop_price = entry - distance
```

* If ATR is unavailable, a 10% fallback distance is used.
* **ATR stop:** if LTP <= `stop_price`, exit at the **actual live LTP** with
  reason `STOP_LOSS_ATR` (never at the theoretical stop price).
* **ATR trail:** once LTP makes a new high above entry, the stop ratchets to
  `peak - distance`. It never ratchets down.
* There is no fixed +5 activation and no +6 breakeven lock.
* Otherwise hold, including across candles and overnight.

## Isolation and operations

This scanner owns its DB, tables, log, service, user, code tree, API and page.
It shares only the host and the Kite credentials with the other scanners.

```bash
sudo systemctl status tradingai-sma9-1min-poll-scanner
sudo journalctl -u tradingai-sma9-1min-poll-scanner -n 50
tail -f /opt/tradingai/logs/live_sma9_1min_poll_scanner.log
```

Offline checks:

```bash
python3 tests/test_sma9_1min_poll_engine.py
python3 ops/dryrun_market_open.py
```

The dry run points `SMA9_1MIN_POLL_DB_PATH` at a throw-away file and never
touches the live DB.
