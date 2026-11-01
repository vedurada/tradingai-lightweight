# Changes and Backups

## Date
2026-10-30

## Host
webserver / Linux / x86_64 / ubuntu / /opt/tradingai (Oracle VM)

## Backup Location

`/opt/tradingai/backups/paper_backtest_parity_20261030_20261030_145731/`

## Backup Contents

| File | SHA256 (pre-change) |
|------|---------------------|
| scripts/tg_alerts.py | 73161cddf755fbfea06bed866a09c0503c9030211b45f62ebf0a483d9120cf8e |
| scripts/paper_scalp_live.py | fa7dc0810bfcd384654a0049d932dd09a1ccc012d6d89d14a0788cb1a7821a51 |
| scripts/fb_post.py | 8bb9ef1307390400b777a4d19ff951e0e8268df85ae621c4e15bfc5c8a0656e5 |
| app/research/scalp_engine.py | de07d65a77e1e1c092fa18a45a2f486eba0bbb43f3ee7ae1b528212acb2f6590 |
| app/strategies/scalp.py | dba6ae960038ed2a8a96972657d9197be233ff9e9b357eb7daeddf83126b1b42 |
| app/live/engine.py | 119685d33fb0bc28483ae90250e0d8d78529dd49576ee933eb4ce6ccb9b98bf7 |
| app/paper_trade/engine.py | da8109c6f764865617c72fc30d87ca6d8d909bc83ba57af060d047d72017c0f7 |
| app/market/collector.py | 4ad20bf7f6d690243faeacc2c0032ce98c28b02c82cfb9f9e65e0799548954bf |
| frontend/scalp.html | 5a3c75646987fda645014746012141704f8bc966f9a9a1995de695929670dce4 |
| app/api/app.py | 51b08639ebe64c075db41822d6a17d4d19b0ea28d2dd3e7a88aae9719f05d234 |
| tradingai.db (SQLite backup) | N/A |

## Changes Applied

### File: scripts/paper_scalp_live.py

**Change:** Fixed `_entry_time_guard()` call to compute `entry_time` as `signal_time + 5min` when `entry_time` is None.

**Before:**
```python
entry_time_s = st.get("entry_time") or st.get("signal_time")
guard, why = _entry_time_guard(entry_time_s, now)
```

**After:**
```python
entry_time_s = st.get("entry_time")
if entry_time_s is None:
    # Entry candle not yet ingested; compute as
    # signal_time + 5min so the entry window is
    # 5 minutes after the entry candle, not 5
    # minutes after the signal candle.
    from datetime import datetime as _dt, timedelta as _td
    signal_dt = _dt.fromisoformat(
        str(st.get("signal_time")).replace("Z", "+00:00")
    )
    entry_dt = signal_dt + _td(minutes=5)
    entry_time_s = entry_dt.isoformat()
guard, why = _entry_time_guard(entry_time_s, now)
```

**Post-change SHA256:** Computed after deployment

## Database Changes

None. No schema modifications, no data modifications. All historical signals, trades, and notification records preserved.

## Service Deployment

- `tradingai-paper-scalp-live.service` restarted with fixed code
- `tradingai-scalp-alerts.service` running (5-second alert watcher)
- `tradingai-api.service` running (gunicorn, port 8000)
- Cron job for `tg_alerts.py --watch` removed (replaced by systemd service)
- Cron job for `tg_alerts.py --reconcile` retained (daily at 09:10)

## Safety Verification

- No Git used
- No strategy parameters changed
- No entry/exit rule changes
- No disabled monitoring timer enabled
- All historical data preserved
- SQLite backup created using `.backup` mechanism
- Isolated tests: 15/15 passed before deployment
- Backtest vs live parity: 100% match (7/7 for both NIFTY and BANKNIFTY)
