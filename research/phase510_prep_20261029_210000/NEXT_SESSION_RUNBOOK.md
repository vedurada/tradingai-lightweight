# Phase 5.10 — Next Session Runbook

## Next Market Session

- Date: 2026-10-30 (Friday)
- Market hours: 09:15-15:30 IST
- Pre-session setup: 09:00 IST

## Pre-Session Checklist

1. Verify market is open
2. Verify services running
3. Verify DB integrity
4. Verify no experimental jobs
5. Create timestamped log file

## Measurement Procedure

Follow Phase 5.9 NEXT_SESSION_RUNBOOK.md (same procedure).

## Evidence Required Before Migration

1. Live ingestion delay: median <30s, P95 <120s
2. Live signal-to-trade latency: <30s
3. Expired signal rejection rate: <10%
4. Zero duplicate trades
5. Zero stale data accepted
6. DB integrity: ok
7. All services stable for full session
