# PHASE 6B-3 B.4 — Implementation Specification: Performance & DB

**Scope**: Performance Optimization & Database Stability
**Status**: SPECIFICATION — AWAITING INDEPENDENT REVIEW
**Frozen baselines**: `45f90fc` (analytical/model), `51c02f9` (PHASE 6A), `63ab095` (PHASE 6B-1), `8bbd4d7` (PHASE 6B-2), `c39af34` (6B-3 Phase A), `3ec9473` (B.1), `cdf0f6a` (B.2), `6596cc7` (B.3)
**Regression baseline**: 385/385 passing
**B.3 dependencies**: DATA UNAVAILABLE/STALE/LIVE protocol, DB error → 503, data_quality on all responses

---

## Part 0: Implementation Boundaries

### Must NOT Change

- ❌ RegimeEngine calculations and thresholds
- ❌ StrategyEngine selection logic
- ❌ OptionsEngine computations
- ❌ Confidence mathematics
- ❌ Scenario normalization (Σ=1.00)
- ❌ LLM boundary (outlook.py merge logic)
- ❌ Backtest methodology (results must be identical)
- ❌ Historical validation methodology
- ❌ Any quantitative/model output
- ❌ Successful API response payloads (fields unchanged, only metadata added)
- ❌ All 385 existing tests must remain green
- ❌ Model layer files: regime.py, strategies.py, outlook.py, scenarios.py, options.py, ai_outlook.py, backtest.py, indicators.py
- ❌ data_quality field values (LIVE, STALE, DATA UNAVAILABLE, PARTIAL)

### Must Add

- ✅ Connection pooling for all DB access
- ✅ Response caching with data_quality integration
- ✅ Async backtest processing
- ✅ Non-blocking market data rebuild
- ✅ Pagination on all list endpoints
- ✅ Concurrent write protection (BEGIN IMMEDIATE)
- ✅ DB growth management (cleanup job)
- ✅ Per-endpoint timeout configuration
- ✅ Request queuing configuration
- ✅ Concurrency verification tests
- ✅ Performance before/after benchmarks

### Mandatory Invariants

| Invariant | Enforcement | Verification |
|---|---|---|
| Caching never misrepresents data_quality | Cache layer validates freshness before setting LIVE | `test_cache_never_misrepresents_quality` |
| Connection pooling preserves 503 | Pool catches DB errors → 503 | `test_pool_preserves_503` |
| No analytical output changes | Before/after comparison of all analytical endpoints | `test_analytical_outputs_unchanged` |
| Backtest methodology preserved | Results identical before/after async migration | `test_backtest_results_unchanged` |
| 385/385 regression | Full test suite runs green | CI gate |
| No model layer changes | `git diff 6596cc7 HEAD --name-only` | Review gate |

### State Transition Protocol

Performance optimization does not change failure states. The 5-state protocol from B.3 remains:

```
LIVE → STALE → DATA UNAVAILABLE → PARTIAL → SYSTEM DEGRADED
```

Caching must add **one** new transition that preserves integrity:

```
LIVE (fresh data) → CACHED LIVE (served from cache, still fresh)
                    → CACHED STALE (served from cache, aged)
                    → NEVER: CACHED LIVE when data is actually stale
```

---

## Part A: Connection Pooling (Finding 7.2)

### Finding

**Severity**: High
**Evidence**: `get_db()` creates a NEW sqlite3 connection every call. 55 endpoints × multiple queries = many connections per request. 3 gunicorn workers × 6 threads = 18 concurrent connections minimum, each with ~5-10ms creation overhead.

### Specification

#### Design

Replace per-request connection creation with a connection pool. SQLite supports `check_same_thread=False` for thread-safe sharing. Minimum implementation:

