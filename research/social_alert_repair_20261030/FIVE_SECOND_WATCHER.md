# Five-Second Watcher

## Date
2026-10-30

## Host
webserver / Linux / x86_64 / ubuntu / /opt/tradingai (Oracle VM)

## Watcher Implementation

The live notification watcher (`scripts/tg_alerts.py --watch`) has been converted
from a cron-triggered one-shot script (1-minute polling) to a persistent systemd
service with an internal 5-second polling loop.

## Systemd Service

| Property | Value |
|----------|-------|
| Service name | `tradingai-scalp-alerts.service` |
| Service file | `/etc/systemd/system/tradingai-scalp-alerts.service` |
| Type | simple |
| User | ubuntu |
| Working directory | /opt/tradingai |
| ExecStart | `/usr/bin/python3 /opt/tradingai/scripts/tg_alerts.py --watch` |
| Restart | always |
| RestartSec | 10 seconds |
| Logs | `/opt/tradingai/logs/scalp_alerts.log`, `/opt/tradingai/logs/scalp_alerts.err.log` |

## Polling Interval

| Property | Value |
|----------|-------|
| Poll interval | 5 seconds |
| Implementation | `time.sleep(5)` inside `while True` loop in `do_watch()` |
| Measurement | Polling time logged per cycle as `poll_ms` |

## Market Hours Handling

| Property | Value |
|----------|-------|
| Market days | Monday-Friday (weekday < 5) |
| Market hours | 09:15-15:30 IST |
| Entry cutoff | 15:25 IST |
| Outside market hours | Watcher sleeps and re-checks every 5 seconds |
| Timezone | Asia/Kolkata (IST) |

Implementation in `do_watch()`:

```python
weekday = now.weekday()  # 0=Mon, 6=Sun
is_market_hours = weekday < 5 and _entry_window_open(now)
```

Where `_entry_window_open()` returns `(now.hour, now.minute) <= (15, 25)`.

## Concurrency Protection

| Property | Value |
|----------|-------|
| Lock file | `/tmp/tg_watch.lock` |
| Lock mechanism | `O_CREAT | O_EXCL | O_WRONLY` |
| Stale lock recovery | Locks older than 600 seconds are auto-removed |
| Cleanup | `atexit` handler removes lock on exit |

## Exception Handling

| Scenario | Behavior |
|----------|----------|
| API poll failure | Logged, continue to next instrument |
| Signal processing failure | Logged, continue to next signal |
| Telegram delivery failure | Recorded as FAILED in notification_events, retry on next cycle |
| Facebook delivery failure | Recorded as FAILED, does not affect Telegram |
| Paper monitor failure | Logged, does not affect watcher |
| Lock acquisition failure | Running unlocked (with warning) |

## Logging

Each poll cycle logs:
- `poll_ms` - Time spent polling the API
- `create_ms` - Time spent creating notifications
- `alert_ms` - Time spent sending alerts
- Signal delivery status (sent/skipped)
- Exit delivery status (sent/skipped)

Example log output:
```
[poll_ms=401.1 create_ms=0.0 alert_ms=0.0]
signal sent for 2026-10-30|BANKNIFTY|BEAR|2026-10-30T14:40:00+05:30 (tg=True, fb=False)
BANKNIFTY signal 2026-10-30T14:15:00+05:30 skipped: stale entry 2026-10-30T14:20:00+05:30
```

## Signal Discovery Delay

| Metric | Value |
|--------|-------|
| Maximum detection delay | 5 seconds (poll interval) + processing time |
| Typical detection delay | < 5 seconds |
| Signal freshness check | 20 minutes (STALE_ENTRY_MIN) |
| Entry cutoff | 15:25 IST |

## Cron Changes

The cron job for `tg_alerts.py --watch` (every minute during 9-15) has been
removed from crontab. The `--reconcile` job at 09:10 remains for daily
reconciliation of missed alerts.

## Verification

The watcher was tested by running `timeout 8 python3 scripts/tg_alerts.py --watch`
and confirmed to:
1. Start and print "paper_scalp_live watcher started (5-second polling)"
2. Poll the API every 5 seconds
3. Skip stale signals (>20 min old)
4. Send ENTRY notifications for new valid signals
5. Record delivery status in notification_events
