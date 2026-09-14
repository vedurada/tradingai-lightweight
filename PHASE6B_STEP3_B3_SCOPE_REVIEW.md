# PHASE 6B-3 B.3 — Scope Review (Read-Only): Failure Recovery

**Status**: SCOPE REVIEW — NOT YET AUTHORIZED

**Frozen baselines**: `45f90fc` (analytical/model), `51c02f9` (PHASE 6A), `63ab095` (PHASE 6B-1), `8bbd4d7` (PHASE 6B-2), `c39af34` (6B-3 Phase A), `3ec9473` (B.1), `cdf0f6a` (B.2)

**Regression baseline**: 350/350 passing

**Previous audit**: PHASE6B_PRODUCTION_HARDENING_AUDIT.md (61 findings)

**Previous implementation**: PHASE6B_STEP3_B2_SPECIFICATION.md (B.2 Security Hardening)

**Implementation authorization**: ❌ NOT AUTHORIZED — This document is read-only scope review only.

---

## 1. Purpose & Principle

B.3 defines how TradingAI.in behaves when dependencies fail. This is a scope review only — no implementation is authorized.

### Governing Principle

> If market data becomes unavailable, the infrastructure layer communicates **DATA UNAVAILABLE / INCOMPLETE** — it does not manufacture a regime, strategy, confidence, or prediction.

**Server decides. LLM explains. Infrastructure reports failures.**

### Model Layer Protection

B.3 must NOT modify analytical behavior. If data is incomplete, the system reports incompleteness — it does not extrapolate, guess, or default to values that could be mistaken for real analysis.

---

## 2. Reconciliation: Audit Findings vs Completed Work

### Already Addressed (NOT in B.3 scope)

| Finding | Severity | Status | Where Addressed |
|---|---|---|---|
| 6.1 No Circuit Breaker | High | ✅ DONE | 6B-1 (circuit_breaker.py) |
| 6.2 No Retry with Backoff | High | ✅ DONE | 6B-1 (retry.py) |
| 1.2 No DB Connection Timeout | High | ✅ DONE | 6B-1 |
| 1.3 Connection Leaks | High | ✅ DONE | 6B-1 |
| 1.5 Bare Except in Health | Medium | ✅ DONE | B.2 (immediate fix) |
| 8.5 nginx Cache Stale Auth | Medium | ✅ DONE | B.2 (nginx config) |
| 8.7 SQL Injection | Low | ✅ DONE | B.2 (sql_guard.py) |
| 8.8 Error Response Leak | Low | ✅ DONE | B.2 (error handlers) |
| 1.7 f-string SQL | Medium | ✅ DONE | B.2 (sql_guard.py) |

### Open Failure/Recovery Findings

**Dimension 9: Failure/Recovery** (8 findings)

| Finding | Severity | B.3? | Rationale |
|---|---|---|---|
| 9.1 No Graceful Degradation | High | ✅ Yes | Core B.3 concern |
| 9.2 No VIX Outage Fallback | Medium | ✅ Yes | Data-source-specific failure |
| 9.3 No Options Outage Fallback | Medium | ✅ Yes | Data-source-specific failure |
| 9.4 Database Failure Recovery | Medium | ✅ Yes | Core B.3 concern |
| 9.5 Stale Data Detection | Medium | ✅ Yes | User-facing failure state |
| 9.6 API Restart Behavior | Medium | ✅ Yes | Operational recovery |
| 9.7 No Rollback Strategy | Medium | ✅ Yes | Operational recovery |
| 9.8 No Request Queuing | Low | ⚠️ TBD | Could be B.4 (Performance) |

**Dimension 6: Data-Source Failures** (unaddressed — 6 of 8)

| Finding | Severity | B.3? | Rationale |
|---|---|---|---|
| 6.3 No External API Health Tracking | Medium | ✅ Yes | Failure observability |
| 6.4 No Fallback for yfinance | Medium | ✅ Yes | Graceful degradation |
| 6.5 VIX Failure Not Isolated | Medium | ✅ Yes | Failure isolation |
| 6.6 Options Failure Not Isolated | Medium | ✅ Yes | Failure isolation |
| 6.7 Database Failure Not Handled | Medium | ✅ Yes | DB recovery (overlaps 9.4) |
| 6.8 NSE Live Quote No Health | Low | ✅ Yes | Health monitoring |

**Related Cross-Cutting**

| Finding | Severity | B.3? | Rationale |
|---|---|---|---|
| 1.4 Inconsistent Partial-Data | Medium | ✅ Yes | Related to stale/fallback behavior |
| 3.5 No Deep Health Check | Medium | ⚠️ TBD | Could be 6B-3 Phase A follow-up |
| 3.10 Pipeline Failure Visibility | Low | ⚠️ TBD | Could be B.3 or B.8 |

### Summary Count