```python
import sqlite3
from threading import Lock

class ConnectionPool:
    def __init__(self, db_path, max_connections=10):
        self.db_path = db_path
        self.max_connections = max_connections
        self._pool = []
        self._lock = Lock()
        self._active = 0

    def get(self):
        with self._lock:
            if self._pool:
                conn = self._pool.pop()
                self._active += 1
                return conn
            if self._active < self.max_connections:
                conn = self._connect()
                self._active += 1
                return conn
            # Pool exhausted — wait with timeout
            # Return 503 behavior must be preserved
            raise sqlite3.OperationalError("Connection pool exhausted")

    def put(self, conn):
        with self._lock:
            self._active -= 1
            if len(self._pool) < self.max_connections:
                self._pool.append(conn)
            else:
                conn.close()

    def _connect(self):
        conn = sqlite3.connect(self.db_path, timeout=10, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=10000")
        return conn

    def close_all(self):
        with self._lock:
            for conn in self._pool:
                conn.close()
            self._pool.clear()
```

#### Integration

1. **Create `backend/db_pool.py`**: Connection pool class
2. **Replace `get_db()` in api_server.py**: Use pool instead of direct connect
3. **Preserve B.3 error handling**: Pool `get()` failures must map to 503 via existing `_handle_db_error`
4. **Add pool health endpoint**: `/api/health` includes pool status (active, available, exhausted)

#### B.3 Preservation

| B.3 Behavior | B.4 Preservation |
|---|---|
| DB failure → 503 | Pool failures → 503 (same handler) |
| WAL mode enabled | Pool connections use WAL |
| busy_timeout=10000 | Pool connections set busy_timeout |
| Data quality indicators | Unchanged by pooling |

#### Tests

| Test | Description |
|---|---|
| `test_connection_pool_exists` | Pool initialized on startup |
| `test_connection_reuse` | Same connection reused within request |
| `test_pool_503_on_exhaustion` | Pool exhaustion → 503 (not 500) |
| `test_connection_creation_reduced` | Connection creation time < 1ms after pool warmup |
| `test_pool_preserves_503` | DB failure through pool → 503 |

#### Acceptance Criteria

- Connection pool implemented for all DB access
- Connection creation time reduced by >90%
- Pool exhaustion returns 503 (preserves B.3)
- 385/385 tests pass
- 0 model files modified

---

## Part B: Response Caching (Findings 10.4, 10.2, 10.3)

### Finding 10.4: No Response Caching

**Severity**: Medium
**Evidence**: Only `/api/market` (20s TTL) and `/api/global` (90s TTL) have response caching. All other 53 endpoints have no caching.

### Specification

#### Cache Architecture

Per-endpoint TTL based on data freshness category:

| Category | Endpoints | TTL | Cache Key |
|---|---|---|---|
| Real-time | `/api/price`, `/api/prices`, `/api/indicators`, `/api/vix*` | 5s | endpoint + params |
| Daily | `/api/outlook*`, `/api/strategy*`, `/api/regime*`, `/api/scenarios*` | 1 hour | endpoint + params |
| Static | `/api/symbols`, `/api/etf*`, `/api/fundamentals*` | 24 hours | endpoint + params |
| Computation | `/api/backtest*`, `/api/options*`, `/api/pcr*`, `/api/maxpain*` | 10 minutes | endpoint + params |

#### B.3 Protocol Integration

**Critical**: Cache must integrate with B.3's data_quality protocol.

| Cache State | data_quality | data_freshness |
|---|---|---|
| Cache hit, data fresh | LIVE (unchanged) | age_minutes from original fetch |
| Cache hit, data aged | STALE (not LIVE) | age_minutes from original fetch, stale=true |
| Cache miss | Normal fetch + data_quality | Normal |
| Cache miss, no data | DATA UNAVAILABLE | N/A |

**Mandatory invariant**: `data_quality` is NEVER set to LIVE when the underlying data is actually stale. The cache stores the data_quality value from the time of fetch, not the current time.

#### Implementation

```python
import time
from threading import Lock

class ResponseCache:
    def __init__(self):
        self._store = {}
        self._lock = Lock()

    def _ttl_for_endpoint(self, endpoint):
        if endpoint in ("/api/price", "/api/prices", "/api/indicators", "/api/vix", "/api/vix/history", "/api/vix/daily"):
            return 5
        if endpoint in ("/api/outlook", "/api/outlooks", "/api/strategy", "/api/strategies", "/api/regime", "/api/regimes", "/api/scenarios"):
            return 3600
        if endpoint in ("/api/symbols", "/api/etf", "/api/etf-holdings", "/api/fundamentals"):
            return 86400
        if endpoint in ("/api/backtest", "/api/options", "/api/pcr", "/api/maxpain", "/api/oi-top", "/api/oi-concentration"):
            return 600
        return 0  # No caching

    def get(self, key):
        with self._lock:
            entry = self._store.get(key)
            if entry and (time.time() - entry["timestamp"]) < entry["ttl"]:
                return entry["value"]
            return None

    def set(self, key, value, ttl):
        with self._lock:
            self._store[key] = {
                "value": value,
                "timestamp": time.time(),
                "ttl": ttl,
            }

    def invalidate(self, key):
        with self._lock:
            self._store.pop(key, None)
```

