# Rollback Instructions

## Date
2026-10-30

## Host
webserver / Linux / x86_64 / ubuntu / /opt/tradingai (Oracle VM)

## Backup Location

`/opt/tradingai/backups/social_alert_5sec_20261030_20261030_143637/`

## Files to Roll Back

| File | Backup Location |
|------|-----------------|
| scripts/tg_alerts.py | backup_dir/scripts/tg_alerts.py |
| scripts/fb_post.py | backup_dir/scripts/fb_post.py |
| scripts/paper_scalp_live.py | backup_dir/scripts/paper_scalp_live.py |

## Pre-Change Checksums

| File | SHA256 |
|------|--------|
| scripts/tg_alerts.py | f01077365730f0089825e076b219f53f4efb4c589ae7f529ca4be054ad451e6e |
| scripts/fb_post.py | 8bb9ef1307390400b777a4d19ff951e0e8268df85ae621c4e15bfc5c8a0656e5 |
| scripts/paper_scalp_live.py | fa7dc0810bfcd384654a0049d932dd09a1ccc012d6d89d14a0788cb1a7821a51 |

## Rollback Procedure

### Step 1: Stop the alert watcher service

```bash
sudo systemctl stop tradingai-scalp-alerts.service
sudo systemctl disable tradingai-scalp-alerts.service
```

### Step 2: Remove any running watcher processes

```bash
pkill -f "tg_alerts.py --watch" 2>/dev/null || true
rm -f /tmp/tg_watch.lock
```

### Step 3: Restore files from backup

```bash
BACKUP_DIR=/opt/tradingai/backups/social_alert_5sec_20261030_20261030_143637
cp -a "$BACKUP_DIR/scripts/tg_alerts.py" /opt/tradingai/scripts/tg_alerts.py
cp -a "$BACKUP_DIR/scripts/fb_post.py" /opt/tradingai/scripts/fb_post.py
cp -a "$BACKUP_DIR/scripts/paper_scalp_live.py" /opt/tradingai/scripts/paper_scalp_live.py
```

### Step 4: Verify checksums

```bash
sha256sum /opt/tradingai/scripts/tg_alerts.py
# Expected: f01077365730f0089825e076b219f53f4efb4c589ae7f529ca4be054ad451e6e

sha256sum /opt/tradingai/scripts/fb_post.py
# Expected: 8bb9ef1307390400b777a4d19ff951e0e8268df85ae621c4e15bfc5c8a0656e5

sha256sum /opt/tradingai/scripts/paper_scalp_live.py
# Expected: fa7dc0810bfcd384654a0049d932dd09a1ccc012d6d89d14a0788cb1a7821a51
```

### Step 5: Remove the systemd service

```bash
sudo rm /etc/systemd/system/tradingai-scalp-alerts.service
sudo systemctl daemon-reload
```

### Step 6: Restore cron (if desired)

The cron job for `tg_alerts.py --watch` was removed. To restore:

```bash
(crontab -l 2>/dev/null; echo "* 9-15 * * 1-5 cd /opt/tradingai && /usr/bin/python3 scripts/mistake_guard.py >> /opt/tradingai/logs/mistake_guard.log 2>&1; /usr/bin/python3 scripts/tg_alerts.py --watch >> /opt/tradingai/logs/tg.log 2>&1") | crontab -
```

### Step 7: Database rollback (optional)

No database changes to existing tables were made. The `notification_events`
table is additive. To remove it:

```bash
sqlite3 /opt/tradingai/database/tradingai.db "DROP TABLE IF EXISTS notification_events;"
```

SQLite backup available at:
`/opt/tradingai/backups/social_alert_5sec_20261030_20261030_143637/tradingai.db`

## What Rollback Would Re-Enable

Rolling back would re-introduce:
1. 1-minute polling interval (cron-based) instead of 5 seconds
2. No ENTRY/EXIT event type tracking in notification_events
3. No independent Telegram/Facebook delivery tracking
4. Alert gating on paper trade existence (signals skipped if trade not yet created)
5. No persistent watcher service (cron-based, less reliable)

## Verification After Rollback

```bash
# Verify tg_alerts.py syntax
python3 -m py_compile /opt/tradingai/scripts/tg_alerts.py

# Verify cron is restored
crontab -l | grep tg_alerts

# Verify service is removed
systemctl list-units --type=service | grep scalp-alerts
# Should return empty
```