| Category | Count |
|---|---|
| Strong B.3 candidates | 13 |
| TBD (could be B.3 or elsewhere) | 3 |
| Already addressed | 9 |
| **Total open** | **16** |

---

## 3. B.3 Proposed Scope

### Primary Areas

| Area | Findings | Priority | Description |
|---|---|---|---|
| **A. Graceful Degradation** | 9.1, 6.4, 1.4 | 🔴 High | Serve last-known-good data with stale flag; never manufacture data |
| **B. Failure Isolation** | 6.5, 6.6, 6.3 | 🟠 High | One data-source failure must not cascade to unrelated endpoints |
| **C. Database Recovery** | 9.4, 6.7 | 🟠 High | DB corruption/lock recovery with verification and alerts |
| **D. Stale Data Communication** | 9.5, 6.8 | 🟠 Medium | Every data endpoint reports freshness; health reports source status |
| **E. Operational Recovery** | 9.6, 9.7 | 🟡 Medium | Graceful restart, rollback strategy, deployment safety |

### Explicit NOT in B.3

| Area | Findings | Deferred To | Rationale |
|---|---|---|---|
| Circuit breaker extension | 6.1 (partially done) | B.3 extension if needed | 6B-1 has circuit breaker; B.3 defines behavior during prolonged failure |
| Retry/backoff | 6.2 | ✅ DONE | Already in 6B-1 |
| Performance optimization | 10.1-10.8 | B.4 | Performance is separate scope |
| Monitoring foundation | 3.1-3.10 | 6B-3 Phase A | Observability is separate scope |
| Rate limiting / CORS / Auth | 2.1, 2.2, 2.3, 8.1, 8.2, 8.6 | B.2 ✅ | Already addressed |
| Analytical behavior | None | NEVER | B.3 must not modify model outputs |

### Key Scoping Decision

**9.8 Request Queuing**: This could be B.3 (failure under load) or B.4 (performance). **Recommend B.4** since it's about capacity, not failure recovery. Decision deferred to B.4 spec review.

**3.5 Deep Health Check / 3.10 Pipeline Visibility**: These overlap with B.3's "health/readiness" and "pipeline status" concerns but also overlap with 6B-3 Phase A observability. Recommend explicit decision during B.3 spec.

---

## 4. B.3 Key Design Principles

### 4.1 Data Unavailability Communication

When any data source fails:

| State | API Response | User Message |
|---|---|---|
| Fresh data available | Normal response with `data_quality: "LIVE"` | Normal |
| Stale data (source unavailable, cached exists) | Response with `data_quality: "STALE"` or `data_freshness: {age, stale: true}` | "Data is X hours old" |
| No data (source failed, no cache) | Response with `data_quality: "DATA UNAVAILABLE"` | "Data unavailable — last fetch was X hours ago" |
| Partial data (some sources fail) | Response with `data_completeness: {total, available, missing}` | "Some indicators unavailable" |

### 4.2 Analytical Layer Protection

| Rule | Enforcement |
|---|---|
| Never manufacture regime/strategy/confidence from missing data | Test: if data unavailable, no NEW analytical values generated |
| Stale data labeled, never presented as fresh | Test: all responses include data_quality or data_freshness |
| LLM explains based on available data only | Test: no prompt includes manufactured or extrapolated values |
| Infrastructure reports failure, server decides | Test: API returns 503 or stale data, never pretends data exists |

### 4.3 Scope Boundaries

**B.3 CAN**:
- Add `data_quality` / `data_freshness` / `data_completeness` fields to responses
- Serve cached/stale data with appropriate flags
- Add DB error handling (503 instead of 500)
- Add health/readiness endpoints
- Add failure observability (error counts, pipeline status)
- Add rollback script
- Add graceful restart behavior

**B.3 CANNOT**:
- Change RegimeEngine, StrategyEngine, OptionsEngine calculations
- Change confidence mathematics or scenario normalization
- Change LLM prompt logic or model outputs
- Change backtest methodology
- Add performance optimizations (B.4 scope)
- Add rate limiting, CORS, auth (B.2 scope)
- Add monitoring instrumentation (6B-3 scope)

---

## 5. Dependency Map

```
B.2 Security 🔒
       ↓
B.3 Failure Recovery (THIS REVIEW)
       ↓
B.4 Performance & DB (next)
       ↓
B.5 Operational Polish
```

**Why this order**: The system must define correct behavior during failure before optimizing performance. You don't want to make a broken system faster — you want to make a failing system resilient.

**B.2 → B.3 dependency**: B.2 auth ensures that during failure recovery, portfolio endpoints are still protected. B.3 assumes auth is in place.

**B.3 → B.4 dependency**: B.4 performance optimization assumes graceful degradation is defined. Caching strategies in B.4 depend on B.3's stale-data protocol.

---

## 6. Test Plan (B.3 — Proposed)

### A. Graceful Degradation Tests

