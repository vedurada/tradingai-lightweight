# PHASE 6B-3 B.4 — Scope Review (Read-Only): Performance & DB

**Status**: SCOPE REVIEW — NOT YET AUTHORIZED

**Frozen baselines**: `45f90fc` (analytical/model), `51c02f9` (PHASE 6A), `63ab095` (PHASE 6B-1), `8bbd4d7` (PHASE 6B-2), `c39af34` (6B-3 Phase A), `3ec9473` (B.1), `cdf0f6a` (B.2), `6596cc7` (B.3)

**Regression baseline**: 385/385 passing

**Previous audits**: PHASE6B_PRODUCTION_HARDENING_AUDIT.md (61 findings), PHASE6B_PRODUCTION_HARDENING_AUDIT.md review at B.3

**Implementation authorization**: ❌ NOT AUTHORIZED — Read-only scope review only.

---

## 1. Purpose & Dependencies

B.4 addresses performance and database stability. It depends on B.3's failure recovery protocol.

### B.3 → B.4 Dependencies

| B.3 Foundation | B.4 Must Preserve |
|---|---|
| DATA UNAVAILABLE/STALE/LIVE protocol | Caching must add `data_quality` fields, never replace them |
| DB error → 503 | Connection pooling must preserve 503 on DB failure |
| Graceful degradation | Performance improvements must not skip graceful degradation |
| Health endpoint per-source status | Performance monitoring must enhance, not replace, health status |
| No model layer changes | B.4 must also not modify model layer |

### Governing Principle

Performance optimization must not compromise failure recovery. If performance work makes the system faster but less resilient, it fails B.3's protocol.

---

## 2. Reconciliation: Findings vs Completed Work

### Already Addressed (NOT in B.4 scope)

| Finding | Severity | Where Addressed |
|---|---|---|
| 7.1 SQLite WAL | Critical | 6B-1 (WAL mode enabled) |
| 1.2 No DB Connection Timeout | High | 6B-1 (timeout=10) |
| 1.3 Connection Leaks | High | 6B-1 (try/finally) |
| 5.1 Structured Logging | High | 6B-3 Phase A (logging_config.py) |
| 5.2 Metrics Endpoint | Medium | 6B-3 Phase A (/api/metrics) |
| 5.3 Request Timing | Medium | 6B-3 Phase A (RequestMonitor) |
| 5.4 Error Logs Request Context | Medium | 6B-3 Phase A (correlation ID) |
| 8.5 nginx Cache | Medium | B.2 (proxy_no_cache) |
| 3.1 No Latency Tracking | High | 6B-3 Phase A (RequestMonitor) |

### B.4 Candidates

**Dimension 10: Performance** (8 findings)

| Finding | Severity | B.4? | Effort |
|---|---|---|---|
| 10.1 Blocking Backtest | Critical | ✅ Yes | L |
| 10.2 Expensive Options | High | ✅ Yes | M |
| 10.3 /api/market Rebuild | High | ✅ Yes | L |
| 10.4 No Response Caching | Medium | ✅ Yes | M |
| 10.5 No Pagination | Medium | ✅ Yes | M |
| 10.6 Concurrent Behavior | Medium | ✅ Yes | M |
| 10.7 Per-Endpoint Timeout | Low | ✅ Yes | S |
| 10.8 DB Query Efficiency | Low | ✅ Yes | L |

**Dimension 7: Database & Resources** (remaining, 7.1 already done)

| Finding | Severity | B.4? | Effort |
|---|---|---|---|
| 7.2 No Connection Pooling | High | ✅ Yes | M |
| 7.3 No DB Growth Management | Medium | ✅ Yes | M |
| 7.4 No Concurrent Write Protection | Medium | ✅ Yes | S |
| 7.6 Chat Cleanup Subquery | Low | ✅ Yes | S |

**Deferred from B.3**

| Finding | Severity | B.4? | Rationale |
|---|---|---|---|
| 9.8 No Request Queuing | Low | ✅ Yes | Deferred from B.3 scope review |

### Summary

| Category | Count |
|---|---|
| Strong B.4 candidates | 13 |
| Already addressed | 9 |
| Total open | 13 |

---

## 3. B.4 Proposed Scope

### Primary Areas

| Area | Findings | Priority | Description |
|---|---|---|---|
| **A. Async Processing** | 10.1 | 🔴 Critical | Backtests must not block request handlers |
| **B. Response Caching** | 10.4, 10.2, 10.3 | 🔴 High | Cache responses by data freshness category |
| **C. Database Optimization** | 7.2, 10.8, 7.4, 7.3 | 🟠 High | Connection pooling, indexes, write protection, cleanup |
| **D. Market Data Performance** | 10.3, 10.8 | 🟠 High | Non-blocking market rebuild, query efficiency |
| **E. List Endpoint Performance** | 10.5 | 🟡 Medium | Pagination on all list endpoints |
| **F. Operational** | 9.8, 10.7 | 🟡 Low | Request queuing, per-endpoint timeouts |
| **G. Concurrency Testing** | 10.6 | 🟡 Medium | Load testing, concurrency verification |

