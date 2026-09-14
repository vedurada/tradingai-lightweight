# PHASE 6B-1 — Read-Only Implementation Specification

**Scope**: Reliability & Database (Database Stability + API Reliability + Data-Source Resilience)
**Status**: READ-ONLY SPECIFICATION — No code changes authorized yet
**Frozen baselines**: `45f90fc` (analytical/model), `51c02f9` (PHASE 6A productization)
**Regression baseline**: 194/194 passing
**Audit source**: PHASE6B_PRODUCTION_HARDENING_AUDIT.md (61 findings, 5 Critical, 20 High, 36 Medium, 22 Low)
**Priority ordering**: Reliability → Stale-data → Abuse → Monitoring → CI → Security → Performance → Deployment

---

## Objective

Define exactly how to fix the database, API reliability, and external-data-source issues identified in the PHASE 6B audit, so that after implementation:

1. The API never hangs on database operations (timeout + WAL)
2. Connections never leak on error paths (context managers + try/finally)
3. All errors follow one schema (frontend can handle one shape)
4. Partial data is communicated uniformly (data_completeness flags)
5. External API failures degrade gracefully (circuit breaker + retry)
6. All 194 existing tests still pass
7. Model layer remains untouched (zero changes to regime.py, strategies.py, outlook.py, scenarios.py, options.py, ai_outlook.py, backtest.py, indicators.py)

---

## Part A: Database & Resource Stability

---

### A.1 SQLite WAL Mode + Busy Timeout [CRITICAL]

**Audit reference**: Dimension 7, Finding 7.1
**Effort**: S
**Affects model layer**: No

**Current state**: `backend/database.py:16-19`, `backend/api_server.py`, `db_schema.py` — All `sqlite3.connect()` calls use default journal mode (DELETE). Default mode means readers block writers and writers block readers. Under concurrent access (3 gunicorn workers × 2 threads = 6 threads + cron + self-heal), this causes lock contention and timeout cascades.

**Specification**:

1. **Add WAL pragma at DB initialization** in `db_schema.py` — after `c.executescript(SCHEMA)`, add:
   ```python
   c.execute("PRAGMA journal_mode=WAL")
   c.execute("PRAGMA busy_timeout=10000")
   ```

2. **Add WAL pragma at connection time** in all three `get_db()` implementations:
   - `backend/api_server.py:get_db()` (line 22-25)
   - `backend/database.py:_conn()` (line 16-19)
   - `backend/data_fetcher_db.py:get_db()` (line 40-44)

   Each should execute after `sqlite3.connect()`:
   ```python
   conn.execute("PRAGMA journal_mode=WAL")
   conn.execute("PRAGMA busy_timeout=10000")
   ```

3. **Ensure `wal_checkpoint_on_close`** is set to 1 for clean shutdown:
   ```python
   conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
   ```

**Acceptance criteria**:
- WAL mode confirmed: `PRAGMA journal_mode` returns `wal` on every connection
- busy_timeout confirmed: `PRAGMA busy_timeout` returns `10000` on every connection
- Concurrent read/write test: 10 threads writing + 10 threads reading simultaneously for 60 seconds with zero "database is locked" errors
- 194 tests still pass
- No model layer files modified (regime.py, strategies.py, outlook.py, scenarios.py, options.py, ai_outlook.py, backtest.py, indicators.py untouched)

**Test plan**:
- Add to `tests/test_phase6a.py` (or new `tests/test_phase6b_1.py`):
  - `test_wal_mode_enabled`: Connect to DB, check `PRAGMA journal_mode` = `wal`
  - `test_busy_timeout_set`: Check `PRAGMA busy_timeout` = `10000`
  - `test_concurrent_read_write_no_lock_errors`: Spawn 10 writer threads + 10 reader threads, run 60 seconds, assert zero lock errors