#### Cache Integration Pattern

For each cached endpoint, the pattern is:

```python
@app.route("/api/price/<symbol>")
@cache(ttl=5)
def latest_price(symbol):
    # ... existing logic unchanged ...
    result = jsonify(quote)
    # result is a Response object — extract dict, add cache key
    if isinstance(result, dict):
        # data_quality already added by B.3 code
        cache.set(f"/api/price/{symbol}", result, ttl=5)
    return result
```

**Key principle**: The cache stores the complete response dict INCLUDING data_quality and data_freshness fields. On cache hit, the response is returned as-is — no re-computation of data_quality.

#### Before/After Evidence Requirement

For each cached endpoint, the specification must document:

| Endpoint | Before (avg ms) | After (avg ms) | Cache hit rate |
|---|---|---|---|
| `/api/price/NIFTY` | TBD | TBD | TBD |
| `/api/market` | TBD | TBD | TBD |
| `/api/options-intelligence/NIFTY` | TBD | TBD | TBD |

#### Tests

| Test | Description |
|---|---|
| `test_price_cache_5s` | Price endpoint caches for 5s |
| `test_cache_adds_data_quality` | Cached responses include data_quality |
| `test_cache_serves_stale_on_outage` | Cache serves stale with STALE flag |
| `test_cache_never_marks_stale_as_live` | STALE data never labeled LIVE |
| `test_options_cache_10min` | Options endpoints cache for 10min |
| `test_market_cache_20s` | Market endpoint caches for 20s |
| `test_cache_hit_rate_gt_50` | Overall cache hit rate > 50% |
| `test_cache_preserves_b3_protocol` | Cached responses pass B.3 validation |

#### Acceptance Criteria

- Response caching for all endpoint categories
- Cache hit rate > 50%
- data_quality preserved on cache hits
- STALE data never labeled LIVE
- 385/385 tests pass
- Before/after benchmarks documented
- 0 model files modified

---

## Part C: Async Backtest Processing (Finding 10.1)

### Finding

**Severity**: Critical
**Evidence**: `/api/backtest`, `/api/backtest/vix-strangle`, `/api/backtest/5m-real` run `BacktestEngine.run()` synchronously. Can take 30+ seconds. Blocks worker for entire duration.

### Specification

#### Design

Move backtests to async processing. Return `202 Accepted` with job ID. Poll endpoint for results.

```python
import uuid
import threading

_backtest_jobs = {}
_jobs_lock = threading.Lock()


def submit_backtest(job_id, params):
    """Run backtest in background thread."""
    try:
        result = BacktestEngine.run(**params)
        with _jobs_lock:
            _backtest_jobs[job_id] = {"status": "completed", "result": result}
    except Exception as e:
        with _jobs_lock:
            _backtest_jobs[job_id] = {"status": "failed", "error": str(e)}


@app.route("/api/backtest", methods=["POST"])
@limiter.limit("2/minute")
def backtest_async():
    """Submit backtest for async processing."""
    body = request.get_json(silent=True) or {}
    job_id = str(uuid.uuid4())[:12]

    # Validate input (same validation as before)
    errors = validate_backtest_payload(body)
    if errors:
        return error_response("INVALID_REQUEST", json.dumps(errors), 400)

    with _jobs_lock:
        _backtest_jobs[job_id] = {"status": "running", "started_at": datetime.now(timezone.utc).isoformat()}

    # Start background thread
    thread = threading.Thread(
        target=submit_backtest,
        args=(job_id, body),
        daemon=True,
    )
    thread.start()

    return jsonify({"job_id": job_id, "status": "running", "poll": f"/api/backtest/{job_id}"}), 202


@app.route("/api/backtest/<job_id>", methods=["GET"])
def backtest_poll(job_id):
    """Poll for backtest results."""
    with _jobs_lock:
        job = _backtest_jobs.get(job_id)

    if job is None:
        return error_response("NOT_FOUND", "Job not found", 404)

    if job["status"] == "running":
        return jsonify({"job_id": job_id, "status": "running"}), 202

    if job["status"] == "completed":
        return jsonify({"job_id": job_id, "status": "completed", "result": job["result"]})

    if job["status"] == "failed":
        return error_response("BACKTEST_FAILED", job["error"], 500)
```

