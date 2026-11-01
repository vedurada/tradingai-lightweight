# Phase 5.18 — Paper-Run Operator Checklist

## Pre-Session (09:00 IST)

- [ ] Verify market is open (Mon-Fri, 09:15-15:30)
- [ ] Verify services: gunicorn, paper_scalp_live, market-data timer
- [ ] Verify DB integrity: PRAGMA integrity_check → ok
- [ ] Verify no experimental jobs running
- [ ] Create timestamped log file
- [ ] Record baseline DB row counts

## During Session (09:15-15:30)

- [ ] Monitor collector latency (every 30 min)
- [ ] Monitor signal detection (every 15 min)
- [ ] Monitor trade creation (every 15 min)
- [ ] Monitor rejected signals (every 30 min)
- [ ] Monitor open positions (every 15 min)
- [ ] Check for errors (every 15 min)

## Post-Session (15:30-16:00)

- [ ] Record final DB row counts
- [ ] Verify DB integrity
- [ ] Count signals detected vs trades created
- [ ] Count rejected signals by reason
- [ ] Verify no duplicate trades
- [ ] Save all logs and API responses
- [ ] Reconcile with EOD backtest

## Abort Conditions

- Production write outside expected paths
- Stale data accepted for trade creation
- Duplicate trades created
- DB integrity failure
- Service crash
- Error rate > 10%