**Affected files**:
- `backend/db_schema.py` — Add WAL + busy_timeout after schema creation
- `backend/api_server.py:get_db()` — Add pragma after connect
- `backend/database.py:_conn()` — Add pragma after connect
- `backend/data_fetcher_db.py:get_db()` — Add pragma after connect
- `tests/test_phase6a.py` or `tests/test_phase6b_1.py` — Add WAL verification tests

---

### A.2 Connection Timeout on All sqlite3.connect() Calls [HIGH]

**Audit reference**: Dimension 1, Finding 1.2
**Effort**: S
**Affects model layer**: No

**Current state**: Three `sqlite3.connect()` calls across 3 files have no `timeout=` parameter:
- `backend/api_server.py:22-25` — `conn = sqlite3.connect(DB_PATH)`
- `backend/database.py:17-19` — `conn = sqlite3.connect(self.db_path)`
- `backend/data_fetcher_db.py:42-44` — `conn = sqlite3.connect(DB_PATH)`

**Specification**:

1. **Add `timeout=10`** to all `sqlite3.connect()` calls (3 locations):
   ```python
   conn = sqlite3.connect(DB_PATH, timeout=10)
   ```

2. **Add `check_same_thread=False`** where connections may be shared across threads (only in `api_server.py:get_db()` since gunicorn is multi-threaded):
   ```python
   conn = sqlite3.connect(DB_PATH, timeout=10, check_same_thread=False)
   ```

   **Important**: `check_same_thread=False` must be paired with proper locking or connection-per-request pattern. Do NOT share a single connection object across threads. Each request still gets its own connection, but `check_same_thread=False` prevents crashes if the connection object is accessed from an unexpected thread context (e.g., Flask test client).

3. **Combine with A.1**: The `timeout=` parameter works with WAL mode and `busy_timeout` to handle lock contention gracefully. Under WAL mode, readers don't block writers, so `timeout` is primarily for edge cases.

