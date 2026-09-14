# PHASE 6B-3 B.5 — Scope Review

**Status**: IN PROGRESS — Awaiting Approval

**Baseline**: `d4990e4` (B.4 frozen)
**Analytical baseline**: `45f90fc` (immutable)
**Model files**: 0/8 modified (preserved)

---

## Purpose

Re-audit remaining production-hardening findings after B.4 freeze. Reconcile what B.1–B.4 already addressed. Identify only the remaining actionable findings for a narrowly defined B.5 scope.

---

## Reconciliation: B.1–B.4 Coverage

### Findings Addressed

| Phase | Findings Addressed | Count |
|---|---|---|
| 6B-1 | 1.1, 1.2, 1.3, 1.4, 7.1, 6.1, 6.2 | 7 |
| 6B-2 | 2.1, 2.2, 2.4, 2.5, 8.2, 8.3, 8.5, 8.7, 8.8, 1.5, 1.7, 1.8, E.6 | 13 |
| 6B-3 Phase A | 3.1, 3.2, 3.3, 3.4, 5.1, 5.2, 5.3, 5.4 | 8 |
| B.1 | 4.1, 4.2, 4.3 | 3 |
| B.2 | 8.1, 8.2 (re-confirmed) | 2 |
| B.3 | 9.1–9.8, 6.3–6.8 | 13 |
| B.4 | 7.2–7.6, 10.1–10.8 | 13 |
| **Total** | | **59** |

### Findings Not in Any B.x Scope

| ID | Severity | Finding | Status |
|---|---|---|---|
| 1.6 | MEDIUM | Impure _symbol_data Called Internally | OPEN — deferred, not in any B.x scope |
| 2.3 | HIGH | No Auth on Any Endpoint (broader) | OPEN — portfolio auth done; broader auth deferred by user decision |

### Findings Fully Addressed (Do Not Reopen)

All 59 findings above are confirmed addressed. These will NOT be re-examined in B.5.

---

## Unaddressed Findings After Reconciliation

### Group 1: Monitoring Depth (Coherent Track)

| ID | Severity | Finding | Why Open |
|---|---|---|---|
| 3.5 | MEDIUM | No Health Check Beyond /api/health | Listed as TBD in 6B-3 scope review. Not in B.3, B.4 scope. |
| 3.6 | MEDIUM | Data Freshness Only Checks Last Timestamp | Per-endpoint freshness exists, but deep health check (row counts, date ranges, value sanity) is open. |

### Group 2: Operational Resilience (Coherent Track)

| ID | Severity | Finding | Why Open |
|---|---|---|---|
| 11.2 | MEDIUM | No Process Supervisor Beyond systemd | systemd exists but no memory limits, logrotate for gunicorn, memory-based restart. |
| 11.3 | MEDIUM | No Structured Deployment Logging | Deploy logging not implemented. |
| 11.4 | MEDIUM | Manual Cron Installation | Self-heal.sh doesn't re-install crontab. |
| 11.5 | MEDIUM | No Database Backup Verification | Backup age check not added to self-heal. |

### Group 3: Code Quality (Single Finding)

| ID | Severity | Finding | Why Open |
|---|---|---|---|
| 1.6 | MEDIUM | Impure _symbol_data Called Internally | Deferred. Not in any B.x scope. Requires refactoring _symbol_data to extract data-building logic from shared function. |

### Excluded (Separate Track Required)

| ID | Finding | Exclusion Reason |
|---|---|---|
| 2.3 | Broader auth on non-portfolio endpoints | Requires auth architecture design before implementation |
| 8.4 | Secrets in /etc/tradingai/ | VM-level operational concern, not code change |
| 8.6 | CSRF Protection | Phased after auth design (8.1). Depends on chat auth which is deferred |
| 3.8 | Distributed Tracing | Requires architecture review (spans, context propagation, cross-service) |
| 4.4 | Staging Environment | Infrastructure (VM provisioning), not code |
| 3.9 | Centralized Error Tracking | Sentry/Rollbar integration — requires vendor selection, separate design |
| 3.10 | Pipeline Failure Visibility | Depends on Group 1 health check design |
| 5.5 | Log Rotation | Depends on Group 2 operational work |

---

## Proposed B.5 Scope