### Explicit NOT in B.4

| Area | Findings | Deferred To | Rationale |
|---|---|---|---|
| Monitoring/observability | 5.1, 5.2, 5.3, 5.4 | 6B-3 Phase A ✅ | Already done (observational) |
| Logging | 3.7, 5.1 | 6B-3 Phase A ✅ | Already done (structured logging) |
| DB journal mode | 7.1 | 6B-1 ✅ | WAL already enabled |
| Connection timeout | 1.2 | 6B-1 ✅ | Already done |
| Circuit breaker | 6.1 | B.2 ✅ | Already done |
| Rate limiting | 2.1 | B.2 ✅ | Already done |
| Auth/security | 8.1-8.8 | B.2 ✅ | Already done |
| Failure recovery | 9.1-9.7 | B.3 ✅ | Already done |
| Analytical behavior | None | NEVER | Must not modify model outputs |
| Monitoring alerts | 3.3, 3.4 | 6B-3 follow-up | Alerting threshold config |

### B.3 Protocol Preservation Rules

B.4 must preserve all B.3 behavior:

| Rule | Enforcement |
|---|---|
| Caching adds data_quality, never removes it | Test: all cached responses include data_quality |
| DB failure → 503 preserved with pooling | Test: simulate DB failure, verify 503 |
| Graceful degradation preserved | Test: simulate outage, verify DATA UNAVAILABLE |
| No model layer changes | Test: git diff 6596cc7 HEAD shows no model files |
| 385 existing tests remain green | Test: all 385 tests pass |

---

## 4. B.4 Key Design Principles

### 4.1 Caching Protocol

B.4 introduces response caching. Must integrate with B.3's data quality protocol:

| Cache Type | TTL | Data Quality |
|---|---|---|
| Real-time (price, quotes) | 5s | LIVE (if fresh), STALE (if aged) |
| Daily (outlooks, strategies) | 1 hour | LIVE or STALE based on actual freshness |
| Static (symbols, config) | 24 hours | LIVE (rarely changes) |
| Computation (backtest, options) | 10 minutes | LIVE or STALE based on actual freshness |

**Critical rule**: Cache serves last-known data with STALE flag. Never serves stale data as LIVE. Never manufactures data.

### 4.2 Connection Pooling Protocol

B.4 introduces connection pooling. Must preserve B.3's error handling:

| Condition | Behavior |
|---|---|
| Pool healthy | Normal operation |
| Pool exhausted | Queue/wait with timeout, then 503 |
| DB failure through pool | 503 (not 500), same as B.3 |

### 4.3 Async Processing Protocol

B.4 moves backtests to async. Must preserve:

| Current Behavior | Async Equivalent |
|---|---|
| Synchronous backtest result | 202 Accepted + job ID + poll endpoint |
| Backtest blocking worker | Worker freed immediately |
| Backtest error → 500 | Job error → stored, retrieved via poll |
| Backtest timeout → 504 | Job timeout → stored, retrieved via poll |

---

## 5. B.4 Implementation Sequence (Proposed)

| Order | Item | Effort | Dependencies |
|---|---|---|---|
| 1 | Connection pooling (7.2) | M | None (foundation) |
| 2 | Per-endpoint timeouts (10.7) | S | None |
| 3 | Response caching framework | M | Item 1 (pooling) |
| 4 | Backtest async (10.1) | L | Item 3 (caching) |
| 5 | Options caching (10.2) | M | Item 3 (caching) |
| 6 | Market rebuild async (10.3) | L | Item 3 (caching) |
| 7 | List pagination (10.5) | M | None |
| 8 | Concurrent write protection (7.4) | S | Item 1 (pooling) |
| 9 | DB growth management (7.3) | M | Item 1 (pooling) |
| 10 | Chat cleanup optimization (7.6) | S | Item 1 (pooling) |
| 11 | DB query efficiency (10.8) | L | Item 8 (write protection) |
| 12 | Concurrency tests (10.6) | M | Items 1, 3, 8 |
| 13 | Request queuing (9.8) | L | Items 1, 3 |

---

## 6. Test Plan (B.4 — Proposed)

### A. Connection Pooling Tests (4)
1. `test_connection_pool_exists` — Pool created on startup
2. `test_connection_reuse` — Same connection reused within request
3. `test_pool_503_on_exhaustion` — Pool exhaustion → 503
4. `test_connection_creation_reduced` — Connection time improved