**Acceptance criteria**:
- All 3 `sqlite3.connect()` calls include `timeout=` parameter (verified by AST scan, not grep)
- Test simulates DB lock: hold write lock in thread 1, attempt connect in thread 2, verify it waits up to 10s then returns (doesn't hang indefinitely)
- 194 tests still pass
- No model layer files modified

**Test plan**:
- `test_db_timeout_set`: AST parse all 3 files, find all `sqlite3.connect(` calls, assert `timeout=` parameter present
- `test_db_timeout_behavior`: Create a thread holding an exclusive lock, attempt connect from another thread, verify either (a) succeeds within 10s or (b) raises `sqlite3.OperationalError` after 10s — never hangs forever

**Affected files**:
- `backend/api_server.py:get_db()` — Add timeout + check_same_thread
- `backend/database.py:_conn()` — Add timeout
- `backend/data_fetcher_db.py:get_db()` — Add timeout

---

### A.3 Connection Leak Prevention on Error Paths [HIGH]

**Audit reference**: Dimension 1, Finding 1.3 + Dimension 7, Finding 7.5
**Effort**: M
**Affects model layer**: No

**Current state**: Every endpoint opens a connection and calls `conn.close()` at the end. Error paths (early returns, exceptions) bypass close. Specifically:
- `backend/api_server.py:_symbol_data()` (lines 464-525): opens connection at 466, `conn.close()` at 524. If ANY exception occurs between, connection leaks. No try/finally.
- `backend/api_server.py:_build_quote()` (lines 277-325): opens nested connection at 302-304 (inside `_symbol_data` which already holds a connection). If exception before line 314, nested connection leaks.
- `backend/api_server.py:options_intelligence()` (lines 750-876): 126 lines with multiple `except Exception: pass` blocks (lines 858, 890, 900) where connection close may be skipped.
- `backend/api_server.py:market_outlook_latest()` (lines 894-917): connection close at 908 and 915, but only if no exception in `merge_llm_into_payload` call.
- `backend/api_server.py:portfolio_add()` (lines 962-982), `portfolio_delete()` (lines 984-990): conn.close() after commit, but exception before close leaks.
- `backend/database.py`: Every method (`execute`, `fetchone`, `fetchall`, `upsert`, `get_latest`, `fetchall`, `cleanup_old_data`, `save_history`, etc.) opens and closes connections individually. Exceptions between open and close leak.

**Specification**:

1. **`_symbol_data()` — wrap in try/finally** (line 466):
   ```python
   def _symbol_data(symbol):
       symbol = (symbol or "").upper()
       conn = get_db()
       try:
           # ... existing 10+ queries ...
       finally:
           conn.close()
   ```

2. **`_build_quote()` — remove nested connection** (lines 302-314). This function is called from `_symbol_data()` which already holds an open connection. Instead of opening a new connection for the `price_1d` fallback, reuse the existing connection:
   ```python
   def _build_quote(symbol, price_row, live_row=None, conn=None):
       # ... existing logic ...
       if not prev and conn is not None:
           prow = conn.execute("SELECT close FROM price_1d WHERE symbol=? ORDER BY timestamp DESC LIMIT 2", (symbol,)).fetchall()
           # ... rest of logic ...
   ```
   Update caller in `_symbol_data` to pass `conn`:
   ```python
   quote = _build_quote(symbol, price_row, _live_quote_row(conn, symbol), conn=conn)
   ```

3. **All endpoint functions** — Replace `conn = get_db(); ...; conn.close()` pattern with `with get_db() as conn:` using context manager. Add a `__enter__`/`__exit__` to connection or use:
   ```python
   conn = get_db()
   try:
       # queries
   finally:
       conn.close()
   ```

4. **`Database` class methods** (`backend/database.py`) — Wrap each method's connection in try/finally:
   ```python
   def execute(self, sql, params=()):
       conn = self._conn()
       try:
           c = conn.cursor()
           c.execute(sql, params)
           conn.commit()
           return c
       finally:
           conn.close()
   ```
   Same pattern for: `fetchone`, `fetchall`, `upsert`, `get_latest`, `cleanup_old_data`, `save_history`, `get_history`, `get_all_history`, `archive_history`, `archive_old_history`, `save_portfolio`, `close_portfolio`, `get_portfolio`, `get_portfolio_summary`.

5. **`get_db()` in `api_server.py` and `data_fetcher_db.py`** — Add a connection tracker for observability:
   ```python
   _active_connections = 0
   _connection_peak = 0

   def get_db():
       global _active_connections, _connection_peak
       _active_connections += 1
       if _active_connections > _connection_peak:
           _connection_peak = _active_connections
       conn = sqlite3.connect(DB_PATH, timeout=10, check_same_thread=False)
       conn.row_factory = sqlite3.Row
       return conn
   ```
   And in the finally of every caller, decrement:
   ```python
   finally:
       conn.close()
       _active_connections -= 1
   ```

**Acceptance criteria**:
- Connection count on error paths is zero after 1000 error-inducing requests (simulate: send requests that trigger 404s, 500s, exceptions)
- Memory stable after error storm: RSS does not grow by more than 5MB over 1000 error requests
- Every `get_db()` call in `api_server.py` is within a try/finally or context manager
- Every `Database` method in `database.py` wraps connection in try/finally
- 194 tests still pass
- No model layer files modified

**Test plan**:
- `test_no_connection_leak_on_error`: Send 1000 requests that trigger 404s and exceptions, check `_active_connections` == 0 after each batch
- `test_memory_stable_after_error_storm`: RSS before/after 1000 error requests, delta < 5MB
- `test_all_db_methods_have_try_finally`: AST scan — verify every method in `Database` class that creates a connection has try/finally pattern

**Affected files**:
- `backend/api_server.py` — `_symbol_data`, `_build_quote`, all endpoint functions, `_build_market`
- `backend/database.py` — ALL methods that create connections
- `backend/data_fetcher_db.py` — `get_db()` (minor, timeout from A.2)
- `tests/test_phase6b_1.py` — New test file

---

### A.4 Unified Partial-Data Policy [MEDIUM]

**Audit reference**: Dimension 1, Finding 1.4
**Effort**: M
**Affects model layer**: No

**Current state**: When partial data exists, endpoints behave inconsistently:
- `/api/price/<symbol>`: Falls back to `price_1d` if both `price_1m` and `live_quotes` empty, returns 404 if neither exists
- `/api/<symbol>`: Returns partial `_symbol_data` (may have quote but no strategy, or vice versa) with 200 — no indication of which fields are populated
- `/api/market`: Returns `{}` if market data unavailable, `{"instruments": {}, ...}` if symbols exist but no prices — different empty shapes
- `/api/options-intelligence`: Returns `{"symbol": X, "spot": null, "data_quality": "LIVE", ...}` with null fields when no option chain exists
- `/api/vix`: Returns `{"error": "no VIX data"}` with 404 vs `/api/prices` returning `[]` with 200 for no data

**Specification**:

1. **Add `_data_completeness` helper function** in `api_server.py`:
   ```python
   def _data_completeness(**fields):
       return {k: bool(v) for k, v in fields.items()}
   ```

2. **`/api/<symbol>` — add `data_completeness` to response**:
   ```python
   result["data_completeness"] = _data_completeness(
       quote=bool(result.get("quote")),
       indicators=bool(result.get("indicators")),
       regime=bool(result.get("regime")),
       strategy=bool(result.get("strategy")),
       scenarios=bool(result.get("scenarios")),
       outlook=bool(result.get("ai_outlook")),
   )
   ```

3. **`/api/market` — add `data_completeness` to response**:
   ```python
   return {
       "source": "TradingAI DB (AI-assisted)",
       "last_updated": latest_ts,
       "data_quality": ...,
       "ai_outlook": nifty_ai,
       "instruments": instruments,
       "data_completeness": {
           "instruments": bool(instruments),
           "ai_outlook": bool(nifty_ai),
           "has_prices": any(bool(v.get("quote")) for v in instruments.values()),
       },
   }
   ```

4. **`/api/price/<symbol>` and `/api/prices/<symbol>` — add `stale` flag**:
   - If data comes from `price_1d` fallback (not `price_1m` or `live_quotes`), set `"stale": True` in response
   - If data is fresh from `price_1m` or `live_quotes`, `"stale": False`

5. **`/api/options-intelligence` — fix data_quality** (finding 6.6):
   - If `option_chain` has 0 rows → `"data_quality": "DATA UNAVAILABLE"` (not `"LIVE"`)
   - If spot is null → `"data_quality": "DATA UNAVAILABLE"`
   - Only `"LIVE"` when both spot and option_chain data exist

6. **All error responses** — see A.5 (unified schema). Empty results should return 200 with empty array/dict, NOT 404 with error (unless genuinely no data exists, in which case 404 is appropriate with standardized error).

**Acceptance criteria**:
- Every `/api/<symbol>` response includes `data_completeness` object with boolean flags for each data category
- `/api/market` response includes `data_completeness`
- `/api/price/<symbol>` includes `stale` flag correctly (true when from price_1d fallback)
- `/api/options-intelligence` returns `"DATA UNAVAILABLE"` when no option chain data
- Test validates `data_completeness` presence on all 55 endpoints
- 194 tests still pass
- No model layer files modified

**Test plan**:
- `test_data_completeness_on_symbol_endpoint`: Call `/api/NIFTY`, verify `data_completeness` present with all expected keys
- `test_data_completeness_on_market`: Call `/api/market`, verify `data_completeness` present
- `test_stale_flag_on_fallback`: When only price_1d data exists, verify `stale: True`
- `test_options_intelligence_quality_unavailable`: When no option_chain data, verify `data_quality: "DATA UNAVAILABLE"`
- `test_data_completeness_all_endpoints`: Iterate all 55 endpoints, verify `data_completeness` or `stale` present where applicable

**Affected files**:
- `backend/api_server.py` — `_symbol_data`, `_build_market`, `latest_price`, `prices`, `options_intelligence`
- `tests/test_phase6b_1.py` — New tests

---

## Part B: External Data-Source Resilience

---

### B.1 Circuit Breaker for External APIs [HIGH]

**Audit reference**: Dimension 6, Finding 6.1
**Effort**: L (per audit; M in practice due to integration)
**Affects model layer**: No

**Current state**: `backend/api_server.py:1195-1228` — `/api/global` calls `yf.download()` directly. `backend/data_fetcher_db.py:62-90` — `fetch_yf_ohlcv` catches exceptions but has no retry, no circuit breaker, no fallback. External sources: yfinance, NSE (nse_source.py, nse_live_chain.py), NSE official (bhavcopy.py), EOD (fo_fetcher.py).

**Specification**:

1. **Create `backend/circuit_breaker.py`** — Lightweight circuit breaker:
   ```python
   import time
   from threading import Lock

   class CircuitBreaker:
       def __init__(self, name, failure_threshold=5, recovery_timeout=60):
           self.name = name
           self.failure_threshold = failure_threshold
           self.recovery_timeout = recovery_timeout
           self._failures = 0
           self._last_failure_time = None
           self._state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN
           self._lock = Lock()

       def call(self, func, *args, **kwargs):
           with self._lock:
               if self._state == "OPEN":
                   if time.time() - self._last_failure_time > self.recovery_timeout:
                       self._state = "HALF_OPEN"
                   else:
                       raise CircuitOpenError(f"Circuit breaker OPEN for {self.name}")

           try:
               result = func(*args, **kwargs)
               with self._lock:
                   self._reset()
               return result
           except Exception as e:
               with self._lock:
                   self._failures += 1
                   self._last_failure_time = time.time()
                   if self._failures >= self.failure_threshold:
                       self._state = "OPEN"
               raise

       def _reset(self):
           self._failures = 0
           self._state = "CLOSED"
           self._last_failure_time = None

       @property
       def state(self):
           with self._lock:
               if self._state == "OPEN" and time.time() - self._last_failure_time > self.recovery_timeout:
                   self._state = "HALF_OPEN"
               return self._state
   ```

2. **Create global breaker instances** in `backend/api_server.py`:
   ```python
   from backend.circuit_breaker import CircuitBreaker

   BREAKERS = {
       "yfinance": CircuitBreaker("yfinance", failure_threshold=5, recovery_timeout=60),
       "nse": CircuitBreaker("nse", failure_threshold=3, recovery_timeout=120),
       "bhavcopy": CircuitBreaker("bhavcopy", failure_threshold=3, recovery_timeout=300),
   }
   ```

3. **Wrap external API calls**:
   - `/api/global` `yf.download()` → wrap with `BREAKERS["yfinance"].call()`
   - `fetch_yf_ohlcv` → wrap with breaker
   - NSE calls → wrap with `BREAKERS["nse"].call()`
   - Bhavcopy calls → wrap with `BREAKERS["bhavcopy"].call()`

4. **Graceful degradation**: When circuit is OPEN, return cached/stale data with warning instead of failing:
   ```python
   try:
       data = BREAKERS["yfinance"].call(fetch_func, *args)
   except CircuitOpenError:
       data = _get_cached_data(symbol)  # last known good from DB
       _warning = f"{breaker.name} circuit OPEN — serving cached data"
   ```

**Acceptance criteria**:
- Circuit breaker wraps all 4 external API sources (yfinance, NSE, bhavcopy, EOD)
- After 5 consecutive yfinance failures, circuit opens and subsequent calls return cached data (not error)
- After 60s recovery timeout, circuit enters HALF_OPEN, next call tests recovery
- Test simulates yfinance failure: 6 consecutive failures → circuit opens → 7th call returns cached data
- 194 tests still pass
- No model layer files modified

**Test plan**:
- `test_circuit_breaker_opens_after_threshold`: Call breaker 5 times with failing function, 6th call raises CircuitOpenError
- `test_circuit_breaker_half_open_after_timeout`: After recovery timeout, next call goes through (HALF_OPEN)
- `test_circuit_breaker_resets_on_success`: Successful call resets failure count
- `test_yfinance_circuit_serves_cached_data`: When yfinance circuit is OPEN, `/api/global` returns last cached data with warning flag

**Affected files**:
- `backend/circuit_breaker.py` — NEW file
- `backend/api_server.py` — `/api/global`, import and use breakers
- `backend/data_fetcher_db.py` — `fetch_yf_ohlcv`, wrap with breaker
- `tests/test_phase6b_1.py` — New tests

---

### B.2 Retry with Exponential Backoff [HIGH]

**Audit reference**: Dimension 6, Finding 6.2
**Effort**: M
**Affects model layer**: No

**Current state**: `backend/data_fetcher_db.py:62-90` — `fetch_yf_ohlcv` catches exception once and returns `[]`. `backend/bhavcopy.py:45-52` — `_get` catches once, returns `None`. `backend/nse_fo.py`, `backend/fo_fetcher.py` — same pattern.

**Specification**:

1. **Create retry decorator** in `backend/retry.py` (or include in circuit_breaker.py):
   ```python
   import time
   import functools

   def retry_with_backoff(max_retries=3, base_delay=2.0, max_delay=30.0):
       def decorator(func):
           @functools.wraps(func)
           def wrapper(*args, **kwargs):
               last_exception = None
               for attempt in range(max_retries):
                   try:
                       return func(*args, **kwargs)
                   except Exception as e:
                       last_exception = e
                       if attempt < max_retries - 1:
                           delay = min(base_delay * (2 ** attempt), max_delay)
                           time.sleep(delay)
               raise last_exception
           return wrapper
       return decorator
   ```

2. **Apply to all external API functions**:
   ```python
   @retry_with_backoff(max_retries=3, base_delay=2.0)
   def fetch_yf_ohlcv(yf_symbol, interval="1m", period="2d"):
       # ... existing code ...

   @retry_with_backoff(max_retries=3, base_delay=2.0)
   def fetch_yf_info(yf_symbol):
       # ... existing code ...
   ```

3. **Integration with circuit breaker** (B.1): Circuit breaker wraps the retry. Order: retry first (handles transient), circuit breaker second (handles sustained outage).

**Acceptance criteria**:
- All external API functions retry 3 times with exponential backoff (2s, 4s, 8s)
- Test verifies retry on transient failure: function fails twice then succeeds → returns result
- Test verifies all retries exhausted: function fails 3 times → raises last exception
- 194 tests still pass
- No model layer files modified

**Test plan**:
- `test_retry_succeeds_after_transient_failure`: Mock function that fails 2x then succeeds, verify result returned
- `test_retry_exhausted_on_permanent_failure`: Mock function that fails 3x, verify raises after 3rd attempt with correct delay timing
- `test_retry_backoff_timing`: Verify delays are approximately 2s, 4s (not 2s, 2s)

**Affected files**:
- `backend/retry.py` — NEW file
- `backend/data_fetcher_db.py` — Apply decorator to fetch functions
- `backend/bhavcopy.py` — Apply decorator to `_get`
- `backend/nse_fo.py` — Apply decorator to fetch functions
- `backend/fo_fetcher.py` — Apply decorator to fetch functions
- `tests/test_phase6b_1.py` — New tests

---

## Part C: API Reliability Infrastructure

---

### C.1 Unified Error Response Schema [CRITICAL]

**Audit reference**: Dimension 1, Finding 1.1
**Effort**: M
**Affects model layer**: No

**Current state**: 55 routes return errors in inconsistent formats:
- `{"error": "no data"}` (404) — price, vix, indicators, regime, strategy, scenarios, outlook, breadth, snapshot, fundamentals
- `{"error": "use dedicated endpoint"}` (404) — generic symbol
- `{"error": f"unknown symbol {symbol}"}` (404) — generic symbol
- `{"error": f"no outlook yet for {symbol}"}` (404) — market-outlook
- `{"error": "symbol required"}` (400) — portfolio POST
- `{"ok": true}` (200) — portfolio POST/DELETE
- `{"status": "ok"/"degraded", ...}` — health
- `[]` or `{}` — empty list results
- `{}` — market data unavailable

**Specification**:

1. **Define standard error schema**:
   ```python
   def error_response(code, message, status_code=400):
       return jsonify({
           "error": {
               "code": code,
               "message": message,
               "timestamp": datetime.now(timezone.utc).isoformat(),
           }
       }), status_code
   ```

2. **Error code taxonomy** (add to api_server.py or config):
   ```python
   ERROR_CODES = {
       "NO_DATA": "The requested data is not available",
       "UNKNOWN_SYMBOL": "The requested symbol is not tracked",
       "SYMBOL_REQUIRED": "A symbol parameter is required",
       "OUTLOOK_NOT_READY": "Market outlook not yet computed for this date",
       "INVALID_REQUEST": "The request parameters are invalid",
       "RATE_LIMITED": "Too many requests, please wait",
       "INTERNAL_ERROR": "An internal error occurred",
       "DB_UNAVAILABLE": "Database is temporarily unavailable",
       "CIRCUIT_OPEN": "An upstream data source is temporarily unavailable",
   }
   ```

3. **Replace all error responses** across all 55 endpoints:
   - `{"error": "no data"}` → `error_response("NO_DATA", "...", 404)`
   - `{"error": "use dedicated endpoint"}` → `error_response("INVALID_REQUEST", "...", 404)`
   - `{"error": f"unknown symbol {symbol}"}` → `error_response("UNKNOWN_SYMBOL", f"Symbol {symbol} is not tracked", 404)`
   - `{"error": "symbol required"}` → `error_response("SYMBOL_REQUIRED", "A symbol parameter is required", 400)`
   - Portfolio POST/DELETE: change `{"ok": true}` to `{"ok": true, "status": "success"}` (200)

4. **Add error handler for 500**:
   ```python
   @app.errorhandler(500)
   def internal_error(e):
       return error_response("INTERNAL_ERROR", "An internal error occurred", 500)

   @app.errorhandler(404)
   def not_found(e):
       return error_response("NO_DATA", "The requested resource was not found", 404)
   ```

5. **Add `handle_error()` utility** — a helper that all endpoints can call:
   ```python
   def handle_error(e, context="", status_code=500):
       code = "INTERNAL_ERROR"
       message = "An error occurred"
       if isinstance(e, ValueError):
           code = "INVALID_REQUEST"
           message = str(e)
       elif isinstance(e, KeyError):
           code = "NO_DATA"
           message = "Required data not found"
       app.logger.warning(f"Error in {context}: {e}")
       return error_response(code, message, status_code)
   ```

**Acceptance criteria**:
- ALL 55 endpoints return errors in identical `{"error": {"code": "...", "message": "...", "timestamp": "..."}}` schema
- Automated test validates error shape for each endpoint (call each endpoint with bad input, verify schema)
- 194 tests still pass
- No model layer files modified

**Test plan**:
- `test_all_endpoints_return_standard_error_schema`: Iterate all 55 endpoints, call each with invalid parameters, verify error response matches schema
- `test_error_response_has_required_fields`: Verify `error.code`, `error.message`, `error.timestamp` present in every error response
- `test_portfolio_post_returns_ok_not_error`: Portfolio POST with valid data returns `{"ok": true, "status": "success"}` not error schema

**Affected files**:
- `backend/api_server.py` — All 55 endpoint error responses, error handlers, `error_response()`, `handle_error()`
- `tests/test_phase6b_1.py` — New tests

---

## Part D: Verification & Non-Regression

---

### D.1 Regression Gate

All specifications must pass the following before commit:

1. **194/194 existing tests pass**: `python3 -m pytest tests/ -v`
2. **New tests pass**: All tests added in this specification pass
3. **Model layer untouched**: `git diff 51c02f9 HEAD --name-only` shows NO changes to:
   - `backend/regime.py`
   - `backend/strategies.py`
   - `backend/outlook.py`
   - `backend/scenarios.py`
   - `backend/options.py`
   - `backend/ai_outlook.py`
   - `backend/backtest.py`
   - `backend/indicators.py`
4. **Boundary audit**: No change to signal confidence formula, strategy selection, scenario normalization, or any analytical computation
5. **PHASE 6A tests still pass**: `tests/test_phase6a.py` — all 10 tests pass (Signal Confidence label, WAIT messaging, health endpoint)

### D.2 Scope Boundary

**Authorized for 6B-1**:
- `backend/db_schema.py` — WAL + busy_timeout
- `backend/api_server.py` — timeout, try/finally, error schema, data_completeness, circuit breaker integration
- `backend/database.py` — try/finally for all connection methods
- `backend/data_fetcher_db.py` — timeout, circuit breaker, retry integration
- `backend/circuit_breaker.py` — NEW
- `backend/retry.py` — NEW
- `config/` — If new config needed (none expected for 6B-1)
- `tests/` — New tests for 6B-1 specifications
- `PHASE6B_STEP1_SPECIFICATION.md` — This document

**Explicitly NOT authorized for 6B-1**:
- Any model layer file (see D.1.3)
- Rate limiting (Dimension 2 — Stage 6B-2)
- Monitoring/alerting (Dimension 3 — Stage 6B-3)
- CI/CD (Dimension 4 — Stage 6B-4)
- Security/auth (Dimension 8 — Stage 6B-5)
- Authentication (Dimension 2.3, 8.1 — deferred)
- Deployment (Dimension 11 — Stage 6B-6)

---

## Part E: Implementation Sequence

Within 6B-1, implement in this order to minimize risk:

| Order | Item | Finding | Effort | Dependencies |
|---|---|---|---|---|
| 1 | SQLite WAL + busy_timeout | A.1 | S | None |
| 2 | DB connection timeout | A.2 | S | A.1 (WAL makes timeout more effective) |
| 3 | Connection leak prevention | A.3 | M | A.1, A.2 |
| 4 | Unified error schema | C.1 | M | None |
| 5 | Partial-data policy | A.4 | M | None |
| 6 | Circuit breaker | B.1 | L | A.2 (timeout needed for circuit to work) |
| 7 | Retry with backoff | B.2 | M | B.1 (circ breaker wraps retry) |
| 8 | Regression test | D.1 | — | All above |

---

## Part F: Post-Implementation Verification Audit

After implementation, conduct a follow-up audit:

1. **Re-run PHASE 6B audit** — confirm all 61 findings still tracked (this spec addresses 7 of them)
2. **Run 194/194 regression** — no regressions
3. **Run new 6B-1 tests** — all pass
4. **Verify model layer untouched** — `git diff 51c02f9 HEAD` only touches authorized files
5. **Commit and freeze** — 6B-1 commit, then freeze before proceeding to 6B-2

---

## Part G: Acceptance Summary

| # | Finding | Severity | Addressed | Testable |
|---|---|---|---|---|
| A.1 | SQLite WAL mode | Critical | Yes | Yes — WAL pragma + concurrent test |
| A.2 | DB connection timeout | High | Yes | Yes — timeout parameter + hang test |
| A.3 | Connection leaks | High | Yes | Yes — error-storm connection count |
| A.4 | Partial-data policy | Medium | Yes | Yes — data_completeness on all endpoints |
| B.1 | Circuit breaker | High | Yes | Yes — failure simulation + cached fallback |
| B.2 | Retry with backoff | High | Yes | Yes — mock failures + timing test |
| C.1 | Unified error schema | Critical | Yes | Yes — error schema test on all 55 endpoints |

**7 of 7 target findings addressed. 0 model layer changes. 194/194 regression required.**

---

*End of PHASE 6B-1 Specification. Awaiting user independent review before implementation.*
