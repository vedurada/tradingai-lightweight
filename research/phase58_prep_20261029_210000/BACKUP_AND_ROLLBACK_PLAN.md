# Phase 5.8 — Backup and Rollback Plan

## Previously Tested (Phase 5.6A)

| Test | Result | Evidence |
|------|--------|----------|
| SQLite backup via backup API | PASS | test_tradingai_backup.db |
| SQLite restore via backup API | PASS | test_tradingai_restore.db |
| Simulated failed restore (corrupt DB) | PASS | test_tradingai_failed_restore.db |
| Original test DB unchanged | PASS | test_tradingai.db |

## Proposed (Untested) Production Procedures

### Pre-Backup Checks

1. Verify production DB exists: `/opt/tradingai/database/tradingai.db`
2. Check `PRAGMA integrity_check` → must return `ok`
3. Check free disk space: `df -h /opt/tradingai/` (minimum 2x DB size)
4. Verify no active writes: `PRAGMA wal_checkpoint(PASSIVE)` returns `ok`
5. Verify service status: gunicorn and paper_scalp_live running

### Backup Command

```bash
python3 -c "
import sqlite3, datetime
src = sqlite3.connect('/opt/tradingai/database/tradingai.db')
dst_path = '/opt/tradingai/backups/tradingai_' + datetime.datetime.now().strftime('%Y%m%d_%H%M%S') + '.db'
dst = sqlite3.connect(dst_path)
src.backup(dst)
dst.commit()
dst.close()
src.close()
print('Backup created:', dst_path)
"
```

### Post-Backup Verification

1. `PRAGMA integrity_check` on backup → `ok`
2. Compare row counts: paper_trades, scalp_signals, paper_scalp, market_candles_5m
3. Compare file size: backup ≥ original
4. Verify backup is readable (open connection, run SELECT)

### Recovery Procedure

1. Stop all services: gunicorn, paper_scalp_live
2. Copy backup to production path: `cp backup.db database/tradingai.db`
3. Verify `PRAGMA integrity_check` → `ok`
4. Verify row counts match pre-backup
5. Restart services
6. Verify API responds: `curl http://127.0.0.1:8000/api/health`

### Feature-Flag Rollback

1. Set `HLC_ONLY_MODE=false` (or remove from environment/config)
2. Restart gunicorn
3. CPR engine resumes as default decision path
4. Existing HLC trades remain manageable (monitor() handles both branches)
5. No trade history deleted
6. No open trades abandoned

### Service Rollback

1. Stop paper_scalp_live service
2. Restart with previous configuration
3. Verify open positions recovered
4. Verify no duplicate trades created

### Post-Rollback Validation

1. API responds: `curl http://127.0.0.1:8000/api/decision`
2. Check decision source: should show CPR, not HLC
3. Open trades still monitored: `curl http://127.0.0.1:8000/api/paper/scalp`
4. Telegram alerts continue (cron unchanged)
5. DB integrity: `PRAGMA integrity_check` → ok

### Safety Notes

- **NOT TESTED on production DB** — procedure is documented but not rehearsed
- Do NOT overwrite production DB during any test phase
- Always verify backup before restoring
- Keep at least 3 most recent backups
- Backup directory: `/opt/tradingai/backups/` (already exists with 443 files)
