# Changes and Backups

## Date
2026-10-30

## Host
webserver / Linux / x86_64 / ubuntu / /opt/tradingai (Oracle VM)

## Backup Location

/opt/tradingai/backups/final_trade_lifecycle_20261030_20261030_152331/

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
| frontend/backtest.html | 9a108f447fecb7a0721a82cd6d302c12c09f5586bd4c16ff2d0e31f17ecd7c01 |
| app/api/app.py | 51b08639ebe64c075db41822d6a17d4d19b0ea28d2dd3e7a88aae9719f05d234 |
| tradingai.db (SQLite backup) | N/A |

## Changes Applied

### File: scripts/paper_scalp_live.py

**Change:** Fixed entry_time computation: when entry_time is None, compute as signal_time + 5min.

**Before:**
entry_time_s = st.get("entry_time") or st.get("signal_time")

**After:**
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

**Root Cause:** When entry_time is None (entry candle not yet ingested into market_candles_5m),
the code fell back to signal_time in _entry_time_guard(). This made entry_close = signal_time + 5min
instead of entry_time + 5min (= signal_time + 10min). Signals expired 5 minutes too early.

**Impact:** 20 signals expired without trades on 2026-10-29 and 2026-10-30 due to this defect.
**Post-change SHA256:** 7712e6d9c1f83892fce0627f715a441e0b518ea1207ddd6345a8e79ea79ea7feb6c1

## Database Changes

None. No schema modifications, no data modifications. All historical signals, trades, and notification records preserved.

## Service Deployment

| Service | Status |
|---------|--------|
| tradingai-paper-scalp-live.service | Active (running fixed code) |
| tradingai-scalp-alerts.service | Active (5-second alert watcher) |
| tradingai-api.service | Active (gunicorn, port 8000) |

## Cron Changes

| Cron Entry | Action |
|------------|--------|
| * 9-15 * * 1-5 ... tg_alerts.py --watch | Removed (replaced by systemd service) |
| 10 9 * * 1-5 ... tg_alerts.py --reconcile | Retained (daily at 09:10) |

## Safety Verification

- No Git used
- No strategy parameters changed
- No entry/exit rule changes
- No disabled monitoring timer enabled
- All historical signals, trades, and notification records preserved
- All source files backed up before modification
- SQLite backup created using .backup mechanism
- Isolated tests: 15/15 passed before deployment
- Backtest vs live parity: 100% match (7/7 for both NIFTY and BANKNIFTY)

## Rollback

Restore from backup:
BACKUP_DIR=/opt/tradingai/backups/final_trade_lifecycle_20261030_20261030_152331
cp -a "/scripts/paper_scalp_live.py" /opt/tradingai/scripts/paper_scalp_live.py
systemctl restart tradingai-paper-scalp-live.service
