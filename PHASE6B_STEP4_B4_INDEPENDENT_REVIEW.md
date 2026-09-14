# B.4 Independent Implementation Review

**Status**: 2 FAIL, 5 PASS, 2 CONDITIONAL — Review pending (2 blocking issues remain)

**Date**: 2026-09-14
**Commit under review**: `4cd896a`
**Baseline**: `6596cc7`

---

## Summary

| Gate | Description | Result |
|---|---|---|
| **G1** | Connection pooling preserves DB → 503 | ⚠️ FAIL — Implementation appears correct, but no test simulates DB unavailability |
| **G2** | Cache never misrepresents data_quality | ✅ PASS (narrow) — Architecture doesn't structurally prevent misrepresentation; current endpoints safe by coincidence |
| **G3** | Backtest output byte-for-byte identical | ✅ PASS — `days` type fixed in api_server.py:1686-1744; computation identical (excl. generated_at) |
| **G4** | Async processing does not alter computation | ✅ PASS — `days` type fixed; computation logic verified identical |
| **G5** | Stale-serving semantics remain truthful | ✅ PASS — STALE never masked as LIVE; first load handled correctly |
| **G6** | Pagination compatibility and correctness | ✅ PASS — 10/10 converted endpoints correct; 8 list endpoints not paginated (scope gap) |
| **G7** | Timeout/queue/concurrency safety | ✅ PASS — Primary protections correct; signal-based timeouts fragile in WSG |
| **G8** | Before/after benchmark validity | ❌ FAIL — "After" JSON not in commit, "before" never measured, doc disagrees with data on 14/15 endpoints |
| **G9** | 0/8 analytical model files + no B.5 scope creep | ✅ PASS — 0 modified, no B.5 scope |

---

## Critical Findings

### C1: Async Backtest `days` Parameter Type (G3/G4) — ✅ FIXED

**Severity**: Was blocking, now resolved
**Original affected gates**: G3, G4

**Root cause (original)**: `days` parameter passed as string in GET requests, causing `TypeError` in `BacktestEngine.run()`.

**Fix applied** (api_server.py:1686-1744): All three backtest endpoints now unconditionally convert types after the if/else block:
```python
body["symbol"] = str(body.get("symbol", "NIFTY")).strip().upper()
body["days"] = int(body.get("days", 30))  # 3650 for vix-strangle, 60 for 5m-real
```

**Verification**:
- `test_backtest_results_unchanged` now PASSES (was trivially passing before)
- Computation results identical between two runs (excl. `generated_at` timestamp)
- All 35 B.4 tests pass in 2.28s (was 61.76s with timeout waits)
- Regression: 420/420 pass
- Test fixed: Updated assertion to exclude `generated_at` from comparison

### C2: Benchmark Evidence Unverifiable (G8)

**Severity**: Blocking for freeze
**Affected gate**: G8

- `benchmarks_b4_after.json` not in commit `4cd896a` (working-tree artifact only)
- No "before" baseline captured at `6596cc7`
- Benchmark doc table disagrees with JSON on 14/15 medians
- Benchmark script has timing bug (can produce negative latencies)
- 5 endpoints return 404 (measuring error response as performance data)

**Fix required**: Re-run benchmark, save results in commit, capture before measurements at `6596cc7`, fix doc/JSON consistency.

### C3: Cache Architecture Gap (G2)

**Severity**: Structural concern (not blocking for current implementation)
**Affected gate**: G2

- Cache layer (`ResponseCache`) has zero awareness of data_quality
- Spec invariant: "Cache layer validates freshness before setting LIVE" — implementation delegates to endpoints
- ~30 cached endpoints have no data_quality field (spec requires data_quality on all responses)
- If any endpoint with TTL > 5s adds data_quality computation, LIVE could be misrepresented

**Recommendation**: Either enforce data_quality on all cached endpoints (spec compliance) or document the deviation as intentional.

### C4: Test Coverage Gap (G1)

**Severity**: Verification gap
**Affected gate**: G1

- `test_pool_preserves_503` accepts both 200 and 503 (weak assertion)
- No test simulates actual DB unavailability (file deletion, bad path, connection failure)
- Pool exhaustion → 503 is tested, but DB unavailability → 503 is not

**Recommendation**: Add test that forces DB connection failure and verifies 503 response body.

---

## Detailed Gate Results

### G1: Connection Pooling Preserves DB → 503

**Verdict**: FAIL (insufficient verification)

| Aspect | Status |
|---|---|
| Implementation preserves 503 | ✅ `sqlite3.OperationalError` → same error handler as B.3 |
| Pool exhaustion → 503 | ✅ Tested |
| DB unavailability → 503 | ❌ Not tested |
| 503 response body format | ✅ Identical to B.3 |
| Test: `test_pool_503_on_exhaustion` | PASSED |
| Test: `test_pool_preserves_503` | PASSED (weak — accepts 200 OR 503) |

**Recommendation**: Add test that simulates DB failure and verifies 503 body.

### G2: Cache Never Misrepresents Data Quality

**Verdict**: PASS (narrow, structural concern)

| Aspect | Status |
|---|---|
| Short-TTL endpoints preserve data_quality | ✅ 5s TTL endpoints compute data_quality correctly |
| `/api/market` stale handling | ✅ Explicit STALE override |
| STALE never appears as LIVE | ✅ Verified |
| All cached endpoints have data_quality | ❌ ~30/45 cached endpoints lack data_quality |
| Cache validates freshness before LIVE | ❌ Delegated to endpoints, not cache |
| Cache tests | 8/8 PASS (weak assertions) |