#### B.3 Protocol Preservation

| Backtest Behavior | Async Equivalent |
|---|---|
| Synchronous result | 202 + job ID + poll endpoint |
| Backtest blocks worker | Worker freed immediately |
| Backtest error → 500 | Job error → stored → retrieved via poll → 500 |
| Backtest timeout → 504 | Job timeout → stored → retrieved via poll → 500 |
| Backtest results data | Identical results (methodology unchanged) |

#### Mandatory Invariant

**Backtest methodology must NOT change.** The `BacktestEngine.run()` function is called in the background thread with identical parameters. Results must be byte-for-byte identical to the synchronous version.

#### Tests

| Test | Description |
|---|---|
| `test_backtest_returns_202` | POST /api/backtest → 202 Accepted |
| `test_backtest_job_id` | Response includes job_id |
| `test_backtest_poll_endpoint` | GET /api/backtest/{id} returns status |
| `test_api_responsive_during_backtest` | Other endpoints work during backtest |
| `test_backtest_results_unchanged` | Async results identical to sync |

#### Acceptance Criteria

- Backtests run async
- API remains responsive during backtest
- Results identical to synchronous version
- 385/385 tests pass
- 0 model files modified

---

## Part D: Market Data Performance (Finding 10.3)

### Finding

**Severity**: High
**Evidence**: `/api/market` cache rebuild blocks for 20-60 seconds during cache miss. First caller blocks until done.

### Specification

#### Design

Serve stale data during rebuild instead of blocking. Add background refresh thread.

```python
import threading
import time

_market_cache = {"data": None, "timestamp": 0, "lock": threading.Lock(), "building": False}


def _refresh_market_background():
    """Background refresh that updates cache continuously."""
    while True:
        time.sleep(15)  # Refresh every 15 seconds during market hours
        try:
            data = _build_market()
            with _market_cache["lock"]:
                _market_cache["data"] = data
                _market_cache["timestamp"] = time.time()
                _market_cache["building"] = False
        except Exception as e:
            app.logger.error(f"Market refresh failed: {e}")
            with _market_cache["lock"]:
                _market_cache["building"] = False


@app.route("/api/market")
@limiter.limit("60/minute")
def market():
    with _market_cache["lock"]:
        if _market_cache["data"] is not None and (time.time() - _market_cache["timestamp"]) < 20:
            # Fresh data available
            data = _market_cache["data"]
        elif _market_cache["data"] is not None:
            # Stale data — serve it with STALE flag, rebuild in background
            if not _market_cache["building"]:
                _market_cache["building"] = True
                threading.Thread(target=_refresh_market_background, daemon=True).start()
            data = _market_cache["data"]
            data["data_quality"] = DATA_QUALITY_STALE
            data["data_freshness"] = {"age_minutes": round(time.time() - _market_cache["timestamp"]), "stale": True}
        else:
            # No data at all — build synchronously (first request)
            data = _build_market()
            if data:
                _market_cache["data"] = data
                _market_cache["timestamp"] = time.time()
    return jsonify(data)
```

#### B.3 Protocol Preservation

- Stale data served with `data_quality: "STALE"` (B.3 invariant)
- No data → DATA UNAVAILABLE (B.3 invariant)
- Fresh data → LIVE (B.3 invariant)

#### Tests

| Test | Description |
|---|---|
| `test_market_non_blocking` | Market request doesn't block for >5s |
| `test_market_stale_during_rebuild` | Stale data served during rebuild |
| `test_market_background_refresh` | Cache refreshes automatically |

---

## Part E: List Endpoint Pagination (Finding 10.5)

### Finding

