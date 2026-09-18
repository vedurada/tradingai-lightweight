# Phase 42A.4B — Scope

**Date**: 2026-09-18
**Phase 41**: FROZEN
**Phase 42A**: DEPLOYED

---

## Objective

Connect ResearchCollector to the real production 5-minute pipeline. Fix root cause of frontend LOADING/UNAVAILABLE states. No trading logic changes. No model changes.

## Scope Boundaries

### IN SCOPE
- ResearchCollector observation layer (collect method)
- Research collection integration (monitor.py)
- Research table population
- Data status model
- Test coverage
- Deployment verification

### OUT OF SCOPE (Phase 42B)
- Trading strategy changes
- Signal optimization
- Threshold tuning
- AI prompt changes
- Exit behavior changes
- New market-data fetcher
- New infrastructure (Redis, PostgreSQL, Docker, Node.js)

## Critical Constraints
- Frozen model files: UNCHANGED (8/8 verified)
- Phase 41 trading logic: UNCHANGED
- No broker execution
- No fabricated data
- Pre-market at observation time (07:32 IST)