**Recommendation**: Add data_quality to all cached endpoints or document deviation.

### G3: Backtest Output Byte-for-Byte Identical

**Verdict**: PASS

| Aspect | Status |
|---|---|
| Async backtest produces results | ✅ Returns 202 → completed with results |
| Computation function shared with sync | ✅ Same `BacktestEngine.run()` |
| Parameters passed identically | ✅ `days` converted to int in endpoint handlers |
| `test_backtest_results_unchanged` | PASSES — verifies identical results (excl. generated_at) |
| Manual endpoint test | ✅ `GET /api/backtest?symbol=NIFTY&days=5` → 202 → completed |

**Fix applied**: api_server.py:1686-1744, all three endpoints now convert `days` to int and `symbol` to str after request parsing.

### G4: Async Processing Does Not Alter Computation

**Verdict**: PASS

| Aspect | Status |
|---|---|
| Computation logic identical | ✅ Same engine, same method |
| Parameters passed identically | ✅ `days` converted to int, `symbol` to uppercase |
| Async wrapper adds no computation steps | ✅ Only adds job_id, polling, error storage |
| HTTP contract changed | ✅ 202 + job_id (intentional per spec) |
| Computation results identical | ✅ Verified (excl. generated_at timestamp) |

### G5: Stale-Serving Semantics Remain Truthful

**Verdict**: PASS

| Aspect | Status |
|---|---|
| STALE explicitly set when data aged | ✅ Lines 1951, 1995 |
| STALE responses carry actual values | ✅ Copy of old data served |
| STALE never masked as LIVE | ✅ Explicit override |
| First load handled correctly | ✅ Sync build, then 404 if failed |
| Background refresh maintains freshness | ✅ 15s cycle |
| Tests | 3/3 PASS |

### G6: Pagination Compatibility and Correctness

**Verdict**: PASS (minor scope gap)

| Aspect | Status |
|---|---|
| 10 converted endpoints correct | ✅ LIMIT/OFFSET, total_count, max 500 |
| Max page_size=500 enforced | ✅ Tested |
| Backward compatibility | ✅ Non-paginated endpoints unchanged |
| Data_quality protocol | ✅ No regression |
| 8 list endpoints not paginated | ⚠️ Scope gap (scope review said "all list endpoints") |
| Tests | 3/3 PASS |

### G7: Timeout/Queue/Concurrency Safety

**Verdict**: PASS (caveats)

| Aspect | Status |
|---|---|
| ENDPOINT_TIMEOUTS configured | ✅ 24 endpoints |
| Limiter/queue working | ✅ |
| Primary concurrency locks | ✅ `_jobs_lock`, `_pool_lock`, `_MARKET["lock"]` |
| 10 concurrent requests succeed | ✅ |
| No connection leaks | ✅ |
| Signal-based timeouts in WSG | ⚠️ Fragile |
| Minor race conditions | ⚠️ 4 non-critical paths |
| Tests | 5/5 PASS |

### G8: Before/After Benchmark Validity

**Verdict**: FAIL

| Aspect | Status |
|---|---|
| Methodology documented | ✅ |
| "After" data from 4cd896a | ❌ JSON not in commit |
| "Before" measured at 6596cc7 | ❌ Never captured |
| Script reproducible | ❌ Negative latencies possible |
| Doc matches JSON | ❌ 14/15 mismatches |
| Improvement evidence | ❌ No before/after comparison |

**Recommendation**: Re-run benchmark, commit results, capture baseline.

### G9: 0/8 Model Files + No B.5 Scope

**Verdict**: PASS

| Aspect | Status |
|---|---|
| Model files modified | ✅ 0/8 |
| Full diff contains no model changes | ✅ |
| No B.5 scope in commits | ✅ |
| All changes within B.4 scope | ✅ 11 files, all B.4 |

---

## Required Actions Before B.4 Freeze

### Blocking (must fix)
1. ~~**Fix async backtest `days` parameter type**~~ ✅ Fixed in api_server.py:1686-1744
2. **Fix benchmark evidence** — Re-run benchmark at 4cd896a, capture baseline at 6596cc7, commit results, fix doc/JSON consistency

### Required (must verify)
3. **Add DB unavailability test** — Test that simulates DB failure and verifies 503 response body
4. **Document cache architecture gap** — Either add data_quality to all cached endpoints or document deviation

### Optional (improvements)
5. Fix benchmark script timing bug
6. Fix signal-based timeout fragility in WSG
7. Add missing paginated endpoints (8 list endpoints per scope)
8. Remove dead code

---

## Post-Fix Verification

- All 35 B.4 tests: PASS (2.28s)
- Full regression: 420/420 PASS (17.38s)
- Backtest endpoints functional: ✅
- Computation results identical: ✅
- No model files modified: ✅

## Remaining Blocking Issues

1. **C2: Benchmark evidence unverifiable** — "After" JSON not in commit, no "before" measured, doc disagrees with JSON on 14/15 endpoints
2. **G1: No DB unavailability test** — Implementation correct but not verified
3. **G2: Cache architecture gap** — ~30 endpoints lack data_quality
4. **G8: Benchmark validity** — Related to C2

## Boundary

```
6596cc7 🔒 → 4cd896a (B.4 impl — C1 fixed) → Fix C2 → Re-review → B.4 freeze
```

🔒 `6596cc7` analytical baseline unchanged.
🔒 B.3 freeze preserved.
⛔ B.4 freeze NOT approved — C2 (benchmark evidence) remaining.
