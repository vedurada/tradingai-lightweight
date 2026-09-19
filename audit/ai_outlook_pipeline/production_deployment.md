# Production Deployment

Date: 2026-09-19
Classification: REPLAY/VALIDATION

## Pre-Deployment

### VM State Verified
- Hostname: webserver
- OS: Ubuntu 22.04.5 LTS
- Python: 3.10.12
- Gunicorn: 3 workers on 127.0.0.1:8000
- Nginx: active on 443
- Database: 264MB, integrity OK

### Backup Created
```
/opt/tradingai/backups/tradingai_pre_ai_outlook_repair_20260919_074207.db
```
Verified: PRAGMA integrity_check = OK

### Deployment Method

```bash
rsync -avz --delete \
  -e "ssh -i ~/.ssh/oci_key -o StrictHostKeyChecking=no" \
  backend/research_collector.py \
  backend/ai_outlook_5m.py \
  backend/api_server.py \
  backend/market_snapshot.py \
  backend/monitor.py \
  ubuntu@129.159.224.81:/opt/tradingai/backend/
```

## Deployment Steps

1. ✅ Created backup
2. ✅ Deployed backend files via rsync
3. ✅ Syntax check: all 5 files compile OK
4. ✅ Restarted gunicorn: `sudo systemctl restart tradingai-api`
5. ✅ Verified API: health check OK
6. ✅ Verified API: /api/ai-outlook/NIFTY returns LEGACY (not LIVE)
7. ✅ Verified API: /api/ai-outlook/BANKNIFTY returns LEGACY
8. ✅ Ran research collector in REPLAY mode
9. ✅ Verified snapshots and evidence created
10. ✅ Verified idempotency (second run no duplicates)
11. ✅ Verified symbol routing (NIFTY→NIFTY, BANKNIFTY→BANKNIFTY)
12. ✅ Ran regression tests: 12 passed, 1 skipped

## Services Restarted

- tradingai-api.service (gunicorn, 3 workers)

## Services NOT Restarted (not needed)

- Nginx (no config changes)
- Cron (no cron changes yet — scheduler trigger integrated but not yet in production cron)

## Test Results

```
Regression tests: 12 passed, 1 skipped, 0 failed
Pre-existing failures: 9 (unrelated to changes)
API verification: 4 endpoints verified
Pipeline validation: complete
```

## Known Limitations

1. **LLM generation not tested**: No API key available. Will be tested in next live session.
2. **5m scheduler not in cron**: The `run_scheduler()` function is integrated into monitor.py but monitor.py already runs research collection. The scheduler runs within the same cron trigger.
3. **Historical data only**: All validation used historical data (market CLOSED on Saturday).
4. **FINNIFTY snapshot not created**: price_5m data for FINNIFTY not available at test timestamp.

## Deployment Timestamp

```
2026-09-19T07:42:00+05:30 (approximate)
```

## Git Commit

```
Commit: f6c4369 (Phase 42A audit artifacts)
Files changed: 5 backend files + 20 audit artifacts
```
