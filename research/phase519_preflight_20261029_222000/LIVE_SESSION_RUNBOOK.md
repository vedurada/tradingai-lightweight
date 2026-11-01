# Phase 5.19 — Live Session Runbook

## Pre-Session (09:00 IST)
- Verify market open (Mon-Fri, 09:15-15:30)
- Verify services: gunicorn, paper_scalp_live, market-data timer
- Verify DB integrity: PRAGMA integrity_check → ok
- Verify no experimental jobs
- Create timestamped log file
- Record baseline DB row counts

## Measurements
1. Candle timestamp (interval start)
2. Observation timestamp (ingested_at)
3. Signal timestamp (when detected)
4. Entry eligibility (_entry_time_guard result)
5. Signal age (now - signal_time)
6. Entry price availability (first observable time)
7. Rejected stale signals (count + reasons)
8. Duplicate signals (count + dedup verification)
9. Process restarts (recovery behavior)
10. Open trade monitoring (exit evaluation)
11. API/dashboard consistency (compare API vs DB)
12. Telegram consistency (alerts match trades)

## Evidence Retention
- Save API responses as JSON
- Save logs
- Record DB row counts before/after
- Save signal/trade snapshots

## Failure Handling
- Stop if production write outside expected paths
- Stop if stale data accepted
- Stop if duplicate trades created
- Stop if DB integrity fails
- Document all stop events

## Session-End Reconciliation
1. Count signals detected vs trades created
2. Count rejected signals by reason
3. Verify no duplicate trades
4. Verify DB integrity
5. Compare API output with DB state
6. Verify Telegram alerts match trades