### B. Response Caching Tests (6)
5. `test_price_cache_5s` — Price endpoint caches for 5s
6. `test_cache_adds_data_quality` — Cached responses include data_quality
7. `test_cache_serves_stale_on_outage` — Cache serves stale with STALE flag
8. `test_cache_never_manu_factures_data` — Stale data never marked LIVE
9. `test_options_cache_10min` — Options endpoints cache for 10min
10. `test_cache_hit_rate` — Cache hit rate > 50%

### C. Async Backtest Tests (4)
11. `test_backtest_returns_202` — Backtest returns 202 Accepted
12. `test_backtest_job_id` — Response includes job ID
13. `test_backtest_poll_endpoint` — Poll endpoint returns results
14. `test_api_responsive_during_backtest` — Other endpoints work during backtest

### D. Market Data Tests (3)
15. `test_market_non_blocking` — Market rebuild doesn't block
16. `test_market_stale_during_rebuild` — Stale data served during rebuild
17. `test_market_background_refresh` — Background refresh updates cache

### E. Pagination Tests (3)
18. `test_list_endpoints_paginate` — All list endpoints support pagination
19. `test_max_page_size_enforced` — Max page size enforced
20. `test_total_count_included` — Responses include total_count

### F. DB Optimization Tests (4)
21. `test_connection_pooling_active` — Pool active on all DB connections
22. `test_write_protection` — BEGIN IMMEDIATE on writes
23. `test_retry_on_lock` — Retries on "database is locked"
24. `test_db_cleanup_runs` — Cleanup job runs daily

### G. Timeout & Queuing Tests (3)
25. `test_per_endpoint_timeouts` — Endpoints respect configured timeouts
26. `test_timeout_returns_504` — Timeout → 504
27. `test_request_queuing` — Queue size configured

### H. Concurrency Tests (2)
28. `test_10_concurrent_requests` — 10 concurrent requests succeed
29. `test_no_connection_leaks_under_load` — Connection count stable

### I. Performance Monitoring Tests (2)
30. `test_response_time_tracking` — Response times tracked
31. `test_slow_endpoint_identified` — Slow endpoints flagged

### Regression Tests
- All 385 existing tests remain green

**Total new tests**: ~31

---

## 7. Acceptance Summary (Proposed)

| # | Finding | Severity | Acceptance |
|---|---|---|---|
| A | 10.1 Blocking backtest | Critical | Async processing, API responsive |
| A | 10.2 Expensive options | High | Caching, response time < 3s |
| A | 10.3 Market rebuild | High | Non-blocking, stale data during refresh |
| A | 10.4 Response caching | Medium | Caching for all endpoints, >50% hit rate |
| B | 7.2 Connection pooling | High | Pool implemented, times improved |
| B | 10.8 Query efficiency | Low | Query time < 3s, indexes added |
| B | 7.4 Write protection | Medium | BEGIN IMMEDIATE, retries on lock |
| B | 7.3 DB growth | Medium | Cleanup runs, size bounded |
| B | 10.5 Pagination | Medium | All list endpoints paginate |
| C | 9.8 Request queuing | Low | Queue configured, depth monitored |
| C | 10.7 Per-endpoint timeout | Low | Timeouts configured, return 504 |
| C | 10.6 Concurrency | Medium | 10 concurrent requests, no leaks |
| C | 10.1-10.8 comprehensive | — | All performance findings addressed |

**13 findings addressed. 0 model layer changes. 385/385 regression required. ~31 new tests.**

---

## 8. Concerns for Reviewer

1. **Caching vs B.3 protocol**: Must ensure caching never marks stale data as LIVE. This is the highest-risk B.4 change.
2. **Async backtests**: Moving from synchronous to async is a significant API contract change. Must document new behavior clearly.
3. **Connection pooling with SQLite**: SQLite has limited concurrency support. Pooling may not help as much as with PostgreSQL.
4. **B.3 protocol preservation**: Every B.4 change must be verified against B.3's failure scenarios. Performance work often breaks error handling.
5. **Scope size**: 13 findings is large. Consider whether some should be deferred to a B.5 cycle.

---

## 9. Verdict

- **SCOPE REVIEW COMPLETE** — Awaiting independent review of scope

**Reviewer**: User (independent decision)
**Date**: 2026-09-14
**Boundary**: 🔒 `6596cc7` — 385/385

**Decision options**:
- **APPROVE** → B.4 Specification
- **REVISE** → Update scope
- **SPLIT** → Move some findings to separate cycle

---

## 10. Next Steps

1. User reviews this scope review
2. User explicitly authorizes B.4 specification (separate from B.3)
3. B.4 Specification written (finding → requirement → boundary → tests → acceptance)
4. User reviews B.4 specification
5. User authorizes B.4 implementation
6. B.4 Implementation → tests → gates → independent review → freeze → STOP

---

*End of PHASE 6B-3 B.4 Scope Review — Performance & DB. Read-only. No implementation authorized.*
