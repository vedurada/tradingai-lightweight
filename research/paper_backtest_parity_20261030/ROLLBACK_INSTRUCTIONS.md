# Rollback Instructions

## Date
2026-10-30

## Host
webserver / Linux / x86_64 / ubuntu / /opt/tradingai (Oracle VM)

## Backup Location

`/opt/tradingai/backups/paper_backtest_parity_20261030_20261030_145731/`

## Files to Roll Back

| File | Backup Location | Pre-change SHA256 |
|------|-----------------|-------------------|
| scripts/paper_scalp_live.py | backup_dir/scripts/paper_scalp_live.py | fa7dc0810bfcd384654a0049d932dd09a1ccc012d6d89d14a0788cb1a7821a51 |

## Rollback Procedure

### Step 1: Stop the watcher service

```bash
sudo systemctl stop tradingai-paper-scalp-live.service
```

### Step 2: Kill any running watcher processes

```bash
pkill -f "scripts/paper_scalp_live.py" 2>/dev/null || true
```

### Step 3: Restore file from backup

```bash
BACKUP_DIR=/opt/tradingai/backups/paper_backtest_parity_20261030_20261030_145731
cp -a "$BACKUP_DIR/scripts/paper_scalp_live.py" /opt/tradingai/scripts/paper_scalp_live.py
```

### Step 4: Verify checksum

```bash
sha256sum /opt/tradingai/scripts/paper_scalp_live.py
# Expected: fa7dc0810bfcd384654a0049d932dd09a1ccc012d6d89d14a0788cb1a7821a51
```

### Step 5: Restart the service

```bash
sudo systemctl start tradingai-paper-scalp-live.service
```

### Step 6: Verify service is running

```bash
systemctl status tradingai-paper-scalp-live.service
```

## Database Rollback

No database changes were made. No database rollback needed.

## What Rollback Would Re-Enable

Rolling back would re-introduce the premature signal expiration defect:
- Signals with entry_time=None would fall back to signal_time in `_entry_time_guard()`
- Entry window would be 5 minutes after signal instead of 5 minutes after entry candle
- Valid signals would expire before trades could be created
- Approximately 20 signals expired without trades on 2026-10-29 and 2026-10-30 due to this defect

## Verification After Rollback (if needed)

```bash
# Verify syntax
python3 -m py_compile /opt/tradingai/scripts/paper_scalp_live.py

# Verify service is running
systemctl is-active tradingai-paper-scalp-live.service
```
