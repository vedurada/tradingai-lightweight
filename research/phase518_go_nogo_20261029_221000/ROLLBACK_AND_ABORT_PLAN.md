# Phase 5.18 — Rollback and Abort Plan

## Rollback (Feature Flag)

1. Set HLC_ONLY_MODE=false (or remove from env/config)
2. Restart gunicorn
3. CPR engine resumes as default
4. Existing HLC trades remain manageable
5. No trade history deleted
6. No open trades abandoned

## Rollback (Service)

1. Stop paper_scalp_live service
2. Restart with previous configuration
3. Verify open positions recovered
4. Verify no duplicate trades

## Abort Conditions (Immediate Stop)

1. Production write outside expected paths
2. Stale data (>20 min) accepted
3. Retroactive entry price used
4. Duplicate trades created
5. Service crash or unexpected restart
6. Telegram alerts sent during test
7. Error rate > 10% of cycles
8. DB integrity failure

## Post-Rollback Validation

1. API responds: curl http://127.0.0.1:8000/api/decision
2. Decision source: CPR (not HLC)
3. Open trades still monitored
4. Telegram alerts continue
5. DB integrity: ok
