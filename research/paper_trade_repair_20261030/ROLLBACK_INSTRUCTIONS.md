# Rollback Instructions

## Rollback Date
2026-10-30

## Host
webserver / Linux / x86_64 / ubuntu / /opt/tradingai (Oracle VM)

## Backup Location
`/opt/tradingai/backups/paper_trade_repair_20261030_20261030_130913/`

## Files to Roll Back
| File | Backup Location |
|---|---|
| scripts/paper_scalp_live.py | backup_dir/scripts/paper_scalp_live.py |
| app/research/scalp_engine.py | backup_dir/app/research/scalp_engine.py |
| app/strategies/scalp.py | backup_dir/app/strategies/scalp.py |

## Rollback Procedure

### Step 1: Stop the service
```bash
sudo systemctl stop tradingai-paper-scalp-live.service
```

### Step 2: Kill any remaining paper_scalp_live processes
```bash
pkill -f paper_scalp_live.py
```

### Step 3: Restore files from backup
```bash
BACKUP_DIR=/opt/tradingai/backups/paper_trade_repair_20261030_20261030_130913
cp -a "$BACKUP_DIR/scripts/paper_scalp_live.py" /opt/tradingai/scripts/paper_scalp_live.py
cp -a "$BACKUP_DIR/app/research/scalp_engine.py" /opt/tradingai/app/research/scalp_engine.py
cp -a "$BACKUP_DIR/app/strategies/scalp.py" /opt/tradingai/app/strategies/scalp.py
```

### Step 4: Verify checksums match pre-change values
| File | Expected SHA256 |
|---|---|
| scripts/paper_scalp_live.py | e3c61da1534b8ebc92fc7caf703d8273e2edeb239f91b35148429784becc97d6 |
| app/research/scalp_engine.py | 127c09d6dfcf4ac930d116d311d56b21005fff84acf40eab8aca01ba7aaf7e23 |
| app/strategies/scalp.py | 7711ad0683ebca88080e1ebbb5efcc3e8e61ba8a994f47282eb380de12f50c82 |

### Step 5: Restart the service
```bash
sudo systemctl start tradingai-paper-scalp-live.service
```

## Database Rollback
No database changes were made. No database rollback needed.
SQLite backup available at:
`/opt/tradingai/backups/paper_trade_repair_20261030_20261030_130913/tradingai.db`

## What Rollback Would Re-Enable
Rolling back would re-introduce all four defects:
1. is_stale() prematurely skipping valid signals (20-min threshold)
2. yfinance 404 errors for NIFTY/BANKNIFTY symbols (no entry price resolution)
3. _trade_for() IndexError on last-candle signals in run_opens_range()
4. Broken first_trigger import in strategies/scalp.py

Rollback should only be performed if the fixes cause unexpected production
issues. The fixes are minimal and do not change strategy rules, stop-loss
targets, or any validated trading parameters.