**Severity**: Medium
**Evidence**: `/api/symbols`, `/api/strategies`, `/api/outlooks`, etc. return ALL matching rows. No pagination.

### Specification

#### Design

All list endpoints accept `page` and `page_size` parameters:

```python
# Example: /api/strategies?page=1&page_size=50
page = request.args.get("page", 1, type=int)
page_size = request.args.get("page_size", 50, type=int)
page_size = min(page_size, 500)  # Enforce max
offset = (page - 1) * page_size

rows = conn.execute("SELECT * FROM strategies LIMIT ? OFFSET ?", (page_size, offset)).fetchall()
total = conn.execute("SELECT COUNT(*) FROM strategies").fetchone()[0]

return jsonify({
    "data": [row_to_dict(r) for r in rows],
    "pagination": {
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": (total + page_size - 1) // page_size,
    },
})
```

#### Tests

| Test | Description |
|---|---|
| `test_list_endpoints_paginate` | All list endpoints support pagination |
| `test_max_page_size_enforced` | Max page_size = 500 |
| `test_total_count_included` | Responses include total_count |

---

## Part F: Database Optimization (Findings 7.4, 7.3, 10.8, 7.6)

### Finding 7.4: No Concurrent Write Protection

**Severity**: Medium
**Specification**: Use `BEGIN IMMEDIATE` for write transactions. Retry on "database is locked" (up to 3 times).

```python
def _execute_write(conn, query, params=None, max_retries=3):
    for attempt in range(max_retries):
        try:
            conn.execute("BEGIN IMMEDIATE")
            if params:
                conn.execute(query, params)
            else:
                conn.execute(query)
            conn.commit()
            return True
        except sqlite3.OperationalError as e:
            conn.rollback()
            if "database is locked" in str(e) and attempt < max_retries - 1:
                time.sleep(0.1 * (attempt + 1))
                continue
            raise
```

### Finding 7.3: DB Growth Management

**Severity**: Medium
**Specification**: Add cleanup cron job enforcing retention policies from `config/instruments.json`.

### Finding 10.8: DB Query Efficiency

**Severity**: Low
**Specification**: Add composite indexes for frequent queries. Batch options queries.

### Finding 7.6: Chat Cleanup Optimization

**Severity**: Low
**Specification**: Optimize DELETE query for chat_messages.

#### Tests

| Test | Description |
|---|---|
| `test_write_protection` | BEGIN IMMEDIATE on writes |
| `test_retry_on_lock` | Retries on database lock |
| `test_cleanup_runs` | Cleanup job runs daily |
| `test_db_size_bounded` | DB size within bounds |
| `test_indexes_exist` | Required indexes present |
| `test_chat_cleanup_fast` | Chat cleanup < 1s on 100k rows |

---

## Part G: Timeout & Queuing (Findings 10.7, 9.8)

### Finding 10.7: Per-Endpoint Timeout

**Severity**: Low
**Specification**: Configure per-endpoint timeouts. Data: 5s, Computation: 60s, Health: 2s, Options: 10s. Return 504 on timeout.

### Finding 9.8: Request Queuing

**Severity**: Low
**Specification**: Configure queue size limit. Monitor queue depth.

#### Tests

| Test | Description |
|---|---|
| `test_per_endpoint_timeouts` | Endpoints respect timeouts |
| `test_timeout_returns_504` | Timeout → 504 |
| `test_request_queuing` | Queue configured |

---

## Part H: Concurrency Testing (Finding 10.6)

### Finding

**Severity**: Medium
**Specification**: Simulate 10 concurrent requests. Monitor for leaks, timeouts, corruption.

#### Tests

| Test | Description |
|---|---|
| `test_10_concurrent_requests` | 10 concurrent requests succeed |
| `test_no_connection_leaks_under_load` | Connection count stable |
| `test_no_data_corruption_under_load` | Data integrity verified after concurrent test |

---

## Part I: Performance Benchmark Protocol

### Before/After Evidence

For every optimization, document before/after benchmarks:

| Endpoint | Before (ms) | After (ms) | Improvement |
|---|---|---|---|
| /api/price/NIFTY | TBD | TBD | TBD |
| /api/market | TBD | TBD | TBD |
| /api/options-intelligence/NIFTY | TBD | TBD | TBD |
| /api/backtest | TBD | TBD | TBD |
| /api/price/NIFTY (concurrent) | TBD | TBD | TBD |

