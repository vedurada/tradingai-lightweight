# Phase 5.10 — Isolated Rollback Rehearsal Plan

## Already Tested (Phase 5.6A)

| Test | Result | Evidence |
|------|--------|----------|
| SQLite backup via backup API | PASS | phase56a test DB |
| SQLite restore via backup API | PASS | phase56a test DB |
| Simulated failed restore (corrupt DB) | PASS | phase56a test DB |
| Original test DB unchanged | PASS | phase56a test DB |

## Production-Specific (NOT TESTED)

| Procedure | Status | Notes |
|-----------|--------|-------|
| Production DB backup | NOT TESTED | Documented in Phase 5.8 |
| Production DB restore | NOT TESTED | Documented in Phase 5.8 |
| Feature-flag rollback | NOT TESTED | Design only |
| Service rollback | NOT TESTED | Design only |

## Proposed Future Rehearsal (Isolated)

1. Copy production DB to isolated test directory (read-only copy)
2. Run backup/restore on the copy
3. Verify integrity and row counts
4. Test feature-flag toggle (env var)
5. Test service restart (systemd unit in test mode)
6. Document results

## Integrity Checks

- `PRAGMA integrity_check` → ok
- Row counts: paper_trades, scalp_signals, paper_scalp, market_candles_5m
- File size comparison
- Readability verification

## Acceptance Criteria

- Backup integrity: ok
- Restore integrity: ok
- Row counts match: 100%
- No data loss
- Open trades remain manageable