### Track: Production Observability & Operational Resilience

**Objective**: Extend monitoring depth and improve operational resilience without touching analytical code, model files, or auth architecture.

**Protected Boundaries**:
- 0/8 model files modified
- No RegimeEngine/StrategyEngine/Confidence/Threshold changes
- No backtest methodology changes
- No auth architecture changes

### B.5 Part 1: Deep Health Checks

| Finding | Action |
|---|---|
| 3.5 | Extend /api/health with: database row counts per table, data freshness date range validation, key source value sanity checks |
| 3.6 | Add deep freshness validation: verify row counts are within expected ranges, date ranges cover expected periods, key values are within reasonable bounds |

### B.5 Part 2: Operational Resilience

| Finding | Action |
|---|---|
| 11.2 | Add process supervision enhancements: gunicorn memory limits, logrotate config for gunicorn logs, memory-based restart thresholds |
| 11.3 | Add structured deployment logging to deploy scripts |
| 11.4 | Add crontab installation to self-heal.sh |
| 11.5 | Add database backup verification to self-heal.sh (backup age check) |

### B.5 Part 3: Code Quality (Conditional)

| Finding | Action |
|---|---|
| 1.6 | Refactor _symbol_data to extract data-building logic into dedicated functions. Must preserve all existing behavior. Must pass all regression tests. |

**Conditional**: Part 3 requires separate design review before implementation. Not included in B.5 implementation authorization by default.

---

## Scope Exclusions (Explicit)

The following are explicitly excluded from B.5 and require separate scope reviews:

| Item | Reason |
|---|---|
| Auth expansion (2.3, 8.6) | Requires auth architecture design |
| Secrets management (8.4) | VM-level, not code |
| Distributed tracing (3.8) | Requires architecture review |
| Staging environment (4.4) | Infrastructure, not code |
| Centralized error tracking (3.9) | Requires vendor selection, separate design |
| Log rotation (5.5) | Covered implicitly by Part 2 |
| _symbol_data refactor (1.6) | Separate design required (Part 3 conditional) |
| Any model/analytical changes | Blocked by freeze boundary |

---

## Dependencies & Risks

| Dependency | Risk | Mitigation |
|---|---|---|
| B.4 caching (Part B) | Deep health checks may read cached data | Health checks should bypass cache or use dedicated DB connections |
| B.3 data_quality protocol | Deep freshness uses data_quality fields | Consistent with B.3 protocol, no changes |
| B.4 connection pool (Part A) | Health checks use pool connections | Use dedicated pool connection with short timeout |
| _symbol_data refactor (1.6) | Breaking existing behavior | Comprehensive regression testing required |

---

## Test Plan

| Coverage | Approach |
|---|---|
| Deep health checks | New tests verifying health endpoint includes row counts, date ranges, value checks |
| Operational resilience | Verify self-heal.sh installs crontab, verifies backup age |
| Code quality (if authorized) | Regression: 421/421 must pass |
| No model changes | `git diff d4990e4..HEAD --name-only backend/regime.py backend/strategies.py ...` → empty |

---

## Phase Comparison

| Dimension | Previous (B.4) | B.5 Proposed |
|---|---|---|
| Focus | Performance & DB | Observability & Operations |
| Key additions | Connection pool, caching | Deep health, deploy ops |
| Model files | 0 modified | 0 modified (protected) |
| Backtest | Async (10.1) | Not touched |
| Auth | Portfolio (B.2) | Not touched |

---

## RECOMMENDATION

B.5 Scope: **Production Observability & Operational Resilience**

**Core scope** (recommended for authorization):
- 3.5 Deep health checks
- 3.6 Freshness validation depth
- 11.2 Process supervisor enhancements
- 11.3 Deployment logging
- 11.4 Crontab auto-install
- 11.5 Backup verification

**Conditional** (separate design review):
- 1.6 _symbol_data refactor

**Excluded** (separate scope required):
- Auth expansion, secrets, distributed tracing, staging, centralized error tracking

---

## STOP — Awaiting Approval

Only after approval should the lifecycle continue:

Specification → Authorization → Implementation → Acceptance → Independent Review → Freeze → STOP

---

*End of PHASE 6B-3 B.5 Scope Review.*
