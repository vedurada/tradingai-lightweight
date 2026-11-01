# Changes and Backups

## Date
2026-10-30

## Host
webserver / Linux / x86_64 / ubuntu / /opt/tradingai (Oracle VM)

## Backup Location

`/opt/tradingai/backups/social_alert_5sec_20261030_20261030_143637/`

## Backup Contents

| File | SHA256 (pre-change) |
|------|---------------------|
| scripts/tg_alerts.py | f01077365730f0089825e076b219f53f4efb4c589ae7f529ca4be054ad451e6e |
| scripts/fb_post.py | 8bb9ef1307390400b777a4d19ff951e0e8268df85ae621c4e15bfc5c8a0656e5 |
| scripts/paper_scalp_live.py | fa7dc0810bfcd384654a0049d932dd09a1ccc012d6d89d14a0788cb1a7821a51 |
| tradingai.db (SQLite backup) | N/A |

## Files Modified

| File | Change | SHA256 (post-change) |
|------|--------|---------------------|
| scripts/tg_alerts.py | 1. init_notification_schema: Added event_type column, UNIQUE(signal_id, channel, event_type), migration logic 2. _is_delivered: Added channel and event_type parameters 3. do_watch: Rewritten as 5-second polling loop with ENTRY/EXIT alerts, PENDING/DELIVERED/FAILED tracking | To be recorded after deployment |

## New Files

| File | Description |
|------|-------------|
| /etc/systemd/system/tradingai-scalp-alerts.service | Systemd service for 5-second watcher |
| /opt/tradingai/research/social_alert_repair_20261030/ | Report directory |

## Database Changes

| Change | Details |
|--------|---------|
| Table | notification_events (additive migration) |
| Column added | event_type TEXT NOT NULL DEFAULT 'ENTRY' |
| Constraint changed | UNIQUE(signal_id, channel) → UNIQUE(signal_id, channel, event_type) |
| Existing rows | 7 rows migrated with event_type='ENTRY' |
| Data modifications | None |

## Cron Changes

| Cron Entry | Action |
|------------|--------|
| `* 9-15 * * 1-5 ... tg_alerts.py --watch` | Removed (replaced by systemd service) |
| `10 9 * * 1-5 ... tg_alerts.py --reconcile` | Kept (daily reconciliation) |

## Systemd Services

| Service | Status |
|---------|--------|
| tradingai-scalp-alerts.service | Active (running) |
| tradingai-paper-scalp-live.service | Active (unchanged) |
| tradingai-api.service | Active (unchanged) |

## Safety Properties Preserved

- No Git usage
- No strategy parameter changes
- No entry/exit rule changes
- No disabled monitoring timer enabled
- All historical signals, trades, and notification records preserved
- All source files backed up before modification
- SQLite backup created using `.backup` mechanism
