# `sma9_5min` — SMA9 premium scanner on a 5-minute poll

**One line:** an isolated copy of `sma9` with the same A+B entry and fixed-stop
rules, sampled once per aligned NIFTY 5-minute candle instead of every 5 seconds.

- **Status:** API and dashboard deployed on the VM; scanner service still staged (not running)
- **Cadence:** aligned 5-minute polls at `:00, :05, ... :55` +10 s
- **Stop:** fixed 5% of entry premium, after the same 5-point trail
- **First live day:** not yet live

## Why it exists

This scanner isolates the effect of sampling the baseline SMA9 rules once per
5-minute bar. It does not change signals, stops, symbols, persistence, or the
paper-only boundary. The original `sma9` scanner remains untouched.

## Entry

Identical to `sma9`, evaluated once per aligned 5m poll:

```
condition_a = previous completed candle CLOSE > SMA9
condition_b = current forming candle OPEN  > SMA9
signal      = condition_a AND condition_b
entry       = paper BUY at round(live LTP, 2)
```

- Entry window: `09:20 <= now < 15:15` IST.
- Scanning starts at 09:00 IST; 09:00–09:15 is warm-up only.
- At most one entry per 5-minute candle per option.
- CE and PE are evaluated independently; both may be open at once.
- The 09:15 candle is never entered.
- Because the poll happens 10 s after the boundary, the forming candle must
  already be published by the broker feed. If it is not, that poll is skipped
  rather than substituting the previous completed candle.

## Exit

The stop/trail state machine is the same as `sma9`, but it is observed once per
5-minute poll instead of every 5 seconds:

```
hwm = max(hwm, LTP)
if hwm - entry >= 5.0:
    stop = entry
    stop = max(stop, hwm - 5.0)
if hwm - entry >= 6.0 and not be_locked:
    stop = max(stop, entry + 2.0)
    be_locked = True

if stop > entry and LTP <= stop:       exit at LTP       # TRAIL_STOP_EXIT
elif LTP <= round(entry * 0.95, 2):    exit at that level # STOP_LOSS_5PCT
else: hold
```

- Trail exits use the sampled LTP at the breach.
- The trail is evaluated before the 5% stop.
- No target, no time-based exit, no session-end square-off.
- `hwm`, `stop` and `be_locked` are persisted on every ratchet, so a restart
  resumes the exact trail.
- Sampling at 5m means an intrabar stop/trail breach can only be observed at
  the next aligned poll. This is a deliberate cadence trade-off, not a fill
  guarantee.

## Cadence

```
POLL_SECONDS   = 300
POLL_OFFSET_SEC = 10
```

`next_poll_time()` floors to the current 5-minute boundary, adds the 10-second
publication offset, and advances one candle if that time has already passed.
The status snapshot reports:

```json
{"poll_seconds": 300, "poll_alignment": "5m_boundary_plus_10s"}
```

## Runtime

| Item | Value |
|---|---|
| Strategy id / type | `sma9_5min` / `SMA9_5MIN_BUY_ONLY` |
| Code | `/opt/tradingai/sma9_5min_scanner/` |
| Entrypoint | `app/live_sma9_5min_scanner.py` |
| Engine | `app/sma9_5min_engine.py` |
| User / unit | `sma95min` / `tradingai-sma9-5min-scanner.service` |
| DB | `/opt/tradingai/database/sma9_5min.db` |
| Tables | `sma9_5min_trades`, `sma9_5min_open_positions`, `sma9_5min_scan_state` |
| Log | `/opt/tradingai/logs/live_sma9_5min_scanner.log` |
| DB env override | `SMA9_5MIN_DB_PATH` |
| API | `/api/sma9-5min/*` (read-only, deployed) |
| Dashboard | `/live/sma9-5min/` (deployed) |
| Performance report | key `sma9_5min`, label `SMA9 5min` |
| Broker mapping | `live_sma9_5min_scanner.py` → `mstock` |

## Safety

- Paper only. No `place_order`, `order_id`, or broker write path.
- Broker access goes through the read-only gateway facade.
- The API and dashboard open the scanner DB in read-only mode.
- The scanner owns its DB, tables, log, service user, and status namespace.

## Relationships

- `sma9` is the unchanged 5-second baseline with identical rules.
- `pattern_scanner` also polls on an aligned 5m cadence, but its exits come
  from completed 5m option OHLC bars shared with the backtest.
- Other SMA variants keep their existing 5-second cadence and identities.
