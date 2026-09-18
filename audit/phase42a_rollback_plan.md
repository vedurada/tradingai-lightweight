# Phase 42A — Rollback Plan

**Date**: 2026-09-17
**Phase 41**: FROZEN

---

## Rollback Trigger

If ANY deployment gate fails, or if Phase 42A causes production issues:

1. Stop rollback immediately
2. Follow this procedure
3. Verify Phase 41 state restored

## Rollback Procedure

### Step 1: Stop Services

```bash
sudo systemctl stop tradingai-api
```

### Step 2: Restore Database (if needed)

Since schema migration is additive, research tables can be safely left in place. However, if a full rollback is needed:

```bash
# Restore pre-deployment database
cp /opt/tradingai/backups/tradingai_pre_phase42a_YYYYMMDD_HHMMSS.db /opt/tradingai/database/tradingai.db

# OR: just remove research tables (safe, additive)
sqlite3 /opt/tradingai/database/tradingai.db \
  "DROP TABLE IF EXISTS research_setup_identity;
   DROP TABLE IF EXISTS research_reentry_log;
   DROP TABLE IF EXISTS research_ai_call_log;
   DROP TABLE IF EXISTS research_outcome_tracking;
   DROP TABLE IF EXISTS research_data_health;
   DROP TABLE IF EXISTS research_manifest;"
```

### Step 3: Restore Code

```bash
# Restore original api_server.py
cd /opt/tradingai/backend
git checkout HEAD -- api_server.py

# Restore original db_schema.py
git checkout HEAD -- db_schema.py

# Remove new modules
rm -f research_collector.py research_exports.py research_api.py deploy_validator.py
```

### Step 4: Restart Services

```bash
sudo systemctl daemon-reload
sudo systemctl restart tradingai-api
```

### Step 5: Verify

```bash
# API health
curl -s http://127.0.0.1:8000/api/health

# Research endpoints should 404
curl -s http://127.0.0.1:8000/api/research/summary

# Database should be Phase 41 schema
sqlite3 /opt/tradingai/database/tradingai.db \
  "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name LIKE 'research_%';"
```

Expected: 0 research tables, API healthy, no research endpoints.

## Rollback Safety

| Aspect | Safety |
|--------|--------|
| Database restore | SAFE (timestamped backup exists) |
| Code revert | SAFE (git checkout, no data loss) |
| Research tables | SAFE (drop is acceptable, contains no production data) |
| Schema | SAFE (additive, removal doesn't affect existing data) |
| Trading | SAFE (rollback restores Phase 41 trading behavior exactly) |

## Note

Because schema migration is additive, the simplest rollback is:
1. Stop gunicorn
2. Remove research tables (if desired)
3. Revert code changes (git checkout)
4. Start gunicorn

No database restore needed unless research tables somehow affected existing data (they won't).