### Benchmark Method

1. Baseline measured at 6596cc7
2. After measurement at B.4 implementation commit
3. Same test data, same environment
4. 10 measurements each, median reported
5. Results documented in B.4 freeze review

---

## Part J: State Transition Protocol

### B.4 Does NOT Change Failure States

| B.3 State | B.4 Behavior |
|---|---|
| LIVE | Caching may serve from cache, but data_quality unchanged |
| STALE | Cache serves stale with STALE flag (never LIVE) |
| DATA UNAVAILABLE | Cache miss → normal fetch → same behavior |
| PARTIAL | Same as B.3 |
| SYSTEM DEGRADED | Same as B.3 |

### B.4 New Transitions (Performance Optimizations)

```
LIVE (fresh) → [cache hit, fresh] → CACHED LIVE (served from cache, still LIVE)
LIVE (fresh) → [cache hit, aged] → CACHED STALE (served from cache, now STALE)
CACHED STALE → [background refresh] → LIVE (fresh data verified)
```

**Critical**: `CACHED LIVE` is only valid when the cached data is actually fresh (within TTL). If TTL expired, the data is `CACHED STALE`.

---

## Part K: Test Plan Summary

### Connection Pooling Tests (5)
1. `test_connection_pool_exists`
2. `test_connection_reuse`
3. `test_pool_503_on_exhaustion`
4. `test_connection_creation_reduced`
5. `test_pool_preserves_503`

### Response Caching Tests (8)
6-13: All cache tests including data_quality preservation

### Async Backtest Tests (5)
14-18: Async processing tests including results verification

### Market Data Tests (3)
19-21: Non-blocking, stale-serve, background refresh

### Pagination Tests (3)
22-24: Pagination, max page size, total count

### DB Optimization Tests (6)
25-30: Write protection, retry, cleanup, indexes, chat cleanup

### Timeout & Queuing Tests (3)
31-33: Timeouts, 504, queue

### Concurrency Tests (2)
34-35: Concurrent requests, no leaks

### Regression
385 existing tests mandatory

**Total new tests**: ~35

---

## Part L: Acceptance Summary

| # | Finding | Severity | Acceptance |
|---|---|---|---|
| A | 7.2 Connection pooling | High | Pool implemented, 503 preserved |
| A | 10.4 Response caching | Medium | Caching for all, >50% hit rate |
| A | 10.2 Options caching | High | Options cached, <3s response |
| A | 10.3 Market rebuild | High | Non-blocking, stale served |
| B | 10.1 Async backtest | Critical | Async, results identical |
| B | 10.5 Pagination | Medium | All lists paginate |
| C | 7.4 Write protection | Medium | BEGIN IMMEDIATE, retries |
| C | 7.3 DB growth | Medium | Cleanup runs, size bounded |
| C | 10.8 Query efficiency | Low | Query time <3s, indexes added |
| C | 7.6 Chat cleanup | Low | Cleanup <1s |
| D | 10.7 Per-endpoint timeout | Low | Timeouts configured |
| D | 9.8 Request queuing | Low | Queue configured |
| D | 10.6 Concurrency | Medium | 10 concurrent, no leaks |
| — | Before/after benchmarks | — | Documented for all endpoints |

**13 findings addressed. ~35 new tests. 0 model files modified. 385/385 regression. Before/after evidence for all optimizations.**

---

## Part M: Post-Implementation Verification

1. **Run 385/385 regression** — must pass
2. **Run all ~35 B.4 tests** — must pass
3. **Verify model layer untouched** — `git diff 6596cc7 HEAD --name-only` shows no model files
4. **Verify data_quality preserved** — all cached responses include data_quality with correct values
5. **Verify 503 preserved** — simulate DB failure, confirm 503 (not 500)
6. **Verify backtest results identical** — compare before/after results
7. **Verify before/after benchmarks** — measure and document
8. **Commit and freeze** — B.4 commit, then freeze before B.5

---

*End of PHASE 6B-3 B.4 Specification: Performance & DB. Awaiting independent review.*
