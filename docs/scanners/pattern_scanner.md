# `pattern_scanner` — candlestick patterns on NIFTY spot

**One line:** when a completed NIFTY **spot** 5-minute candle matches a known
bullish or bearish pattern, buy the ATM CE (bullish) or ATM PE (bearish) and
manage the exit on **spot** with a trail and a fixed 12-point stop.

- **Status:** active
- **Cadence:** every 5 seconds
- **Stop:** fixed **12 NIFTY spot points**, after a 5-point spot trail
- **First reported day:** 2026-11-18 (older rows are excluded from reports)

## Why it exists

Every other scanner derives its signal and its stop from **option premium**.
`pattern_scanner` is the only strategy that reads the underlying directly:
patterns are detected on NIFTY spot candles, and the stop/trail are expressed
in index points. It answers a different question — "does the index pattern
predict the option move?" — and is therefore not directly comparable with the
premium scanners.

It is also the only scanner that is directional rather than independent-leg:
a bullish pattern buys CE, a bearish pattern buys PE. It is long-only on both
sides; there is no short CE and no short PE.

## Entry

- **Signal source:** completed NIFTY spot 5-minute candles only (the forming
  candle is never used for a signal).
- **Patterns:** roughly 37 bullish and 37 bearish candlestick patterns.
- **Mapping:** bullish → long ATM CE (nearest weekly expiry); bearish → long
  ATM PE.
- **Entry price:** the chosen option's **live LTP** on the tick that closes the
  spot candle — not the spot close, and never a stale or opposite-leg quote.
  Quotes older than `MAX_QUOTE_AGE_SEC` (20 s) are rejected, so a missed quote
  skips the entry rather than inventing a price.
- **Entry timestamp:** the actual tick time, not the signal candle's start.
- **One per key:** at most one active position per `pattern_name:instrument`.
- **Entry tick skip:** a position entered at a candle close is first managed on
  the following tick, never on its own entry tick.
- No new entries at or after 15:15 IST.

## Exit

Tick-level on NIFTY **spot**, trail first, then the fixed stop. Direction-aware:

**BULLISH (long CE)**

```
hwm = max(hwm, spot)
if hwm - entry_spot >= 5: stop = max(entry_spot, hwm - 5)
if hwm - entry_spot >= 6 and not be_locked:
    stop = max(stop, entry_spot + 2); be_locked = True
if stop > entry_spot and spot <= stop: exit   # TRAIL_STOP_EXIT
elif spot <= round(entry_spot - 12, 2): exit  # STOP_LOSS_SPOT
```

**BEARISH (long PE)**

```
lwm = min(lwm, spot)
if entry_spot - lwm >= 5: stop = min(entry_spot, lwm + 5)
if entry_spot - lwm >= 6 and not be_locked:
    stop = min(stop, entry_spot - 2); be_locked = True
if stop < entry_spot and spot >= stop: exit   # TRAIL_STOP_EXIT
elif spot >= round(entry_spot + 12, 2): exit  # STOP_LOSS_SPOT
```

- The stop is **always 12 index points**, independent of the NIFTY level — no
  percentage scaling at 18,000, 25,000 or 30,000.
- **Exit price:** the position's own option LTP at the moment spot breaches the
  stop, not the spot level and never the current ATM's opposite leg. A stale
  quote (>20 s) defers the exit until a fresh one arrives.
- No target, no candle-close exit, no session-end square-off.

## Runtime

| Item | Value |
|---|---|
| Live runner | `/opt/tradingai/scripts/pattern_scanner_live.py` |
| Engine | `/opt/tradingai/app/research/pattern_scanner.py` |
| User / unit | `ubuntu` / `pattern-scanner-live.service` |
| Working dir / PYTHONPATH | `/opt/tradingai` |
| DB | `/opt/tradingai/database/tradingai.db` |
| Tables | `pattern_scanner_positions`, `pattern_scanner_stop_changes` |
| Status file | `/opt/tradingai/data/pattern_scanner_status.json` |
| Log | `/opt/tradingai/logs/pattern_scanner_live.log` |
| API | `/api/pattern_scanner/*` (own namespace, not the 9-endpoint set) |
| Dashboard | `/live/pattern_scanner/` |
| Performance report | key `pattern_scanner`, label `Pattern`, from 2026-11-18 |

Unlike the premium scanners, it shares the main `app/` tree and the `ubuntu`
user. Its log line is `[ps-live] Kite connected...` followed by
`NFO instruments cached: <n> rows`.

## API

```
GET  /api/pattern_scanner/status
GET  /api/pattern_scanner/instruments
GET  /api/pattern_scanner/active-trades
GET  /api/pattern_scanner/closed-trades
GET  /api/pattern_scanner/pattern-summary
GET  /api/pattern_scanner/history
POST /api/pattern_scanner/start
POST /api/pattern_scanner/stop
```

The `start`/`stop` POSTs are ops-only and wrap `systemctl`; the dashboard does
not use them.

## State and restart behaviour

`stop_loss`, `hwm`, `lwm`, `entry_spot`, `be_locked`, `trailing_update_cnt`,
`mfe_points` and `mae_points` are written on every trail change and again on
exit. Each trail change is appended to `pattern_scanner_stop_changes`. Open
positions are reloaded on startup, so a restart resumes the trail correctly.

The runner quotes the current ATM CE/PE **and** every instrument with an active
position on every poll, so a position is still managed after the ATM band
moves. Quotes are fed to the engine **before** the spot tick, so each decision
uses this poll's price rather than the previous poll's.

## Ops

```bash
systemctl status pattern-scanner-live
tail -f /opt/tradingai/logs/pattern_scanner_live.log
curl -s https://tradingai.in/api/pattern_scanner/status
```

The token is read once at process start. `pattern-scanner-live` is in
`ALL_UNITS` of `refresh_token.sh`; a token refresh without a restart would
leave it logging `Incorrect api_key or access_token` (this happened on
2026-11-19 before the unit was added to the restart list).
