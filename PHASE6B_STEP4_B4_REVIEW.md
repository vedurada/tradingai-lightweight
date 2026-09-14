# PHASE 6B-3 B.4 — Independent Specification Review

**Status**: SPECIFICATION REVIEW — AWAITING REVIEWER DECISION

**Specification**: `PHASE6B_STEP4_B4_SPECIFICATION.md`

**Frozen baseline**: `6596cc7` 🔒

**Regression baseline**: 385/385

**Implementation**: NOT AUTHORIZED ⛔

---

## 1. Reviewer Checklist — 9 Critical Gates

Each gate must be verified before B.4 specification can be approved:

| # | Gate | Specification Section | Verification Method | Status |
|---|---|---|---|---|
| 1 | Cache/data-quality integrity | Part B | Cache hit/miss must preserve truthful data_quality; STALE never labeled LIVE | ⬜ PENDING |
| 2 | DB pooling and 503 preservation | Part A | Pool exhaustion → 503; DB failure through pool → 503 | ⬜ PENDING |
| 3 | Byte-for-byte backtest equivalence | Part C | Async results identical to sync; methodology unchanged | ⬜ PENDING |
| 4 | Async job correctness | Part C | 202 → poll → result flow; no data corruption | ⬜ PENDING |
| 5 | Stale-data semantics | Parts B, D | Stale data served with STALE; never as LIVE | ⬜ PENDING |
| 6 | Concurrency safety | Part H | 10 concurrent requests; no leaks, no corruption | ⬜ PENDING |
| 7 | Timeout/queue boundaries | Part G | Endpoints respect timeouts; queue bounded; 504 on timeout | ⬜ PENDING |
| 8 | Benchmark methodology | Part I | Before/after measurements reproducible | ⬜ PENDING |
| 9 | Zero analytical/model-layer changes | Part 0 | 0/8 model files; no analytical output changes | ⬜ PENDING |

---

## 2. Gate Verification Detail

### Gate 1: Cache/Data-Quality Integrity

**What to verify**:

| Scenario | Expected | Must NOT |
|---|---|---|
| Cache hit, data fresh | data_quality = LIVE | data_quality = LIVE on stale data |
| Cache hit, data aged | data_quality = STALE | data_quality = LIVE |
| Cache miss, no data | data_quality = DATA UNAVAILABLE | data_quality = LIVE |
| Cache miss, fresh data | data_quality = LIVE | — |
| Background refresh | Fresh data → LIVE | Stale data promoted to LIVE |

**Verification**: All 8 cache tests in spec Part B must pass. Specifically `test_cache_never_marks_stale_as_live`.

### Gate 2: DB Pooling and 503 Preservation

**What to verify**:

| Scenario | Expected | Must NOT |
|---|---|---|
| Pool healthy | Normal DB access | — |
| Pool exhausted | 503 SERVICE_DEGRADED | 500, timeout, or hang |
| DB failure through pool | 503 SERVICE_DEGRADED | 500, stack trace |
| Connection leak under load | Connection count stable | Growing connection count |
| WAL mode | Enabled on pool connections | Disabled |

**Verification**: All 5 pooling tests in spec Part A must pass. Specifically `test_pool_preserves_503`.

### Gate 3: Byte-for-Byte Backtest Equivalence

**What to verify**:

| Aspect | Expected | Must NOT |
|---|---|---|
| Backtest results | Identical before/after async migration | Any difference in results |
| Backtest methodology | BacktestEngine.run() called with same params | Modified algorithm |
| Backtest output format | Same JSON structure | Different shape |
| Backtest timing | May be faster (async) | Slower |

**Verification**: `test_backtest_results_unchanged` must demonstrate byte-for-byte equivalence.

### Gate 4: Async Job Correctness

**What to verify**:

| Aspect | Expected | Must NOT |
|---|---|---|
| Submit | 202 + job_id | 500, synchronous block |
| Poll (running) | 202 + status: running | Timeout, 500 |
| Poll (completed) | Result data | Empty, error |
| Poll (failed) | Error message | Silent failure |
| Concurrent jobs | All complete independently | Race conditions |
| Memory | Jobs cleaned up after completion | Memory leak |

**Verification**: All async backtest tests in spec Part C must pass.

### Gate 5: Stale-Data Semantics

**What to verify**:

| Scenario | Expected | Must NOT |
|---|---|---|
| Market rebuild in progress | STALE flag set | LIVE flag on stale data |
| Background refresh complete | LIVE flag restored | STALE persists |
| Data source unavailable | DATA UNAVAILABLE | Manufactured values |
| API available, data stale | STALE + age_minutes | LIVE + stale data |
| B.3 data_quality fields | Preserved by all B.4 changes | Removed or altered |

**Verification**: Market data tests in spec Part D + B.3 data_quality tests.

### Gate 6: Concurrency Safety

