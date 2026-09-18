# Phase 42A — Initial State

**Timestamp**: 2026-09-17T21:50:00+05:30
**Phase 41**: FROZEN
**Phase 41C**: COMPLETE
**Phase 42 Design Review**: COMPLETE

---

## Git State

| Item | Value |
|------|-------|
| Branch | html/h31-shell-core-pages |
| HEAD | 488971a |
| Commit message | Phase 41C: Production validation audit documents and final state |
| Working tree | 20 untracked files (Phase 42 audit docs), 0 modified, 0 deleted |
| Clean | Yes (no tracked file changes) |
| Pushed | Yes (to origin) |

## Test Baseline

| Metric | Value |
|--------|-------|
| Total tests collected | 1270 |
| Tests run (excluding test_ai_outlook_backtest.py) | 1270 |
| Passing | 1261 |
| Failing | 9 |
| Pre-existing failures | 9 (confirmed: not caused by Phase 42A) |
| test_ai_outlook_backtest.py | Collection error (pre-existing) |

### Pre-existing Failures (confirmed unchanged)

1. test_level_invariant.py::test_key_levels_api_matches_invariant
2. test_live_pages.py::test_038_index_no_broken_internal_hrefs
3. test_phase1.py::test_existing_tests_still_pass
4. test_phase6a.py::test_signal_confidence_label
5. test_phase6b_b1.py::test_existing_tests_still_pass
6. test_phase6b_b2.py::test_existing_tests_still_pass
7. test_phase6b_b6.py::test_record_fetch_result_writes
8. test_phase7_track_b.py::test_consent_defaults_precede_gtag_load_everywhere
9. test_phase7_track_c.py::test_observational_wording

## Database State (Workspace)

| Item | Value |
|------|-------|
| DB path | /Users/satya/remove_workspace/tradingai.in_live_VM/database/tradingai.db |
| DB size | 15.7 MB |
| Total tables | 51 |
| Rows (approx) | 95,000+ |

### Key Research Tables (Workspace)

| Table | Rows | Status |
|-------|------|--------|
| market_snapshots_5m | 0 | Empty (populated on VM) |
| market_evidence_5m | 0 | Empty (populated on VM) |
| ai_outlooks_5m | 0 | Empty (populated on VM) |
| paper_trades | 0 | Empty (populated on VM) |
| paper_trade_events | 0 | Empty (populated on VM) |
| ai_outcome_predictions | 0 | Empty (populated on VM) |

## VM State

| Item | Value |
|------|-------|
| OS | Ubuntu 22.04 |
| API | Gunicorn (3 workers) on 127.0.0.1:8000, active |
| Nginx | Config exists, certificate permission issue (pre-existing) |
| DB | /opt/tradingai/database/tradingai.db |
| DB size | ~182 MB (VM) |
| Memory | 564MB available / 956MB total |
| Disk | 45GB, 35% used |

## Existing Research Tables (VM - populated)

| Table | Rows | Status |
|-------|------|--------|
| market_snapshots_5m | populated | LIVE data |
| market_evidence_5m | populated | evidence data |
| ai_outlooks_5m | populated | AI outlook data |
| paper_trades | populated | paper trade data |
| paper_trade_events | populated | trade events |

## Scheduler State (VM)

- Cron installed via crontab (multiple entries visible, market hours 9:30-15:30 IST)
- Systemd service: tradingai-api.service (active, running)
- Self-heal: every 2 minutes

## Deployment State

- Deploy script: deploy-vm.sh (not run during this task)
- No deployment performed
- Git: clean, pushed

## Baseline Confirmed

- No production code modified
- No trading logic changed
- No thresholds tuned
- No AI prompts modified
- No evidence rules changed
- No strategy selection changed
- No broker execution added
- 20 Phase 42 audit documents exist as untracked files (from Phase 42 design review)
