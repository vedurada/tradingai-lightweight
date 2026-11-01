# Phase 5.6A — Backup and Restore Test Results

## Test Environment

- Test database: `/opt/tradingai/research/phase56a_readiness_20261029_204000/test_tradingai.db` (isolated)
- Backup database: `/opt/tradingai/research/phase56a_readiness_20261029_204000/test_tradingai_backup.db`
- Restore database: `/opt/tradingai/research/phase56a_readiness_20261029_204000/test_tradingai_restore.db`
- Failed restore: `/opt/tradingai/research/phase56a_readiness_20261029_204000/test_tradingai_failed_restore.db` (corrupt)

## Test Results

| Test ID | Scenario | Expected | Actual | Result | Evidence |
|---------|----------|----------|--------|--------|----------|
| B1 | SQLite backup via backup API | Integrity OK, counts match | Integrity=ok, match=True | PASS | test_tradingai_backup.db |
| B2 | SQLite restore via backup API | Integrity OK, counts match | Integrity=ok, match=True | PASS | test_tradingai_restore.db |
| B3 | Simulated failed restore (corrupt DB) | Integrity check fails | Integrity check failed | PASS | test_tradingai_failed_restore.db |
| B4 | Original test DB unchanged after backup/restore | Counts and integrity match | Match=True | PASS | test_tradingai.db |

## Proposed Production Backup Procedure

### Prechecks
1. Verify production DB exists: `/opt/tradingai/database/tradingai.db`
2. Check `PRAGMA integrity_check` → must return `ok`
3. Check free disk space: `df -h /opt/tradingai/` (minimum 2x DB size)
4. Verify no active writes: check `PRAGMA wal_checkpoint(PASSIVE)` returns `ok`

### Backup Command
```bash
python3 -c "
import sqlite3
src = sqlite3.connect('/opt/tradingai/database/tradingai.db')
dst = sqlite3.connect('/opt/tradingai/backups/tradingai_YYYYMMDD_HHMMSS.db')
src.backup(dst)
dst.commit()
dst.close()
src.close()
"
```

### Post-Backup Verification
1. `PRAGMA integrity_check` on backup → must return `ok`
2. Compare row counts: `paper_trades`, `scalp_signals`, `paper_scalp`, `daily_trade_locks`
3. Compare file size: backup ≥ original
4. Verify backup is readable (open connection, run SELECT)

### Restore Procedure
1. Stop all services: gunicorn, paper_scalp_live
2. Copy backup to production path: `cp backup.db database/tradingai.db`
3. Verify `PRAGMA integrity_check` → `ok`
4. Verify row counts match pre-backup
5. Restart services
6. Verify API responds: `curl http://127.0.0.1:8000/api/health`

### Safety Notes
- **NOT TESTED on production DB** — this procedure is documented but not rehearsed
- Do NOT overwrite production DB during any test phase
- Always verify backup before restoring
- Keep at least 3 most recent backups
- Backup directory: `/opt/tradingai/backups/` (already exists with 443 files)