**What to verify**:

| Aspect | Expected | Must NOT |
|---|---|---|
| 10 concurrent requests | All complete | Deadlocks, timeouts |
| Connection pool under load | Stable count | Connection leaks |
| Cache under concurrent access | Consistent reads | Corrupted data |
| Write transactions | BEGIN IMMEDIATE, retries | Silent conflicts |
| Data integrity | No corruption after concurrent test | Changed data |

**Verification**: All concurrency tests in spec Part H.

### Gate 7: Timeout/Queue Boundaries

**What to verify**:

| Aspect | Expected | Must NOT |
|---|---|---|
| Data endpoint timeout | 5s → 504 | No timeout, 500 |
| Computation endpoint timeout | 60s → 504 | No timeout |
| Queue size | Bounded | Unbounded growth |
| Queue depth monitoring | Available | No visibility |
| Bounded resource failure | Deterministic 503/504 | Indeterminate hang |

**Verification**: All timeout/queue tests in spec Part G.

### Gate 8: Benchmark Methodology

**What to verify**:

| Aspect | Expected | Must NOT |
|---|---|---|
| Before measurement | At 6596cc7, median of 10 runs | Single measurement |
| After measurement | At B.4 commit, same conditions | Different environment |
| Same test data | Identical payloads | Different data |
| Reproducibility | Multiple runs consistent | Wild variance |
| Documentation | Per-endpoint before/after table | No documentation |

**Verification**: Benchmark table in spec Part I is filled in at freeze review.

### Gate 9: Zero Analytical/Model-Layer Changes

**What to verify**:

| Aspect | Expected | Must NOT |
|---|---|---|
| Model files | 0/8 modified | Any modification |
| Analytical outputs | Identical before/after | Any change in regime, strategy, confidence |
| LLM boundary | Unchanged | Modified outlook.py logic |
| Backtest results | Byte-for-byte identical | Different results |
| API successful responses | Fields unchanged | Changed payloads |

**Verification**: `git diff 6596cc7 HEAD --name-only` shows no model files. Analytical output comparison test.

---

## 3. Gate Traceability

Each gate maps to specific tests in the specification:

| Gate | Key Tests | Gate Count |
|---|---|---|
| 1. Cache/data-quality | test_cache_never_marks_stale_as_live, test_cache_adds_data_quality, test_cache_preserves_b3_protocol | 8 tests |
| 2. DB pooling/503 | test_pool_preserves_503, test_pool_503_on_exhaustion, test_connection_reuse | 5 tests |
| 3. Backtest equivalence | test_backtest_results_unchanged | 1 test (critical) |
| 4. Async jobs | test_backtest_returns_202, test_backtest_poll_endpoint, test_api_responsive_during_backtest | 5 tests |
| 5. Stale semantics | test_market_stale_during_rebuild, test_cache_serves_stale_on_outage | 3 tests |
| 6. Concurrency | test_10_concurrent_requests, test_no_connection_leaks_under_load | 2 tests |
| 7. Timeout/queue | test_timeout_returns_504, test_per_endpoint_timeouts | 3 tests |
| 8. Benchmarks | Before/after table (documented at freeze) | 0 tests (documented) |
| 9. Model boundary | git diff verification | 0 tests (verified at review) |

**Total**: 32 tests across 9 gates

---

## 4. Concerns for Reviewer

1. **Cache + B.3 protocol**: Cache layer adds complexity to B.3's data_quality protocol. The risk of accidentally marking stale data as LIVE is real.
2. **Async backtest migration**: Moving synchronous → async changes API contract (202 vs 200). Existing clients may break.
3. **Connection pooling with SQLite**: SQLite's concurrency model limits pooling effectiveness. Pooling may help less than expected.
4. **Scope size**: 13 findings is large for one cycle. Some could be deferred.
5. **Benchmark rigor**: Before/after benchmarks are specified but need disciplined execution at freeze review.

---

## 5. Verdict

| Option | Status |
|---|---|
| **APPROVE** → formal B.4 specification approval | Awaiting reviewer |
| **REVISE** → update specification | Awaiting reviewer |
| **SPLIT** → move some findings to separate cycle | Awaiting reviewer |

**Reviewer**: User (independent decision)
**Date**: 2026-09-14
**Boundary**: 🔒 `6596cc7` — 385/385

---

## 6. Decision Record

| Decision | Date | Notes |
|---|---|---|
| | | |

---

## 7. If Approved: Next Step

If this specification is approved, the next step is **explicit implementation authorization**:

```
Authorize PHASE 6B-3 B.4 implementation — Performance & DB
```

This authorization is **separate** from the specification approval. Implementation requires its own authorization, independent review, and freeze.

**Current state**: Specification review pending. **No implementation authorized.**

---

*End of PHASE 6B-3 B.4 Independent Specification Review.*
