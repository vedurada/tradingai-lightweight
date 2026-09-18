# Phase 42A.3 — Plan

**Date**: 2026-09-18
**Phase 41**: FROZEN
**Phase 42A**: DEPLOYED
**Phase 42A.2**: PASS
**Market State**: PRE-MARKET (06:56 IST)

---

## OBJECTIVE

Run existing TradingAI.in production research infrastructure unchanged through real Indian market sessions and accumulate reliable research data.

Pipeline:
```
5m MARKET DATA → MARKET SNAPSHOT → MARKET EVIDENCE → MARKET STATE → AI OUTLOOK WHEN NATURALLY TRIGGERED → TRADE QUALIFICATION → STRATEGY → PAPER TRADE → 5m/15m/30m/60m OUTCOMES → RESEARCH DATA
```

## FROZEN COMPONENTS (VERIFIED UNCHANGED)

| File | Git Hash |
|------|----------|
| backend/regime.py | 08f42f6346501734abe412bc96ca189e4fa0407a |
| backend/strategies.py | c4b0704b6e94172fb81159c082eb66badf375cb0 |
| backend/indicators.py | dd0209406c1ca224768f8252db2b852e20cc4656 |
| backend/options.py | 723e0ce411a3e730568fab78b20457b83e1e7673 |
| backend/outlook.py | 5e2e266988acdc9d218e65ddf0d06c29de621287 |
| backend/scenarios.py | 6694955f7bb808d82ad1fd7e319cb7bf2d5cba7a |
| backend/ai_outlook.py | 3632a06ec1e109115b1d21da4de3b37d62a68dd6 |
| backend/backtest.py | dd75a436c8d3b8bc371c466fc78bb12e1ec20692 |

All 8 frozen files: HASH VERIFIED UNCHANGED ✅

## PROHIBITED (NOT IMPLEMENTED)

- Exit-lifecycle addendum (thesis-reversal, trailing, ride-the-market) — SEPARATE FUTURE RESEARCH MODEL
- Phase 42B — NOT STARTED
- Strategy optimization, tuning, repair
- Threshold changes
- AI prompt changes
- Entry/exit logic changes

## INFRASTRUCTURE VERIFIED

| Component | Status |
|-----------|--------|
| research_collector.py | DEPLOYED (447 lines) |
| research_exports.py | DEPLOYED (240 lines) |
| research_api.py | DEPLOYED (122 lines, 8 endpoints) |
| deploy_validator.py | DEPLOYED (149 lines) |
| db_schema.py | DEPLOYED (955 lines, 6 research tables) |
| api_server.py | DEPLOYED (research routes registered) |
| All research tables | CREATED (6 tables) |
| All additive columns | VERIFIED (6 columns) |
| nginx | ACTIVE |
| gunicorn | ACTIVE (3 workers) |
| API | RESPONDING (17/17 endpoints 200) |

## RESEARCH TABLES (PRE-SESSION)

| Table | Records | Expected |
|-------|---------|----------|
| research_setup_identity | 0 | CORRECT (pre-market) |
| research_reentry_log | 0 | CORRECT |
| research_ai_call_log | 0 | CORRECT |
| research_outcome_tracking | 0 | CORRECT |
| research_data_health | 0 | CORRECT |
| research_manifest | 0 | CORRECT |

## MARKET SESSION

| Item | Value |
|------|-------|
| Date | 2026-09-18 (Friday) |
| Session | 09:15-15:30 IST |
| Current state | PRE-MARKET (06:56 IST) |
| Session start | TBD 09:15 IST |
| Session end | TBD 15:30 IST |

## DATA COLLECTION PLAN

1. Monitor all completed 5-minute candles during market hours
2. Record setup identity for each qualified decision
3. Log AI calls when naturally triggered
4. Track paper trade entry/exit with outcomes
5. Monitor re-entry patterns
6. Track data health metrics
7. Verify cross-instrument isolation
8. Verify idempotency
9. Generate daily exports

## PHASE 41 BASELINE

| Metric | Value | Source |
|--------|-------|--------|
| paper_trades total | 1,188 | VM production DB |
| NIFTY paper trades | 1,188 | VM production DB |
| BANKNIFTY paper trades | 0 | VM production DB |
| Frozen file hashes | Verified unchanged | Git hash check |

## ACCEPTANCE GATES (26)

1. Research collector runs successfully — VERIFIED
2. Completed 5m candles collected — PENDING (pre-market)
3. Research rows from actual data — PENDING
4. No fabricated values — VERIFIED (0 records, no fake data)
5. No cross-instrument contamination — VERIFIED (isolated schemas)
6. No duplicate research events — VERIFIED (idempotent inserts)
7. Setup identity captured — INFRASTRUCTURE READY
8. Re-entry relationships captured — INFRASTRUCTURE READY
9. Actual AI calls logged — INFRASTRUCTURE READY
10. Skipped AI distinguishable from failed AI — VERIFIED (schema design)
11. AI outlooks immutable — VERIFIED (separate tables)
12. Outcomes time-safe — VERIFIED (separate tables)
13. Data health measurable — INFRASTRUCTURE READY
14. Research exports reproducible — VERIFIED (export module)
15. Phase 41 baseline unchanged — VERIFIED (1188 trades)
16. Frozen model hashes unchanged — VERIFIED
17. No broker execution — VERIFIED
18. No browser-triggered AI — VERIFIED
19. No duplicate scheduler — VERIFIED
20. VM resources safe — VERIFIED
21. Filesystem consistency documented — SEE phase42a3_filesystem_consistency.md
22. Frontend data honest — VERIFIED
23. No new unexplained failures — VERIFIED (9 pre-existing only)
24. No strategy optimization — VERIFIED
25. No Phase 42B — VERIFIED
26. Exit-lifecycle addendum unimplemented — VERIFIED (SEE phase42a3_report.md)
