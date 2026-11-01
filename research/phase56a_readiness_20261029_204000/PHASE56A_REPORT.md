# Phase 5.6A — HLC Deployment Safeguards and Integration Test Completion

## Environment

- Host: `webserver` (Oracle VM)
- Application root: `/opt/tradingai`
- Production database: `/opt/tradingai/database/tradingai.db`
- Phase 5.5 report: `/opt/tradingai/research/phase55_hlc_integration_tests_20261029_203500/PHASE55_REPORT.md`
- Report directory: `/opt/tradingai/research/phase56a_readiness_20261029_204000/`

## Phase A — Baseline

### Current Decision Path

- Live decision engine: `app/live/engine.py` (gunicorn, port 8000)
- Default strategy: HLC 3-Bar Scalp (`_hlc_book_signal()`, line 578)
- CPR trigger engine (`_cpr_book_signal()`, line 321) retained for rollback
- Live paper trade creator: `scripts/paper_scalp_live.py` (PID 806096/806158)
- Telegram alerts: `scripts/tg_alerts.py --watch` (cron, every minute 09:15–15:30 weekdays)

### Active Trade-Creation Paths

1. `paper_scalp_live.py` → `scalp_engine.run_opens_range()` → `PaperTradeEngine.create_paper_trade()`
2. `tg_alerts.py` does NOT create trades (only alerts for existing trades)

### Production Configuration

- Feature flag: None currently implemented. HLC is de facto default.
- Mode C: one open position per instrument at a time (enforced in `paper_scalp_live.py`)
- Daily trade limit: NOT implemented
- `HLC_ONLY_MODE`: NOT implemented (designed in Phase 5.6A)

### Working-Tree State

- Branch: `production-2026-10-01`
- Last commit: `7da4b21 feat(scalp): add 1m scalp backtest script`
- Modified tracked files: 439 (5 core app files + frontend + data)
- Untracked files: 1,403 (mostly research/backups)
- Total dirty: 1,842

### Service Status

- Gunicorn: 3 processes (PIDs 802784, 824977, 829484), port 8000
- paper_scalp_live.py: 2 processes (PIDs 806096, 806158)
- tg_alerts.py: cron-scheduled (not running as daemon)
- systemd: no enabled units for paper_scalp_live

### DB Integrity

- `PRAGMA integrity_check` → `ok`
- `paper_trades`: 94 rows
- `scalp_signals`: 29 rows
- `paper_scalp`: 217 rows
- `tg_alerts_archive.jsonl`: 131 entries

### Dependencies Affected by HLC-Only Mode

See `DEPENDENCY_CHANGES_REQUIRED.csv` from Phase 5.5.

## Phase B — Integration Test Results

8 tests run, 8 passed, 0 failed, 0 not run. See `INTEGRATION_TEST_RESULTS.md`.

## Phase C — Trade Limit Policy

Designed and tested in isolation. See `TRADE_LIMIT_POLICY_TESTS.md`.

## Phase D — Backup and Restore

4 tests run, 4 passed. See `BACKUP_RESTORE_TEST_RESULTS.md`.

## Phase E — Working-Tree Safety

See `WORKING_TREE_SAFETY_AUDIT.md`.

## Phase F — Feature Flag Design

See `FEATURE_FLAG_AND_ROLLBACK_DESIGN.md`.

## Phase G — Final Decision

See `DEPLOYMENT_BLOCKERS.csv`.

## Final Status

**PARTIAL — SOME TESTS OR SAFETY GATES REMAIN**

Reasons:
- 6 of 8 integration tests are design-level (not exercising production code paths)
- Daily trade limit not implemented
- Systemd unit for paper_scalp_live not enabled
- Working tree has 1,842 uncommitted files
- Feature flag not implemented
- No production backup rehearsal performed (test DB only)
- Live verification of sub-10-second latency not possible (market closed during all audit windows)