| Test | Description |
|---|---|
| `test_price_404_serves_stale` | If price unavailable, last known price served with stale flag |
| `test_market_empty_serves_partial` | Empty market data → partial with missing indicators listed |
| `test_no_manufactured_confidence` | When data unavailable, no NEW confidence/regime values generated |
| `test_stale_flag_every_endpoint` | All data endpoints include data_quality or data_freshness |

### B. Failure Isolation Tests

| Test | Description |
|---|---|
| `test_vix_failure_does_not_affect_price` | VIX data failure doesn't cause price endpoint to fail |
| `test_options_failure_does_not_affect_market` | Options failure doesn't cascade to market overview |
| `test_single_source_failure_isolated` | One data-source failure doesn't affect unrelated endpoints |

### C. Database Recovery Tests

| Test | Description |
|---|---|
| `test_db_corruption_returns_503` | DB failure → 503 (not 500), user-friendly message |
| `test_migration_verification` | DB migration succeeds/fails deterministically |
| `test_connection_timeout_handled` | DB lock → 503 with helpful message, not indefinite hang |

### D. Stale Data Communication Tests

| Test | Description |
|---|---|
| `test_health_reports_source_status` | /api/health includes per-source status (ok/stale/unavailable) |
| `test_stale_data_communicated` | Stale data responses include age and staleness flag |
| `test_pipeline_status_endpoint` | Data pipeline success/failure visible |

### E. Operational Recovery Tests

| Test | Description |
|---|---|
| `test_rollback_script_exists` | Fast rollback script exists and works |
| `test_rollback_completes_under_2min` | Rollback completes in < 2 minutes |
| `test_graceful_shutdown` | SIGTERM handled gracefully, in-flight requests completed |
| `test_startup_verification` | API verifies health before accepting traffic |

### Regression Tests
- All 350 existing tests remain green

---

## 7. B.3 Acceptance Criteria (Proposed)

If authorized:

1. **350 existing tests remain green**
2. **All new B.3 tests pass**
3. **Model layer untouched**: zero changes to regime.py, strategies.py, outlook.py, scenarios.py, options.py, ai_outlook.py, backtest.py, indicators.py
4. **Data unavailable clearly communicated**: all data endpoints include quality/freshness indicators
5. **No manufactured data**: no analytical values generated from missing inputs
6. **Failure isolated**: one data-source failure doesn't cascade
7. **DB recovery works**: DB failure → 503, not 500; recovery verified
8. **Graceful restart**: SIGTERM handled, startup verified
9. **Rollback functional**: fast rollback < 2 minutes
10. **Public endpoints unaffected**: auth boundary preserved from B.2

---

## 8. B.3 Implementation Sequence (Proposed)

| Order | Item | Effort | Dependencies |
|---|---|---|---|
| 1 | Graceful degradation protocol (stale flag, fallback data) | M | None |
| 2 | Data-source failure isolation | M | Item 1 |
| 3 | DB error handling + recovery | M | None |
| 4 | Stale data communication (all endpoints) | M | Item 1 |
| 5 | Health/readiness endpoints | S | Item 4 |
| 6 | Failure observability (error counts, pipeline status) | M | Item 5 |
| 7 | Operational recovery (rollback, graceful restart) | M | None |
| 8 | Partial-data behavior standardization | M | Item 1 |
| 9 | Regression test + model boundary verification | — | All above |

---

## 9. Concerns for Reviewer

1. **Scope boundary**: B.3 must carefully avoid touching analytical behavior. The "DATA UNAVAILABLE" protocol needs explicit test coverage.
2. **6.7 vs 9.4 overlap**: Both are DB recovery — should be a single implementation or split?
3. **9.8 Request Queuing**: Recommendation is to defer to B.4, but this needs explicit decision.
4. **3.5 / 3.10 overlap**: Health check depth and pipeline visibility could be B.3 or 6B-3 follow-up. Needs decision.
5. **Stale data protocol**: This affects ALL data endpoints (55). The protocol definition should be spec-first.
6. **Cache serving during outage**: Serving stale data requires cache infrastructure. Is this B.3 (failure behavior) or B.4 (caching/performance)?

---

## 10. Verdict

- **SCOPE REVIEW COMPLETE** — Awaiting independent review of scope

**Reviewer**: User (independent decision)
**Date**: 2026-09-14
**Notes**: B.3 scope review is READ-ONLY. No implementation authorized. User must review scope, approve specification, then explicitly authorize implementation in a separate step.

---

## 11. Next Steps

1. **User reviews this scope review**
2. **If approved → B.3 Specification** (finding → requirement → implementation boundary → tests → acceptance criteria)
3. **User reviews B.3 specification**
4. **User explicitly authorizes B.3 implementation**
5. **B.3 Implementation → tests → gates → independent review → freeze → STOP**

---

*End of PHASE 6B-3 B.3 Scope Review — Failure Recovery. Read-only. No implementation authorized.*
