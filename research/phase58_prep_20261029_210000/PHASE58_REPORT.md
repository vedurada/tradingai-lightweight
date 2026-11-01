# Phase 5.8 — HLC Migration Preparation and Deployment Safety Audit

## Environment

- Host: `webserver` (Oracle VM)
- Application root: `/opt/tradingai`
- Production database: `/opt/tradingai/database/tradingai.db`
- Phase 5.7 report: `/opt/tradingai/research/phase57_timing_20261029_205000/PHASE57_REPORT.md`
- Report directory: `/opt/tradingai/research/phase58_prep_20261029_210000/`

## Phase A — Phase 5.7 Evidence Revalidation

See `PHASE57_EVIDENCE_REVALIDATION.md`.

Key findings:
- Sample count: 75 candles per instrument (NIFTY, BANKNIFTY, INDIA_VIX) from Oct 29, 2026
- Calculation: `ingested_at - (timestamp + 5 minutes)` = delay after candle completion
- Timestamp represents: candle END time (timestamp + 5 min), not provider availability or DB persistence
- Measurements include: collection scheduling delay (RandomizedDelaySec=20) + collector processing + yfinance fetch
- 16 production-function tests: ACTUALLY EXECUTED (16/16 PASS)
- 5 entry-guard tests: ACTUALLY EXECUTED (5/5 PASS)
- Mocked dependencies: get_conn (patched to test DB), MarketDataProvider (not called in tests)
- Test writes: restricted to isolated test DB (`test_prod.db` in phase57 directory)
- Entry guard: UNCHANGED (not modified)

## Phase B — Working-Tree Safety

See `WORKING_TREE_DEPLOYMENT_SAFETY.md`.

Key findings:
- 439 modified tracked files + 1,403 untracked = 1,842 dirty files
- Top untracked directories: backups/ (443), research/ (433), backup/ (345), frontend/ (171)
- 5 core app files modified: app.py, engine.py, provider.py, paper_trade/engine.py, scalp_engine.py
- No path collisions identified that would block deployment
- Non-destructive deployment strategy proposed (file-level copy, not git merge)
- Blocker B1 remains OPEN (cannot establish safe deployment from evidence alone)

## Phase C — Feature-Flag Design

See `FEATURE_FLAG_DESIGN.md`.

Key findings:
- Flag: `HLC_ONLY_MODE`, default `false` (CPR-driven)
- Missing/invalid/unreadable → default `false` (fail-safe)
- One source of truth: environment variable or config/settings.json
- One trade-initiation path per mode
- Existing trades remain manageable during mode switch
- No historical trade records erased or migrated

## Phase D — Trade-Limit Design

See `TRADE_LIMIT_DESIGN.md`.

Key findings:
- Daily limit disabled: 63 trades (current baseline)
- Daily limit 1/day: ~6 trades (estimated, not verified from ledger)
- Mode C (concurrent position): preserved as baseline
- Selection rule: first signal per instrument per day

## Phase E — Service and Lifecycle Readiness

See `SERVICE_AND_LIFECYCLE_DESIGN.md`.

Key findings:
- paper_scalp_live.py currently runs as background process (PID 806096/806158)
- No systemd unit enabled
- Duplicate-process prevention via fcntl lock
- Restart recovery via recover_open_positions() and recover_new_signals()
- Idempotent signal processing via UNIQUE constraint and deterministic trade_id

## Phase F — Backup and Rollback Plan

See `BACKUP_AND_ROLLBACK_PLAN.md`.

Key findings:
- SQLite backup API tested (4/4 PASS on isolated test DB)
- Production backup procedure documented but NOT rehearsed
- Rollback procedure documented (flag change + service restart)
- Feature-flag rollback: set HLC_ONLY_MODE=false, restart gunicorn
- Service rollback: restart with previous configuration

## Phase G — Live-Session Validation

See `LIVE_SESSION_RUNBOOK.md`.

Key findings:
- Runbook prepared for next market session
- Measures all required latency stages
- Stop conditions defined
- No live measurements performed (market closed)

## Final Status

**PARTIAL — SOME SAFETY GATES OR DEPENDENCIES UNRESOLVED**

Reasons:
- Working tree blocker (B1) remains unresolved
- Live-session latency (B6, B13) not measured
- Daily trade limit not implemented (B3, B8)
- Feature flag not implemented (B5)
- Systemd unit not enabled (B4)
- No production backup rehearsal (B2)
- No rollback rehearsal (B12)
- CPR retirement not safe (B11)
