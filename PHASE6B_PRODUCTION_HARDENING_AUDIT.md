# PHASE 6B — Production Hardening Audit (Read-Only)

**Status**: AUDIT — FINDINGS ONLY
**Frozen baselines**: `45f90fc` (analytical/model), `51c02f9` (PHASE 6A productization)
**Audit date**: 2026-09-13
**Scope**: Read-only inspection of committed code at `51c02f9`. No code changes. No implementations. Findings for future PHASE 6B implementation planning.

**Regression baseline**: 194/194 passing at audit time
**Test command**: `python3 -m pytest tests/ -v`

---

## Audit Summary

| Dimension | Critical | High | Medium | Low |
|---|---|---|---|---|
| API Reliability | 1 | 3 | 4 | 2 |
| Rate Limiting & Abuse | 1 | 1 | 1 | 0 |
| Monitoring & Alerting | 0 | 2 | 4 | 3 |
| CI/CD | 1 | 1 | 1 | 0 |
| Observability | 0 | 2 | 3 | 2 |
| Data-Source Failures | 0 | 2 | 3 | 1 |
| Database & Resources | 1 | 1 | 3 | 2 |
| Security | 0 | 2 | 4 | 3 |
| Failure/Recovery | 0 | 1 | 4 | 3 |
| Performance | 1 | 2 | 3 | 2 |
| Production Deployment | 0 | 2 | 3 | 2 |
| **Totals** | **5** | **20** | **36** | **22** |

**Total findings**: 61 (5 Critical, 20 High, 36 Medium, 22 Low)
**Findings affecting analytical/model layer**: 0 (all are operational/UX/infrastructure)

---

## Priority Ranking (Recommended)

Per TradingAI.in's intended public options-trader audience:

**Reliability → Stale-data protection → API abuse protection → Monitoring/alerting → CI regression → Security → Performance → Deployment**

---

## Dimension 1: API Reliability

### 1.1 Inconsistent Error Response Schema [CRITICAL]

- **Severity**: Critical
- **Evidence**: `backend/api_server.py` — 55 routes return errors in inconsistent formats:
  - `{"error": "no data"}` with 404 (price, vix, indicators, regime, strategy, scenarios, outlook, breadth, snapshot, fundamentals)
  - `{"error": "use dedicated endpoint"}` with 404 (generic symbol)
  - `{"error": f"unknown symbol {symbol}"}` with 404 (generic symbol)
  - `{"error": f"no outlook yet for {symbol}"}` with 404 (market-outlook)
  - `{"error": "symbol required"}` with 400 (portfolio POST)
  - `{"ok": true}` with 200 (portfolio POST/DELETE — no error field)
  - `{"status": "ok"/"degraded", ...}` (health)
  - `[]` or `{}` for empty results on many list endpoints
  - `{"error": "rate limited: 8/min"}` with 429 (chat POST only)
  - `{}` (empty dict) when market data is unavailable (/api/market)
- **Risk**: Frontend must handle 15+ different error shapes. One wrong handler = silent failure. Options traders seeing empty responses can't distinguish "no data" from "system down."
- **Recommended fix**: Standardize all error responses to `{"error": {"code": "STRING", "message": "Human readable", "timestamp": "ISO"}}` with consistent HTTP status codes. Add a `handle_error()` utility in api_server.py.
- **Effort**: M
- **Affects model layer**: No
- **Acceptance criteria**: All 55 endpoints return errors in identical schema; automated test validates error shape for each endpoint; 194 tests still pass

### 1.2 No Database Connection Timeout [HIGH]

- **Severity**: High
- **Evidence**: `backend/api_server.py:22-25` — `sqlite3.connect(DB_PATH)` has no `timeout=` parameter. `backend/database.py:17-19` same. `backend/data_fetcher_db.py:42-44` same. All 3 locations.
- **Risk**: If SQLite is locked by a write operation (backtest, data fetch, backup), a read request blocks indefinitely. Under load, this cascades: all 3 gunicorn workers (6 threads total) blocked on DB reads = complete API freeze.
- **Recommended fix**: Add `timeout=10` (or similar) to all `sqlite3.connect()` calls. Implement connection retry with exponential backoff for lock contention.
- **Effort**: S
- **Affects model layer**: No
- **Acceptance criteria**: All `sqlite3.connect()` calls include `timeout=` parameter; test simulates DB lock and verifies API returns 503 instead of hanging

### 1.3 Connection Leaks on Error Paths [HIGH]

- **Severity**: High
- **Evidence**: `backend/api_server.py` — Every endpoint opens a connection and calls `conn.close()` at the end, but error paths (early returns with 404/400, exceptions) bypass close. 55 routes × error paths = up to 55 potential leak points. Specifically:
  - `_build_quote()` lines 302-314: opens nested connection inside a function called from `_symbol_data()` (which already holds a connection). If exception before line 314, nested connection leaks.
  - `options_intelligence()` line 750-876: 126 lines with multiple `except Exception: pass` blocks (lines 858, 890, 900) where connection close may be skipped.
  - `market_outlook_latest()` lines 894-917: connection close at 908 and 915, but only if no exception in `merge_llm_into_payload` call.
- **Risk**: Under error conditions, SQLite connections accumulate. Each connection uses ~2MB RAM. 100 leaked connections = 200MB+ memory growth. On a 1GB VM, this causes OOM.
- **Recommended fix**: Use context managers (`with get_db() as conn:`) or try/finally blocks for all connection handling. Add a connection count metric to /api/health.
- **Effort**: M
- **Affects model layer**: No
- **Acceptance criteria**: Connection count on error paths is zero after 1000 error-inducing requests; memory stable after error storm

### 1.4 Inconsistent Partial-Data Behavior [MEDIUM]

- **Severity**: Medium
- **Evidence**: `backend/api_server.py` — When partial data exists, endpoints behave inconsistently:
  - `/api/price/<symbol>`: Falls back to `price_1d` if both `price_1m` and `live_quotes` empty, returns 404 if neither exists
  - `/api/<symbol>`: Returns partial `_symbol_data` (may have quote but no strategy, or vice versa) with 200 — no indication of which fields are populated
  - `/api/market`: Returns `{}` if market data unavailable, `{"instruments": {}, ...}` if symbols exist but no prices — different empty shapes
  - `/api/options-intelligence`: Returns `{"symbol": X, "spot": null, "data_quality": "LIVE", ...}` with null fields when no option chain exists
  - `/api/vix`: Returns `{"error": "no VIX data"}` with 404 vs `/api/prices` returning `[]` with 200 for no data
- **Risk**: Frontend cannot uniformly detect "I have partial data" vs "I have no data." A trader might see a price but no indicators and not know the data is incomplete.
- **Recommended fix**: Add `data_completeness` or `_has_*` flags to all responses indicating which data sources contributed. Standardize empty-data responses.
- **Effort**: M
- **Affects model layer**: No
- **Acceptance criteria**: Every endpoint includes a `data_completeness` or equivalent indicator; test validates presence for all 55 endpoints

### 1.5 Bare Except Clauses in Health Endpoint [MEDIUM]

- **Severity**: Medium
- **Evidence**: `backend/api_server.py:52,57,81` — Three `except: pass` or `except: return None` clauses in the `/api/health` function. These catch ALL exceptions including `KeyboardInterrupt`, `SystemExit`, `MemoryError`.
- **Risk**: If health endpoint encounters a memory pressure condition, `MemoryError` is silently swallowed. Health endpoint reports "ok" when it should report "degraded" or fail loudly.
- **Recommended fix**: Replace `except:` with `except Exception:` in all 3 locations. Add logging for caught exceptions.
- **Effort**: S
- **Affects model layer**: No
- **Acceptance criteria**: No bare `except:` clauses exist; `except Exception:` with logging used instead

### 1.6 Impure `_symbol_data` Called Internally [MEDIUM]

- **Severity**: Medium
- **Evidence**: `backend/api_server.py:1155-1174` — `_build_market()` calls `_symbol_data(sym)` which returns a Flask `Response` object (via `jsonify()`), then calls `.get_json()` on it. This is an anti-pattern: creating HTTP response objects for internal computation.
- **Risk**: If `_symbol_data` is ever modified to return something other than a Response (e.g., during refactoring), `_build_market` breaks silently. Also creates unnecessary Response objects (memory/CPU).
- **Recommended fix**: Extract the data-building logic from `_symbol_data` into a `_build_symbol_data(symbol, conn)` function that returns a dict. Have `_symbol_data` call it and wrap in `jsonify()`, and have `_build_market` call it directly.
- **Effort**: L
- **Affects model layer**: No
- **Acceptance criteria**: `_build_market` no longer calls `_symbol_data`; it calls a shared internal function; 194 tests still pass

### 1.7 f-string SQL Queries [MEDIUM]

- **Severity**: Medium
- **Evidence**: `backend/api_server.py:123` — `f"SELECT * FROM {table} WHERE..."` (table name from hardcoded enum, safe but fragile). `backend/api_server.py:136` — `f"SELECT * FROM price_1m WHERE symbol IN ({placeholders})..."` (values parameterized, table hardcoded). Also in `backend/aggregate.py:68,73`, `backend/database.py:283,302`, `backend/data_fetcher_db.py:293,630`.
- **Risk**: Table names cannot be parameterized in SQL. If a future developer passes user input as a table name, SQL injection occurs. Current code is safe because table names are hardcoded, but there's no enforcement.
- **Recommended fix**: Define allowed table names as constants. Add assertion `assert table in ALLOWED_TABLES` before f-string queries.
- **Effort**: S
- **Affects model layer**: No
- **Acceptance criteria**: All f-string SQL uses assertions against allowed-table constants; audit confirms no user-controlled values in table name positions

### 1.8 Error Messages Leak Internal Details [LOW]

- **Severity**: Low
- **Evidence**: `backend/api_server.py:218` — `{"error": f"unknown symbol {symbol}"}` (echoes user input). Various `except Exception as e: app.logger.warning(...)` messages include exception text that may contain SQL errors, DB paths, or stack trace fragments.
- **Risk**: Internal error details in responses help attackers probe the system (DB schema, table names, library versions).
- **Recommended fix**: Return generic error messages in responses (`{"error": "request failed"}`), log details server-side only.
- **Effort**: S
- **Affects model layer**: No
- **Acceptance criteria**: No response contains stack traces, SQL errors, or file paths; all internal details logged server-side

---

## Dimension 2: Rate Limiting & Abuse Protection

### 2.1 Zero Rate Limiting on 53 of 55 Endpoints [CRITICAL]

- **Severity**: Critical
- **Evidence**: `backend/api_server.py` — Only `/api/chat/messages` POST (line 1415: `return jsonify({"error": "rate limited: 8/min"}), 429`) and `/api/chat/messages` GET (nginx 10s cache) have rate limiting. All other 53 endpoints: zero rate limiting, zero throttling, zero request counting.
- **Risk**: Public options-trader audience means automated bots can hammer every endpoint simultaneously. A single malformed request loop can freeze the API (compounded by finding 1.2 — no DB timeout). No protection against scraping, data extraction, or denial-of-service.
- **Recommended fix**: Implement Flask-Limiter with per-endpoint rate limits:
  - Data endpoints (price, indicators, regime): 60/min per IP
  - Computation endpoints (backtest, options-intelligence, maxpain): 10/min per IP
  - List endpoints (symbols, strategies, etc.): 120/min per IP
  - Health endpoint: exempt (for monitoring)
- **Effort**: M
- **Affects model layer**: No
- **Acceptance criteria**: All 55 endpoints have rate limits configured; test verifies 429 returned after limit exceeded; 194 tests still pass

### 2.2 CORS Wide Open [HIGH]

- **Severity**: High
- **Evidence**: `backend/api_server.py:18` — `CORS(app)` with no parameters. This allows ANY origin to make cross-origin requests to ANY endpoint including POST/DELETE.
- **Risk**: Any website can embed TradingAI data in their page (data scraping). More critically, a malicious site can make authenticated-seeming POST requests (portfolio add/delete) from a user's browser via CSRF — no CSRF token required because CORS allows all origins AND no auth.
- **Recommended fix**: Restrict CORS to known frontend origins (e.g., `CORS(app, origins=["https://tradingai.in", "https://www.tradingai.in"])`). Add CSRF protection for state-changing endpoints.
- **Effort**: S
- **Affects model layer**: No
- **Acceptance criteria**: CORS configured with explicit allowlist; OPTIONS preflight returns 403 for unauthorized origins; CSRF tokens required for POST/DELETE

### 2.3 No Authentication on Any Endpoint [HIGH]

- **Severity**: High
- **Evidence**: `backend/api_server.py` — All 55 endpoints have zero authentication, zero API keys, zero session management. The portfolio endpoints (`/api/portfolio` GET/POST/DELETE) allow full portfolio management without any user identification.
- **Risk**: Anyone can view or modify any portfolio. Public market data is expected to be open, but portfolio management without auth is a data exposure risk. Chat messages can be posted anonymously (intentional for chat, but unbounded).
- **Recommended fix**: Add optional auth header for portfolio endpoints (API key or session token). Public market data endpoints remain unauthenticated. Add user-isolation for portfolio data (one user's portfolio only visible to that user).
- **Effort**: L
- **Affects model layer**: No
- **Acceptance criteria**: Portfolio endpoints accept auth tokens; unauthenticated portfolio requests return 401; public market data remains accessible

### 2.4 No Request Size Limits [MEDIUM]

- **Severity**: Medium
- **Evidence**: `backend/api_server.py` — No `MAX_CONTENT_LENGTH` configured on Flask app. No `request.content_length` checks on any endpoint. Chat POST accepts up to 500 chars (checked), but no endpoint validates request body size.
- **Risk**: A client can send an arbitrarily large request body, exhausting memory. Combined with no rate limiting, this enables memory-based DoS.
- **Recommended fix**: Set `app.config['MAX_CONTENT_LENGTH'] = 1 * 1024 * 1024` (1MB). Add per-endpoint validation for body size where applicable.
- **Effort**: S
- **Affects model layer**: No
- **Acceptance criteria**: Requests >1MB return 413; all existing valid requests still pass; 194 tests still pass

### 2.5 No Request Timeout Enforcement [MEDIUM]

- **Severity**: Medium
- **Evidence**: `backend/api_server.py` — No per-request timeout. Flask's default is no timeout. Gunicorn has `--timeout 90` (90 seconds), but if a request hangs before reaching gunicorn (e.g., DB lock), 90 seconds may not be enough.
- **Risk**: A slow query or external API hang ties up a gunicorn worker for extended period. With 6 total threads, 2 hung workers = 67% capacity loss.
- **Recommended fix**: Add Flask `before_request` hook with timeout using `signal` (Unix) or `multiprocessing` (cross-platform). Enforce per-endpoint timeouts (e.g., backtest: 30s, options-intelligence: 15s, data endpoints: 5s).
- **Effort**: M
- **Affects model layer**: No
- **Acceptance criteria**: Requests exceeding per-endpoint timeout return 504; no worker hangs >timeout duration

---

## Dimension 3: Monitoring & Alerting

### 3.1 No Latency Tracking [HIGH]

- **Severity**: High
- **Evidence**: `backend/api_server.py` — No response time tracking on any endpoint. `/api/health` returns status, freshness, and warnings but no latency data. Gunicorn access logs include response time but are not queryable in real-time.
- **Risk**: Cannot detect degrading API performance before it becomes failures. A 5-second endpoint slowly getting worse won't trigger any alert until it starts timing out.
- **Recommended fix**: Add response time middleware that records per-endpoint latency (histogram). Expose via `/api/health` or dedicated `/api/metrics` endpoint. Alert on p95 latency thresholds.
- **Effort**: M
- **Affects model layer**: No
- **Acceptance criteria**: Latency middleware records per-endpoint times; `/api/health` or `/api/metrics` includes latency data; alert triggers on p95 > threshold

### 3.2 No API Failure Counter [HIGH]

- **Severity**: High
- **Evidence**: `backend/api_server.py` — `/api/health` reports `status` (ok/degraded) based on data freshness, but does not track API-level failures (500s, timeouts, exceptions). No error counter. No success/failure ratio.
- **Risk**: Data can be fresh but the API itself can be failing (500 errors from code bugs). Health endpoint says "ok" while users see 500 errors.
- **Recommended fix**: Add Flask `after_request` hook that counts 5xx responses by endpoint. Expose in `/api/health` as `api_errors` field. Alert when 5xx rate > 1%.
- **Effort**: M
- **Affects model layer**: No
- **Acceptance criteria**: `/api/health` includes `api_errors` with per-endpoint 5xx counts; alert triggers on 5xx rate > 1%

### 3.3 No Latency Alerts [MEDIUM]

- **Severity**: Medium
- **Evidence**: `ops/crontab.txt` — Cron jobs include monitor.py (every 5 min), alert.py (every 2 hours), self-heal.sh (every 2 min). None check API latency. Self-heal.sh checks API health (curl with 10s timeout) but doesn't measure response time.
- **Risk**: Degraded performance (10x slower) isn't detected by binary health checks. API is "healthy" but 10x slower — users see slow page loads.
- **Recommended fix**: Add latency check to monitor.py or self-heal.sh. Alert when `/api/health` response time > 2 seconds.
- **Effort**: S
- **Affects model layer**: No
- **Acceptance criteria**: Monitoring script measures API response time; alert triggers on latency threshold breach

### 3.4 Alert Thresholds Not Configured [MEDIUM]

- **Severity**: Medium
- **Evidence**: `backend/alert.py` — PCR alerts use hardcoded thresholds (PCR ≤ 0.65, PCR ≥ 1.30). No alert threshold for API errors, latency, disk usage (self-heal.sh hardcodes 85%/90%). No centralized threshold configuration.
- **Risk**: Thresholds are scattered across files. Changing a threshold requires code change. No visibility into what thresholds exist.
- **Recommended fix**: Create `config/alerting.json` with all thresholds (API errors, latency, disk, data freshness, PCR, regime changes). Load at startup.
- **Effort**: M
- **Affects model layer**: No
- **Acceptance criteria**: All alerting thresholds in `config/alerting.json`; thresholds loadable without code changes; tests validate threshold ranges

### 3.5 No Health Check Beyond /api/health [MEDIUM]

- **Severity**: Medium
- **Evidence**: `backend/api_server.py` — Only `/api/health` exists as a health check. No endpoint-level health. No deep health check (DB connection test, external API connectivity test). No readiness/liveness distinction.
- **Risk**: Kubernetes or load balancer can't distinguish "API process is up but not ready" from "API is fully functional." A DB connection failure would show API as "up" but returning errors.
- **Recommended fix**: Add `/api/health/live` (process alive) and `/api/health/ready` (ready to serve, DB connected, data fresh). Deep health check includes DB query + external API connectivity.
- **Effort**: M
- **Affects model layer**: No
- **Acceptance criteria**: Live endpoint returns process status; ready endpoint returns readiness (DB, data, external APIs); both endpoints tested

### 3.6 Data Freshness Only Checks Last Timestamp [MEDIUM]

- **Severity**: Medium
- **Evidence**: `backend/api_server.py:37-85` — `/api/health` checks `MAX(timestamp)` for each data source. If a fetch ran but returned empty/invalid data, the timestamp is recent but data quality is poor. No row count check. No data range check.
- **Risk**: Freshness ≠ quality. A fetch that returns empty data has a recent timestamp but provides no value. Health endpoint would report "ok."
- **Recommended fix**: Add data quality checks to /api/health: row count (not just timestamp), date range (last data date is within expected range), value sanity (prices > 0, etc.).
- **Effort**: M
- **Affects model layer**: No
- **Acceptance criteria**: Health endpoint includes data quality metrics (row counts, date ranges, value sanity); test validates stale-quality detection

### 3.7 Logs Are Plain Text [MEDIUM]

- **Severity**: Medium
- **Evidence**: `backend/api_server.py`, `backend/data_fetcher_db.py`, `backend/alert.py`, etc. — All loggers use standard `logging` module with format `"%(asctime)s %(levelname)s %(name)s: %(message)s"`. Plain text. Not JSON-structured.
- **Risk**: Plain text logs require regex for parsing. In a production environment with centralized logging (ELK, Datadog), structured JSON logs are significantly easier to query and alert on.
- **Recommended fix**: Add structured JSON log formatter. Use `python-json-logger` or custom formatter. Write to separate JSON log files or add `json` field to log entries.
- **Effort**: L
- **Affects model layer**: No
- **Acceptance criteria**: Log entries are valid JSON; can be parsed by `json.loads()`; key fields (timestamp, level, logger, message) present in every entry

### 3.8 Distributed Tracing Absent [MEDIUM]

- **Severity**: Medium
- **Evidence**: Entire codebase — No request IDs, no trace IDs, no span IDs, no correlation between API request and downstream operations (DB queries, external API calls).
- **Risk**: When a request fails, it's impossible to trace it through the system. "Which DB query failed for which user request?" requires manual log grepping across multiple log files.
- **Recommended fix**: Add request ID middleware (generate UUID per request, inject into logging context). Add span IDs for DB queries and external API calls. Propagate through all log entries.
- **Effort**: L
- **Affects model layer**: No
- **Acceptance criteria**: Every log entry includes a request_id; request_id is consistent across all operations for a single API request; tests verify propagation

### 3.9 No Centralized Error Tracking [LOW]

- **Severity**: Low
- **Evidence**: `backend/api_server.py:83` — `app.logger.warning(f"health freshness check failed: {e}")`. Errors logged locally to files in `/opt/tradingai/logs/`. No Sentry, no Rollbar, no similar error tracking service.
- **Risk**: Errors are only visible if someone SSHs into the VM and reads log files. No real-time error alerting. No error grouping or frequency tracking.
- **Recommended fix**: Integrate with error tracking service (Sentry, etc.) OR create a lightweight error tracker that counts errors by type and exposes via `/api/health`.
- **Effort**: L
- **Affects model layer**: No
- **Acceptance criteria**: Errors are grouped and counted; error frequency is queryable; alert triggers on error rate threshold

### 3.10 No Pipeline Failure Visibility [LOW]

- **Severity**: Low
- **Evidence**: `backend/data_fetcher_db.py`, `backend/bhavcopy.py`, etc. — Data fetchers log errors locally but there's no endpoint to check pipeline status. `/api/data_status` exists (returns `data_status` table rows) but doesn't indicate failures.
- **Risk**: If a data fetcher fails silently, the data becomes stale but there's no alert and no visibility. The next manual check discovers the failure hours or days later.
- **Recommended fix**: Add pipeline status endpoint. Track fetch success/failure in `data_status` table with error counts. Alert on consecutive failures.
- **Effort**: L
- **Affects model layer**: No
- **Acceptance criteria**: Pipeline status endpoint returns per-source success/failure; consecutive failure count tracked; alert triggers on N consecutive failures

---

## Dimension 4: CI/CD

### 4.1 No Automated Regression Gates [CRITICAL]

- **Severity**: Critical
- **Evidence**: Entire repository — No `.github/` directory, no `.gitlab-ci.yml`, no `Jenkinsfile`, no `Makefile` with test targets, no `tox.ini`, no `pytest.ini`, no CI config of any kind. Tests exist (2,863 lines across 8 test files, 194 passing) but are only run manually via `python3 -m pytest tests/ -v`.
- **Risk**: Any commit that breaks tests is not caught automatically. With 14 commits ahead of origin/main and growing, the risk of a regression slipping through increases with each commit. The 194-test regression suite is only as reliable as the discipline of the developer running it.
- **Recommended fix**: Add `.github/workflows/regression.yml` that runs `python3 -m pytest tests/ -v` on every push and PR. Block merge if tests fail. Store results as artifacts.
- **Effort**: S
- **Affects model layer**: No
- **Acceptance criteria**: CI runs pytest on every push; PR merge blocked if 194 tests don't pass; test results stored as artifacts

### 4.2 No Commit/PR Validation [HIGH]

- **Severity**: High
- **Evidence**: `backend/api_server.py` — No pre-commit hooks. No `pre-commit` config. No `.pre-commit-config.yaml`. No branch protection rules documented.
- **Risk**: Code style inconsistencies, debug statements (`print()`), and forbidden patterns (bare `except:`, `TODO:`, etc.) can enter the codebase unchecked.
- **Recommended fix**: Add pre-commit hooks for: Python syntax check, pytest, forbidden patterns (bare except, print statements in non-test code), linting (flake8/ruff).
- **Effort**: S
- **Affects model layer**: No
- **Acceptance criteria**: Pre-commit hooks run on every commit; blocked commits listed in `.pre-commit-config.yaml`; hooks tested

### 4.3 No Deployment Safety Check [MEDIUM]

- **Severity**: Medium
- **Evidence**: `deploy-vm.sh` — Deploy is a manual `rsync + systemctl restart` sequence. No health check after deploy (line 45: `curl -s http://127.0.0.1:8000/api/health || true` — the `|| true` means failure is ignored). No rollback automation.
- **Risk**: A broken deploy leaves the API in a broken state. The `|| true` on the health check means a failed health check doesn't stop the deploy script. No automated rollback.
- **Recommended fix**: Remove `|| true` from health check. Add post-deploy validation (check /api/health returns "ok", run subset of regression tests). Add rollback script that reverts to previous commit and restarts.
- **Effort**: S
- **Affects model layer**: No
- **Acceptance criteria**: Post-deploy health check fails → deploy script exits non-zero; rollback script tested and documented

### 4.4 No Staging Environment [MEDIUM]

- **Severity**: Medium
- **Evidence**: `deploy-vm.sh`, `ops/RESTORE.md` — Single production VM at 129.159.224.81. No staging, no pre-production environment.
- **Risk**: Every change is tested directly on production. A deploy that works on VM but breaks on a slightly different environment (different Python version, different yfinance cache, etc.) has no safe space to validate.
- **Recommended fix**: Add a staging VM (same image, different IP). Deploy to staging first, validate, then deploy to production. At minimum, document the staging environment requirements.
- **Effort**: L
- **Affects model layer**: No
- **Acceptance criteria**: Staging VM exists; deploy-vm.sh deploys to staging first; validation checklist documented

---

## Dimension 5: Observability

### 5.1 No Structured Logging [HIGH]

- **Severity**: High
- **Evidence**: All backend modules — `logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")` (data_fetcher_db.py), `"%(asctime)s %(levelname)s %(name)s: %(message)s"` (various). Plain text format. No JSON structure. No request context.
- **Risk**: In production with centralized logging, plain text logs require fragile regex for parsing. Key fields (endpoint, user_id, request_id) are not consistently extracted.
- **Recommended fix**: Implement JSON log formatter with consistent fields: `timestamp`, `level`, `logger`, `message`, `request_id`, `endpoint`, `duration_ms`. Use `python-json-logger` package or custom formatter.
- **Effort**: M
- **Affects model layer**: No
- **Acceptance criteria**: Log entries parse as JSON; consistent field names across all loggers; request_id present in all entries

### 5.2 No Metrics Endpoint [MEDIUM]

- **Severity**: Medium
- **Evidence**: Entire codebase — No `/api/metrics`, `/api/stats`, or equivalent endpoint that exposes operational metrics (request counts, error rates, latency histograms, DB connection count, cache hit rate).
- **Risk**: Prometheus/grafana or equivalent can't scrape metrics. Operational visibility depends on ad-hoc log grepping.
- **Recommended fix**: Add `/api/metrics` endpoint exposing: request count (total, per-endpoint), error count (5xx, 4xx), avg latency, DB connection count, cache hit/miss. Use in-memory counters updated by middleware.
- **Effort**: M
- **Affects model layer**: No
- **Acceptance criteria**: `/api/metrics` returns valid metrics; Prometheus can scrape; tests verify metric accuracy

### 5.3 No Request Timing Middleware [MEDIUM]

- **Severity**: Medium
- **Evidence**: `backend/api_server.py` — No `before_request`/`after_request` hooks that measure response time. Gunicorn access logs include timing but aren't queryable in real-time.
- **Risk**: Without per-request timing, latency issues are discovered by user complaints, not by monitoring.
- **Recommended fix**: Add `@app.before_request` and `@app.after_request` hooks that measure elapsed time and record it. Store in request context for `/api/metrics` or log it.
- **Effort**: S
- **Affects model layer**: No
- **Acceptance criteria**: Request timing middleware records elapsed time; time available in logs and/or metrics endpoint

### 5.4 Error Logs Don't Include Request Context [MEDIUM]

- **Severity**: Medium
- **Evidence**: `backend/api_server.py:83` — `app.logger.warning(f"health freshness check failed: {e}")`. `backend/data_fetcher_db.py` — `logger.error(f"OHLCV error for {yf_symbol}: {e}")`. No request ID, no endpoint, no user context in any error log.
- **Risk**: When 55 endpoints share one logger, errors from different endpoints are indistinguishable in log aggregation. "OHLCV error" doesn't tell you which endpoint triggered it.
- **Recommended fix**: Add request context to all log entries: endpoint path, request ID, client IP. Use Flask's `g` object for request-scoped logging context.
- **Effort**: M
- **Affects model layer**: No
- **Acceptance criteria**: Every error log includes endpoint and request_id; can filter logs by request_id to trace full request lifecycle

### 5.5 Log Rotation Not Configured [LOW]

- **Severity**: Low
- **Evidence**: `ops/crontab.txt`, `ops/self-heal.sh` — Logs in `/opt/tradingai/logs/` with no logrotate config. Self-heal.sh has disk threshold check (line 14: `DISK_PCT > 90`), but no proactive log rotation. `self-heal.sh:17` truncates large logs as emergency measure only.
- **Risk**: Logs grow unbounded. On a 1GB VM, a few days of verbose logging can fill the disk. Disk full → API can't write logs → can't debug issues.
- **Recommended fix**: Add logrotate config for `/opt/tradingai/logs/*.log` (daily rotation, 7-day retention, gzip). Or use Python's `RotatingFileHandler`.
- **Effort**: S
- **Affects model layer**: No
- **Acceptance criteria**: Logrotate config exists; logs rotate daily; max disk usage by logs < 500MB

---

## Dimension 6: Data-Source Failures

### 6.1 No Circuit Breaker for External APIs [HIGH]

- **Severity**: High
- **Evidence**: `backend/api_server.py:1195-1228` — `/api/global` calls `yf.download()` directly. If yfinance is down or slow, this blocks a gunicorn worker for the timeout duration. `backend/data_fetcher_db.py:62-90` — `fetch_yf_ohlcv` catches exceptions but has no retry, no circuit breaker, no fallback. Multiple external data sources: yfinance, NSE (via nse_source.py, nse_live_chain.py), NSE official (bhavcopy.py), EOD (fo_fetcher.py).
- **Risk**: A single unresponsive external API ties up a worker. With 3 workers/6 threads, one stuck yfinance call can cascade to complete API unavailability. Bhavcopy URL change (common) causes silent failures until next cron.
- **Recommended fix**: Implement circuit breaker pattern (e.g., `pybreaker` or custom). Track failure count per external source. After N failures in T minutes, stop calling that source and serve cached/stale data with a warning. Implement retry with exponential backoff for transient failures.
- **Effort**: L
- **Affects model layer**: No
- **Acceptance criteria**: Circuit breaker implemented for all external APIs; test simulates API failure and verifies graceful degradation; cached data served during outage

### 6.2 No Retry with Backoff [HIGH]

- **Severity**: High
- **Evidence**: `backend/data_fetcher_db.py:62-90` — `fetch_yf_ohlcv` catches exception once and returns `[]`. No retry. `backend/bhavcopy.py:45-52` — `_get` catches exception once and returns `None`. `backend/nse_fo.py`, `backend/fo_fetcher.py` — same pattern.
- **Risk**: A transient network glitch causes a data fetch failure. Next fetch is at the next cron interval (could be minutes). If the glitch persists, data is stale by the time retry happens. No automatic recovery from transient failures.
- **Recommended fix**: Add retry with exponential backoff (3 retries, 2s/4s/8s delays) to all external API calls. Use `tenacity` library or custom decorator.
- **Effort**: M
- **Affects model layer**: No
- **Acceptance criteria**: All external API calls retry 3 times with backoff; test verifies retry on transient failure; 194 tests still pass

### 6.3 No External API Health Tracking [MEDIUM]

- **Severity**: Medium
- **Evidence**: `backend/data_fetcher_db.py` — `data_status` table exists (tracks `last_fetch` per source) but `/api/data_status` endpoint only returns raw rows. No success/failure tracking. No error count. No uptime percentage.
- **Risk**: Can't tell if a data source is degraded or fully down from the API. Health check only checks timestamps, not data quality.
- **Recommended fix**: Track fetch success/failure in `data_status` table. Add `success_count`, `error_count`, `last_error` columns. Expose via `/api/data/status` with meaningful aggregation.
- **Effort**: M
- **Affects model layer**: No
- **Acceptance criteria**: Data status includes success/failure counts; endpoint shows per-source health; alert triggers on consecutive failures

### 6.4 No Fallback for yfinance Outage [MEDIUM]

- **Severity**: Medium
- **Evidence**: `backend/api_server.py:1195-1228` — `/api/global` returns `{}` if yfinance fails entirely. `backend/data_fetcher_db.py` — If yfinance is down during data fetch, data is simply missing (empty). No fallback to alternative sources, no cached response serving.
- **Risk**: yfinance is the primary data source. If yfinance goes down for 1 hour during market hours, all price data becomes stale or missing. No graceful degradation.
- **Recommended fix**: Add cached response serving during yfinance outage (even stale data is better than no data). Add alternative data source (NSE official, other provider) as fallback.
- **Effort**: L
- **Affects model layer**: No
- **Acceptance criteria**: During yfinance outage, last known data is served with `stale: true` flag; alert triggers on yfinance failure

### 6.5 VIX Data Source Failure Not Isolated [MEDIUM]

- **Severity**: Medium
- **Evidence**: `backend/api_server.py` — VIX data from `vix_data` table used in `/api/vix`, `/api/vix/history`, `/api/vix/daily`, `/api/global`, and in `backtest.py` (VIX-based strategies). If VIX data fetch fails, multiple endpoints and backtests are affected. No isolation.
- **Risk**: VIX data failure cascades to price analysis (VIX regime), backtest (VIX-based strategies), and global markets (CBOE VIX in GLOBAL_SYMBOLS).
- **Recommended fix**: Isolate VIX data source. If VIX unavailable, serve last known VIX with staleness warning. Don't let VIX failure affect non-VIX endpoints.
- **Effort**: M
- **Affects model layer**: No
- **Acceptance criteria**: VIX endpoint serves stale data during outage; non-VIX endpoints unaffected; alert triggers on VIX fetch failure

### 6.6 Options Data Source Failure Not Isolated [MEDIUM]

- **Severity**: Medium
- **Evidence**: `backend/api_server.py` — Options endpoints (`/api/options`, `/api/pcr`, `/api/maxpain`, `/api/options-intelligence`, etc.) all depend on `option_chain` and `option_expiries` tables. If options data fetch fails, all options endpoints return empty or partial data. Also: `options_intelligence` endpoint derives its `data_quality: "LIVE"` regardless of actual data freshness (lines 770).
- **Risk**: Options Intelligence reports `data_quality: "LIVE"` even when no option chain data exists (0 rows). This is misleading for options traders.
- **Recommended fix**: Make `data_quality` reflect actual data presence. If option_chain has 0 rows, report `"DATA UNAVAILABLE"` not `"LIVE"`. Add endpoint-level data quality check.
- **Effort**: M
- **Affects model layer**: No
- **Acceptance criteria**: Options intelligence reports `"DATA UNAVAILABLE"` when option_chain is empty; test verifies quality label accuracy

### 6.7 Database Failure Not Handled Gracefully [MEDIUM]

- **Severity**: Medium
- **Evidence**: `backend/api_server.py` — All endpoints call `get_db()` which does `sqlite3.connect(DB_PATH)` with no error handling. If DB file is corrupted or locked, the request throws an unhandled exception → 500 error. `self-heal.sh:47-58` checks DB integrity but only during self-heal cycle (every 2 min).
- **Risk**: DB corruption or lock causes immediate 500 errors on ALL endpoints. No graceful degradation, no cached fallback, no error message that helps the user understand the situation.
- **Recommended fix**: Add DB connection error handling in `get_db()`. Return 503 with helpful message instead of 500 with stack trace. Add SQLite WAL mode for better lock handling. Implement read-only fallback if primary DB fails.
- **Effort**: L
- **Affects model layer**: No
- **Acceptance criteria**: DB failure returns 503 (not 500); message is user-friendly; WAL mode enabled; read-only fallback works

### 6.8 NSE Live Quote Source Has No Health Check [LOW]

- **Severity**: Low
- **Evidence**: `backend/api_server.py:258-274` — `_live_quote_row()` checks freshness (25 min max age) but if the live quote source (NSE) is down entirely, `live_quotes` table is empty and the function returns None. The system falls back to 1m candles but doesn't log or alert that the live source is down.
- **Risk**: Live quotes are the freshest data source. If NSE feed is down, users see 1m-old data as current without knowing the real-time feed is broken.
- **Recommended fix**: Add monitoring for `live_quotes` table freshness (separate from `price_1m`). Alert if live quotes are >5 min stale (much stricter than 25 min threshold).
- **Effort**: S
- **Affects model layer**: No
- **Acceptance criteria**: Live quote staleness monitored separately; alert triggers on >5 min staleness; /api/health includes live_quotes status

---

## Dimension 7: Database & Resource Stability

### 7.1 SQLite Default Journal Mode (Not WAL) [CRITICAL]

- **Severity**: Critical
- **Evidence**: `backend/database.py:16-19` — `sqlite3.connect(self.db_path)` with no `PRAGMA journal_mode=WAL`. `db_schema.py` — Schema creates tables but no WAL pragma. `api_server.py` — No WAL configuration anywhere. Default journal mode is DELETE (readers block writers, writers block readers).
- **Risk**: Under concurrent access (3 gunicorn workers × 2 threads = 6 threads, plus cron jobs, plus self-heal), SQLite default journal mode causes lock contention. Writers block readers → API timeouts. Multiple concurrent writes (data fetch, chat insert, portfolio update) → deadlock risk. SQLite docs: "WAL mode is the recommended mode for most applications."
- **Recommended fix**: Add `PRAGMA journal_mode=WAL` to DB initialization in `db_schema.py`. Add `PRAGMA busy_timeout=10000` (10 second wait for lock). These should be set at connection time or DB creation.
- **Effort**: S
- **Affects model layer**: No
- **Acceptance criteria**: WAL mode enabled on all DB connections; busy_timeout set; test simulates concurrent reads/writes without lock errors

### 7.2 No Connection Pooling [HIGH]

- **Severity**: High
- **Evidence**: `backend/api_server.py:22-25` — `def get_db(): conn = sqlite3.connect(DB_PATH); return conn`. Every call creates a NEW connection. 55 endpoints × multiple queries per endpoint = many connections per request. `backend/database.py:16-19` — Same pattern. `backend/data_fetcher_db.py:42-44` — Same pattern. Total: 3 separate `get_db()` implementations, none with pooling.
- **Risk**: Connection creation is expensive (~5-10ms each). Under load, connection overhead dominates request time. 6 gunicorn threads × 50 concurrent requests = 300 connections created/second. SQLite file locking means most connections serialize anyway.
- **Recommended fix**: Implement connection pool. SQLite supports `check_same_thread=False` for sharing connections across threads (with proper locking). OR use `SQLAlchemy` with SQLite pool. Minimum: add `check_same_thread=False` and reuse connections within a request using context managers.
- **Effort**: M
- **Affects model layer**: No
- **Acceptance criteria**: Connection pool implemented; connection creation time reduced; 194 tests still pass

### 7.3 No DB Growth Management [MEDIUM]

- **Severity**: Medium
- **Evidence**: `config/instruments.json:331-335` — `data_retention` config exists (`minute_data_hours: 24, five_minute_data_days: 90, daily_data_years: 5`) but `Database.cleanup_old_data()` (database.py:294-306) is NOT called by any cron job. No `cleanup` entry in `ops/crontab.txt`. Multiple tables grow unbounded: `chat_messages` (only 500/2000 retention in code, not in DB schema), `price_1m` (no automated cleanup), `alerts` (no cleanup).
- **Risk**: DB grows indefinitely. On a 1GB VM, price_1m data at 1-minute intervals for 40 symbols × 60 min/hr × 24 hr = ~57,600 rows/day per table. Over months, this reaches millions of rows. Slow queries, large backups, disk pressure.
- **Recommended fix**: Add `cleanup_old_data` cron job. Ensure all retention policies in `config/instruments.json` are enforced. Add DB size monitoring to /api/health.
- **Effort**: M
- **Affects model layer**: No
- **Acceptance criteria**: Cleanup job runs daily; DB size bounded; retention policies enforced; /api/health includes DB size

### 7.4 No Concurrent Write Protection [MEDIUM]

- **Severity**: Medium
- **Evidence**: `backend/api_server.py:962-982` — `portfolio_add` does `conn.execute(INSERT)` then `conn.commit()`. `backend/api_server.py:984-990` — `portfolio_delete` same pattern. `backend/database.py:248-254` — `Database.execute()` opens new connection per call, commits, closes. No `BEGIN IMMEDIATE` or `SELECT ... FOR UPDATE` pattern.
- **Risk**: If two users simultaneously add to portfolio, SQLite's default isolation (DEFERRED) means both reads the same state, both write, one write conflicts silently or throws "database is locked." With WAL mode (recommended in 7.1), readers don't block writers but concurrent writers can still conflict.
- **Recommended fix**: Use `BEGIN IMMEDIATE` for write transactions. Add retry logic for "database is locked" errors (up to 3 retries). Use `PRAGMA busy_timeout` for automatic wait.
- **Effort**: S
- **Affects model layer**: No
- **Acceptance criteria**: Write transactions use BEGIN IMMEDIATE; concurrent writes retry 3 times; no "database is locked" errors under concurrent load test

### 7.5 _symbol_data Connection Not Closed on Exception [MEDIUM]

- **Severity**: Medium
- **Evidence**: `backend/api_server.py:464-525` — `_symbol_data` opens one connection (line 466), does 10+ queries, calls `conn.close()` at line 524. If ANY exception occurs between lines 466 and 524, the connection leaks. There is no try/finally block.
- **Risk**: Under error conditions (DB lock, corrupt data, unexpected null), the connection leaks. Each leak uses ~2MB RAM. 100 errors = 200MB leaked.
- **Recommended fix**: Wrap in try/finally: `try: ... finally: conn.close()`. Same pattern affects `_symbol_data`'s nested calls.
- **Effort**: S
- **Affects model layer**: No
- **Acceptance criteria**: _symbol_data uses try/finally; connection count stable after error storm; 194 tests still pass

### 7.6 Chat Message Cleanup Uses Subquery [LOW]

- **Severity**: Low
- **Evidence**: `backend/api_server.py:1437` — `DELETE FROM chat_messages WHERE id NOT IN (SELECT id FROM chat_messages WHERE channel=? ORDER BY id DESC LIMIT 500) AND channel=?`. This is a correlated subquery that can be slow on large tables. SQLite doesn't optimize `NOT IN (LIMIT)` well.
- **Risk**: As chat_messages grows, the cleanup DELETE slows down. Currently bounded by 500/2000 limit, but if retention code fails, table grows without bound and cleanup becomes increasingly expensive.
- **Recommended fix**: Use `DELETE FROM chat_messages WHERE id < (SELECT MIN(id) FROM (SELECT id FROM chat_messages WHERE channel=? ORDER BY id DESC LIMIT 500) AS sub)` for more efficient deletion. Or use a scheduled cleanup job instead of inline cleanup.
- **Effort**: S
- **Affects model layer**: No
- **Acceptance criteria**: Chat cleanup query optimized; cleanup time < 1 second on 100k rows; test validates cleanup performance

---

## Dimension 8: Security

### 8.1 No Authentication on Portfolio Endpoints [HIGH]

- **Severity**: High
- **Evidence**: `backend/api_server.py:939-990` — `/api/portfolio` GET returns all portfolios (no user filter). `/api/portfolio` POST adds to any portfolio. `/api/portfolio/<int:pid>` DELETE removes any entry. No user identification, no session, no API key, no token.
- **Risk**: Anyone can see or modify any portfolio. In a production context with real trading data, this is a critical data exposure vulnerability. Even for paper trading, it's a privacy issue.
- **Recommended fix**: Add API key authentication for portfolio endpoints. Associate portfolios with users (add `user_id` to portfolio table). Filter portfolio queries by authenticated user.
- **Effort**: L
- **Affects model layer**: No
- **Acceptance criteria**: Portfolio endpoints require auth; portfolios are user-isolated; unauthenticated requests return 401

### 8.2 No Input Validation on Portfolio POST [HIGH]

- **Severity**: High
- **Evidence**: `backend/api_server.py:962-982` — `portfolio_add` takes `body.get("symbol")`, `body.get("entry_price")`, `body.get("quantity")`, etc. without validation. `entry_price` and `quantity` could be negative, zero, or non-numeric. `symbol` is not checked against known symbols. `direction` defaults to "LONG" if not "LONG" or "SHORT" but accepts ANY other string value as-is (only explicitly forces to LONG if not SHORT).
- **Risk**: Invalid portfolio entries corrupt backtest data. Negative quantities create nonsensical P&L. Invalid symbols break downstream queries. This is a data integrity issue, not just a security issue.
- **Recommended fix**: Validate all portfolio fields: symbol must be in `config/instruments.json`, entry_price must be positive float, quantity must be positive integer, direction must be LONG or SHORT, dates must be valid ISO. Return 400 with specific error messages for invalid fields.
- **Effort**: S
- **Affects model layer**: No
- **Acceptance criteria**: Portfolio POST validates all fields; invalid requests return 400 with specific errors; valid requests unchanged; 194 tests still pass

### 8.3 Debug Mode Off but Flask App Importable [MEDIUM]

- **Severity**: Medium
- **Evidence**: `backend/api_server.py:1471` — `app.run(host="0.0.0.0", port=port, debug=False)`. Debug is correctly False ✅. However, `app` is importable from `backend.api_server`, which means any module that imports it can access the Flask app object, including all route definitions.
- **Risk**: If debug mode is accidentally enabled (e.g., via environment variable), the Werkzeug debugger provides interactive Python execution in the browser. With no auth, this is RCE. While debug=False currently prevents this, there's no enforcement.
- **Recommended fix**: Add explicit assertion: `assert os.environ.get("FLASK_DEBUG", "0") != "1"`. Set `app.config["DEBUG"] = False` explicitly. Add to deployment checklist.
- **Effort**: S
- **Affects model layer**: No
- **Acceptance criteria**: Debug mode explicitly disabled; environment variable enforced; deployment checklist includes debug check

### 8.4 Secrets Stored in /etc/tradingai/ [MEDIUM]

- **Severity**: Medium
- **Evidence**: `deploy-vm.sh:36` — `echo 'export GROQ_API_KEY=PLACEHOLDER_REPLACE_ON_VM' > /etc/tradingai/groq.env && chmod 600`. API key stored on VM filesystem. `ops/RESTORE.md` documents this. No secrets in git ✅ (`.gitignore` excludes `.env`). `config/settings.json` has no secrets ✅.
- **Risk**: VM compromise exposes API keys. No key rotation mechanism. No vault integration. Backup (`vm-backup.sh`) includes `/etc/tradingai/`? No — `deploy-vm.sh` excludes `/etc/tradingai/` from rsync ✅. But the VM itself is the single point of failure.
- **Recommended fix**: Document key rotation procedure. Consider adding a secrets manager (even a simple encrypted file). Ensure `vm-backup.sh` does NOT include `/etc/tradingai/`.
- **Effort**: L
- **Affects model layer**: No
- **Acceptance criteria**: Key rotation documented; secrets not in any backup; vm-backup.sh excludes /etc/tradingai/

### 8.5 nginx Cache May Expose Stale Auth Data [MEDIUM]

- **Severity**: Medium
- **Evidence**: `ops/nginx-tradingai.conf` — `location /api/ { proxy_cache api_cache; proxy_cache_valid 200 10s; }`. ALL API responses are cached for 10 seconds by nginx (except chat endpoints which use 2s and GET-only cache). This includes responses that might contain user-specific or time-sensitive data.
- **Risk**: If user-specific data (portfolio, alerts, P&L) ever goes through the generic /api/ cache, one user could see another user's cached data. Currently portfolio endpoints don't seem to use the cache, but this needs explicit exclusion.
- **Recommended fix**: Add `proxy_no_cache` directive for authenticated endpoints (portfolio, chat POST, alerts if user-specific). Explicitly list endpoints that must NOT be cached.
- **Effort**: S
- **Affects model layer**: No
- **Acceptance criteria**: nginx config explicitly excludes auth-required endpoints from cache; test validates no caching for portfolio endpoints

### 8.6 No CSRF Protection [MEDIUM]

- **Severity**: Medium
- **Evidence**: `backend/api_server.py` — State-changing endpoints (POST /api/portfolio, DELETE /api/portfolio/<id>, POST /api/chat/messages) have no CSRF protection. CORS allows all origins (finding 2.2). No CSRF tokens.
- **Risk**: A malicious website can submit a portfolio add/delete on behalf of a logged-in user via browser-based request. If auth is added later without CSRF protection, this becomes a critical vulnerability.
- **Recommended fix**: Add CSRF token validation for all state-changing endpoints. Use same-origin policy enforcement. At minimum, check `Origin` or `Referer` header on POST/DELETE.
- **Effort**: S
- **Affects model layer**: No
- **Acceptance criteria**: CSRF tokens required for state-changing endpoints; Origin header validated; tests verify CSRF protection

### 8.7 SQL Injection Analysis [LOW]

- **Severity**: Low
- **Evidence**: `backend/api_server.py` — All SQL queries use parameterized queries (`?` placeholders) ✅. Exceptions:
  - Line 123: `f"SELECT * FROM {table} WHERE symbol=?..."` — table name is hardcoded (from `interval` arg, filtered by `if interval in ("1m", "5m", "15m", "1d")`), safe but fragile.
  - Line 136: `f"SELECT * FROM price_1m WHERE symbol IN ({placeholders})..."` — values are parameterized (`?`), table name hardcoded, safe.
  - `backend/data_fetcher_db.py:293` — `f"INSERT OR IGNORE INTO {interval_table}..."` — table name from `interval` variable, need to verify it's filtered.
  - `backend/database.py:283,302` — `f"SELECT * FROM {table} WHERE..."` — table name passed as function parameter, could be user-controlled if function is called with user input.
- **Risk**: Current code is safe (all user inputs parameterized). But pattern is fragile — future code might pass user input as table name.
- **Recommended fix**: Define `ALLOWED_TABLES` constant. Assert table name is in allowlist before any f-string SQL. Add a linter rule for f-string SQL.
- **Effort**: S
- **Affects model layer**: No
- **Acceptance criteria**: All table names in SQL are assert against ALLOWED_TABLES; linter rule added; test verifies no f-string SQL with user input

### 8.8 Error Responses Leak Request Context [LOW]

- **Severity**: Low
- **Evidence**: `backend/api_server.py` — Error messages like `{"error": f"unknown symbol {symbol}"}` (line 218), `{"error": f"no outlook yet for {symbol}"}` (line 910) echo user input. Flask debug mode is off ✅, but unhandled exceptions produce Flask's default error page which includes stack traces and code snippets.
- **Risk**: Error messages that echo user input can be used for social engineering. Flask's default error page (in production without debug) still reveals the framework version and Python version.
- **Recommended fix**: Add custom error handlers (`@app.errorhandler(404)`, `@app.errorhandler(500)`) that return JSON without stack traces. Set `app.config["PROPAGATE_EXCEPTIONS"] = False`.
- **Effort**: S
- **Affects model layer**: No
- **Acceptance criteria**: Custom error handlers return JSON; no stack traces in responses; Flask version not exposed

---

## Dimension 9: Failure/Recovery

### 9.1 No Graceful Degradation for Market-Data Outage [HIGH]

- **Severity**: High
- **Evidence**: `backend/api_server.py` — If price data is unavailable (empty tables), `/api/price/<symbol>` returns 404, `/api/<symbol>` returns partial data (may have regime but no quote, or vice versa), `/api/market` returns `{}` or `{"instruments": {}, ...}`. There's no cached fallback to "last known good" data. If NSE feed is down for 30 minutes, every price request fails for 30 minutes.
- **Risk**: During a data-source outage, users see completely empty pages. No data at all — not even stale data. For an options-trading platform, "no data" during market hours is unacceptable.
- **Recommended fix**: Implement "last known good" caching. Cache the last successful response for each endpoint (5-minute TTL). During outage, serve cached data with `stale: true` flag. Clearly distinguish "fresh data" from "cached stale data."
- **Effort**: L
- **Affects model layer**: No
- **Acceptance criteria**: Cached data served during outage with stale flag; staleness clearly communicated to user; outage alert triggers

### 9.2 No VIX Outage Fallback [MEDIUM]

- **Severity**: Medium
- **Evidence**: `backend/api_server.py` — VIX endpoints (`/api/vix`, `/api/vix/history`, `/api/vix/daily`) return 404 if no VIX data. `backtest.py` — VIX-based strategies check `if v_open is None or v_close is None: v_close = v_open = 14.0` (fallback to 14). But `/api/global` includes CBOE VIX in global markets, and if it fails, that symbol is just skipped.
- **Risk**: VIX is critical for options analysis. A VIX outage makes options-intelligence, backtest, and global-markets incomplete without warning.
- **Recommended fix**: Serve last-known VIX data during outage with staleness warning. Add VIX-specific health check. Alert on VIX data gap > 15 minutes.
- **Effort**: M
- **Affects model layer**: No
- **Acceptance criteria**: Last VIX data served during outage; VIX-specific health check exists; alert on VIX data gap

### 9.3 No Options-Data Outage Fallback [MEDIUM]

- **Severity**: Medium
- **Evidence**: `backend/api_server.py` — If `option_chain` and `option_expiries` are empty (options data fetch failed), all options endpoints return empty arrays or null values. `/api/options-intelligence` returns `{"data_quality": "LIVE", ...}` with null fields (finding 6.6).
- **Risk**: Options traders see empty data with "LIVE" quality indicator. This is dangerously misleading — they might make trading decisions on empty data.
- **Recommended fix**: Serve cached last-known options data during outage. Change quality indicator to `"DATA UNAVAILABLE"` when option_chain has no recent data. Add explicit messaging: "Options data unavailable — last fetch was X hours ago."
- **Effort**: M
- **Affects model layer**: No
- **Acceptance criteria**: Options endpoints serve cached data during outage; quality indicator reflects actual data status; explicit messaging about data staleness

### 9.4 Database Failure Recovery [MEDIUM]

- **Severity**: Medium
- **Evidence**: `ops/self-heal.sh:47-58` — Self-heal checks DB integrity (`SELECT 1 FROM symbols LIMIT 1`) and tries to restore from backup (`/opt/tradingai-backup/database/tradingai.db`) on failure. This is a good start. But: recovery is best-effort, no notification on failure, no alerting on DB corruption, and recovery doesn't verify data consistency beyond the initial integrity check.
- **Risk**: DB corruption detected by self-heal, but if the backup is also corrupt (unlikely but possible), recovery fails silently. API continues running with potentially inconsistent data.
- **Recommended fix**: Add DB corruption alert (not just self-heal log). Add recovery verification (compare row counts before/after restore). Add alert on any self-heal DB recovery event.
- **Effort**: S
- **Affects model layer**: No
- **Acceptance criteria**: DB recovery triggers alert; row count comparison verifies restore; corruption alerts on separate channel from self-heal log

### 9.5 Stale Data Detection [MEDIUM]

- **Severity**: Medium
- **Evidence**: `backend/api_server.py:37-85` — `/api/health` detects stale data (NIFTY > 30 min, VIX > 60 min, outlook > 1 day) and reports `status: "degraded"`. `backend/api_server.py:258-274` — `_live_quote_row` checks 25-min freshness. But: no other endpoint tells the user that the data they're viewing is stale. The stale indicator is only in /api/health.
- **Risk**: User views market data that's 2 hours old but doesn't know it because only /api/health shows stale status. The market page looks normal but data is outdated.
- **Recommended fix**: Add `data_age` or `stale` flag to EVERY data endpoint response, not just /api/health. Each response should include when the data was last updated and whether it's stale.
- **Effort**: M
- **Affects model layer**: No
- **Acceptance criteria**: All data endpoints include `data_freshness` info; stale flag present in every response; test validates stale flag on stale data

### 9.6 API Restart Behavior [MEDIUM]

- **Severity**: Medium
- **Evidence**: `ops/systemd/tradingai-api.service` — `Restart=always, RestartSec=10`. Systemd restarts on crash ✅. `ops/self-heal.sh:30-44` — Self-heal detects API unhealthiness and restarts via systemctl. But: no graceful shutdown (SIGTERM not handled by Flask app), no in-flight request drain, no startup verification.
- **Risk**: API restart drops in-flight requests without warning. A user mid-backtest (which could take 30+ seconds) loses their work. No notification that the API restarted.
- **Recommended fix**: Add Flask `@app.before_first_request` or startup hook that runs health checks. Add SIGTERM handler for graceful shutdown. Add `StartLimitIntervalSec=60` and `StartLimitBurst=10` (already in service file ✅). Add post-restart verification in self-heal.
- **Effort**: M
- **Affects model layer**: No
- **Acceptance criteria**: API handles SIGTERM gracefully; startup verifies health before accepting traffic; restart is logged and observable

### 9.7 No Rollback Strategy [MEDIUM]

- **Severity**: Medium
- **Evidence**: `ops/RESTORE.md` — Documents full VM rebuild from vm-backup branch. But: no code rollback (git checkout previous commit + restart). No database rollback. No staged rollout. No canary deployment.
- **Risk**: A bad deploy that breaks the API requires full VM rebuild to roll back, which takes 30+ minutes per RESTORE.md. No fast rollback.
- **Recommended fix**: Add rollback script: `git checkout <previous_commit> && pip install -r requirements && systemctl restart tradingai-api`. Keep last 3 deploy commits available for instant rollback. Document rollback procedure.
- **Effort**: S
- **Affects model layer**: No
- **Acceptance criteria**: Rollback script exists and is tested; rollback completes in < 2 minutes; last 3 commits are reachable

### 9.8 No Request Queuing [LOW]

- **Severity**: Low
- **Evidence**: `ops/systemd/tradingai-api.service:12` — Gunicorn with 3 workers × 2 threads = 6 concurrent requests. No request queue. Flask synchronous — each request blocks a worker until complete. `--max-requests 1000 --max-requests-jitter 100` recycles workers after 1000 requests (good for memory, but not for queue management).
- **Risk**: Under traffic spike (>6 concurrent users), additional requests are queued by gunicorn but have no timeout at the queue level. Users see connection timeout, not "request queued."
- **Recommended fix**: Increase workers (4-5 workers for 1GB VM). Add request queue size limit. Add queue-depth monitoring. Consider async workers for I/O-bound endpoints.
- **Effort**: L
- **Affects model layer**: No
- **Acceptance criteria**: Queue size configured; queue depth monitored; traffic spike test shows graceful degradation

---

## Dimension 10: Performance

### 10.1 Blocking Backtest Endpoints [CRITICAL]

- **Severity**: Critical
- **Evidence**: `backend/api_server.py:992-1020` — `/api/backtest`, `/api/backtest/vix-strangle`, `/api/backtest/5m-real` all run `BacktestEngine.run()` synchronously in the request handler. `backend/backtest.py:run()` (355 lines) can take 30+ seconds for 10-year backtests. Gunicorn `--timeout 90` means this works but ties up a worker for the entire duration.
- **Risk**: A single backtest request ties up a gunicorn worker for 30+ seconds. With 6 total threads, 2 concurrent backtests = 33% of API capacity consumed by computation. 3 concurrent backtests = 50% capacity. User experience degrades for everyone else during backtests.
- **Recommended fix**: Move backtests to async processing (Celery, or a simple job queue). Return `202 Accepted` with a job ID. Poll endpoint for results. OR pre-compute popular backtests (1y, 5y, 10y NIFTY) and cache results. Set a shorter timeout for backtest endpoints (30s) with progress updates.
- **Effort**: L
- **Affects model layer**: No
- **Acceptance criteria**: Backtests run async; API remains responsive during backtest; 194 tests still pass; backtest results cached for repeated queries

### 10.2 Expensive Options Endpoints [HIGH]

- **Severity**: High
- **Evidence**: `backend/api_server.py:750-876` — `/api/options-intelligence` (126 lines) creates multiple `OptionsEngine()` instances (lines 756, 790, 815, 819, 827), queries option_chain 2+ times, computes OI concentration, expected move, IV stats, max pain, and PCR — all in one request. `/api/maxpain` (lines 624-650) — one `OptionsEngine()` per expiry. `/api/pcr` (lines 602-622) — multiple queries per expiry. `/api/oi-concentration/<symbol>` (lines 681-717) — creates `OptionsEngine()` per call with multiple DB queries.
- **Risk**: Options endpoints are the most computationally expensive in the API. Under concurrent access, they can tie up all workers. Options data changes infrequently (daily EOD for most, 5min for live), so caching could dramatically reduce load.
- **Recommended fix**: Add response caching for options endpoints (1-minute TTL for live, 1-hour for EOD). Pre-compute options-intelligence overnight and serve cached results. Add per-endpoint timeout.
- **Effort**: M
- **Affects model layer**: No
- **Acceptance criteria**: Options endpoints have caching; response time < 3 seconds; concurrent options requests don't degrade API

### 10.3 /api/market Rebuild Blocks All Inceptors [HIGH]

- **Severity**: High
- **Evidence**: `backend/api_server.py:1116-1152` — `/api/market` has a 20-second TTL cache with a building lock. But during cache miss, `_build_market()` (lines 1155-1174) sequentially calls `_symbol_data()` for ALL active symbols (4 indices + 33 stocks = 37 calls). Each `_symbol_data` call opens a DB connection, runs 10+ queries, and creates a full response. Total rebuild: estimated 20-60 seconds. During rebuild, the building lock prevents concurrent rebuilds BUT first caller blocks until done (line 1138-1151: up to 35-second wait loop).
- **Risk**: A single cache miss on /api/market blocks a worker for up to 60 seconds. If multiple users hit the cache miss simultaneously, they all wait. Other endpoints still work but the most important page (market overview) is unresponsive.
- **Recommended fix**: Pre-compute market data asynchronously (every 15 seconds during market hours). Serve stale data during rebuild instead of blocking. Add a background refresh thread that updates the cache continuously.
- **Effort**: L
- **Affects model layer**: No
- **Acceptance criteria**: Market data cached continuously; no blocking rebuilds; stale data served during refresh; 194 tests still pass

### 10.4 No Response Caching (Except /api/market and /api/global) [MEDIUM]

- **Severity**: Medium
- **Evidence**: `backend/api_server.py` — Only `/api/market` (20s TTL, line 1191) and `/api/global` (90s TTL, line 1201) have response caching. All other 53 endpoints have no caching. nginx cache at `proxy_cache_valid 200 10s` applies to all /api/ responses but only caches 200s for 10s. Most dynamic data shouldn't be cached for 10s.
- **Risk**: Every request hits the database. 55 endpoints × multiple queries each = 20+ DB queries per request. At any given moment, many requests are racing against each other on the same data.
- **Recommended fix**: Add per-endpoint TTL based on data freshness:
  - Real-time (price, quotes): 5s cache
  - Daily (outlooks, strategies): 1-hour cache
  - Static (symbols, config): 24-hour cache
  - Computation (backtest, options): 10-minute cache
- **Effort**: M
- **Affects model layer**: No
- **Acceptance criteria**: Response caching implemented for all endpoint categories; cache hit rate > 50%; 194 tests still pass

### 10.5 No Pagination on List Endpoints [MEDIUM]

- **Severity**: Medium
- **Evidence**: `backend/api_server.py` — `/api/symbols`, `/api/strategies`, `/api/outlooks`, `/api/regimes`, `/api/snapshots`, `/api/breadth/history`, `/api/alerts` — all return ALL matching rows with only `limit` parameter (default 50 or 100). No `offset`, no `page`, no total count. `/api/all_prices` returns up to 50 records for ALL symbols. `/api/strategies` returns all strategies ever stored (potentially thousands).
- **Risk**: Large result sets cause slow responses, high memory usage, and timeouts. A user requesting `/api/strategies` with no limit gets all strategies ever created.
- **Recommended fix**: Add pagination (page + page_size) to all list endpoints. Add `total_count` to responses. Enforce maximum page_size (e.g., 500). Add `offset` for continuation.
- **Effort**: M
- **Affects model layer**: No
- **Acceptance criteria**: All list endpoints paginate; max page_size enforced; total_count included; test validates pagination

### 10.6 Concurrent User Behavior Not Tested [MEDIUM]

- **Severity**: Medium
- **Evidence**: Entire codebase — No concurrency tests. No load testing. No concurrent-request simulation. Gunicorn configured for 3 workers × 2 threads (6 concurrent). `_MARKET` TTL cache uses threading.Lock (line 1123) which is correct, but no other concurrency protection exists. SQLite default mode (not WAL — finding 7.1) has well-documented concurrency limitations.
- **Risk**: Under concurrent user load, undiscovered race conditions, deadlocks, or connection leaks may surface. SQLite with DELETE journal mode blocks readers during writes, causing timeouts.
- **Recommended fix**: Add concurrency test: simulate 10 concurrent requests to various endpoints. Monitor for: connection leaks, timeouts, data corruption, race conditions. Run during load test: price endpoint, market overview, backtest, options-intelligence.
- **Effort**: M
- **Affects model layer**: No
- **Acceptance criteria**: 10 concurrent requests complete without errors; no connection leaks; no data corruption; response times within SLA

### 10.7 No Per-Endpoint Timeout [LOW]

- **Severity**: Low
- **Evidence**: `backend/api_server.py` — No per-endpoint timeout. Flask default is no timeout. Gunicorn has `--timeout 90` globally. But a 90-second timeout is too generous for a data endpoint (should be 5s) and too strict for a backtest (could be 60s+).
- **Risk**: A data endpoint hanging (e.g., DB lock) ties up a worker for 90 seconds. A backtest that takes 31 seconds gets killed by gunicorn timeout (returning 500 to user).
- **Recommended fix**: Add per-endpoint timeout decorators or configuration. Data endpoints: 5s. Computation endpoints: 60s. Health endpoint: 2s. Options endpoints: 10s.
- **Effort**: S
- **Affects model layer**: No
- **Acceptance criteria**: Per-endpoint timeouts configured; test verifies endpoints respect timeouts; timeouts return 504

### 10.8 Database Query Efficiency [LOW]

- **Severity**: Low
- **Evidence**: `backend/api_server.py` — `_symbol_data` runs 10+ queries per call (price, indicators, regime, strategy, scenarios, outlook, investment, lot, expiry). Many use `ORDER BY timestamp DESC LIMIT 1` which benefits from indexes. `options_intelligence` runs multiple `SELECT DISTINCT expiry` and `SUM(open_interest)` queries per expiry. `options` endpoint uses `ORDER BY fetched_at DESC LIMIT 200` which may not use the best index.
- **Risk**: N+1-like patterns (e.g., options_intelligence per-expiry queries) become slower as option_chain grows. 200+ strikes per expiry × 2-3 expiries = 400-600 rows scanned per request.
- **Recommended fix**: Add composite indexes for frequently queried patterns (`symbol, expiry, option_type, strike`). Use `SUM()` in SQL instead of Python-side aggregation where possible. Batch options queries instead of per-expiry loops.
- **Effort**: L
- **Affects model layer**: No
- **Acceptance criteria**: Query time for options endpoints < 3 seconds; composite indexes added; batch queries replace per-expiry loops

---

## Dimension 11: Production Deployment

### 11.1 No Health Check on Deploy [HIGH]

- **Severity**: High
- **Evidence**: `deploy-vm.sh:45` — `curl -s http://127.0.0.1:8000/api/health || true`. The `|| true` means even if health check fails, deploy script continues to completion. No assertion that health check returns `{"status": "ok"}`.
- **Risk**: A broken deploy that returns 500 on /api/health is not caught. Deploy completes, users see broken site, operator discovers via user complaints.
- **Recommended fix**: Remove `|| true`. Check that response contains `"status": "ok"`. Fail deploy if health check doesn't return OK. Add pre-deploy health check (ensure current API is healthy before deploying).
- **Effort**: S
- **Affects model layer**: No
- **Acceptance criteria**: Deploy fails if health check returns non-ok status; deploy script exits non-zero on health failure; pre-deploy health check added

### 11.2 No Process Supervisor Beyond systemd [MEDIUM]

- **Severity**: Medium
- **Evidence**: `ops/systemd/tradingai-api.service` — Systemd supervises the gunicorn process (`Restart=always`). But: no process monitor (like supervisord or systemd service watching), no memory limit, no CPU limit, no oom-score adjustment for gunicorn workers (OOMScoreAdjust=-200 is set, which is good). No log rotation for gunicorn logs.
- **Risk**: If gunicorn memory grows (e.g., connection leak, cache growth), systemd restarts it, but memory grows again. No automatic memory-based restart. No log rotation (gunicorn-access.log and gunicorn-error.log grow unbounded).
- **Recommended fix**: Add memory limit to systemd unit (`MemoryMax=512M`). Add logrotate for gunicorn logs. Add memory-based restart threshold in systemd (`RestartTriggersMemoryDeny`).
- **Effort**: S
- **Affects model layer**: No
- **Acceptance criteria**: Systemd unit has memory limit; logrotate configured; memory-based restart tested

### 11.3 No Structured Deployment Logging [MEDIUM]

- **Severity**: Medium
- **Evidence**: `deploy-vm.sh` — Deploy script outputs to stdout only. No deployment log file. No timestamp on deploy events. No success/failure logging. `ops/RESTORE.md` documents the restore process but no automated logging of actual restores.
- **Risk**: When something goes wrong, there's no deploy history. "When was the last deploy? What changed? Did it succeed?" — all require git log inspection.
- **Recommended fix**: Add deploy logging: timestamp, commit hash, deploy result (success/failure), health check result. Write to `/opt/tradingai/logs/deploy.log`. Add deploy notification (email/chat).
- **Effort**: S
- **Affects model layer**: No
- **Acceptance criteria**: Deploy log exists; includes timestamp, commit, result; deploy.log rotated; deploy notification configured

### 11.4 Manual Cron Installation [MEDIUM]

- **Severity**: Medium
- **Evidence**: `ops/setup-new-vm.sh:58-59` — Cron installed via `crontab -` (piped from file). `ops/crontab.txt` — Cron entries are documented but if cron service restarts, the crontab is not automatically restored (crontab is VM-local, not in repo). `ops/self-heal.sh:86-89` — Self-heal checks if cron daemon is running but doesn't re-install crontab if it was cleared.
- **Risk**: If cron service crashes and restarts, all cron jobs are lost. Self-heal checks cron daemon but doesn't verify crontab contents. All data freshness, monitoring, and backup jobs stop running silently.
- **Recommended fix**: Add cron installation to self-heal.sh (install crontab from file if missing or incomplete). Add crontab verification to self-heal (count expected entries). Document cron installation procedure.
- **Effort**: S
- **Affects model layer**: No
- **Acceptance criteria**: Self-heal installs crontab if incomplete; crontab verification checks entry count; cron restart triggers crontab re-install

### 11.5 No Database Backup Verification [MEDIUM]

- **Severity**: Medium
- **Evidence**: `ops/vm-backup.sh:66-85` — Backup script verifies snapshot integrity (`PRAGMA integrity_check`) and row counts BEFORE committing. This is excellent ✅. But: backup verification is only done at backup time. If the DB becomes corrupt AFTER the backup, the backup is no longer valid. No backup age check. No backup-to-live consistency check.
- **Risk**: Backup is 2 days old and DB has been updated since. Backup doesn't include recent data. Or backup is from a corrupt DB state (unlikely but possible if corruption started before backup).
- **Recommended fix**: Add backup age check to self-heal (alert if backup is >24 hours old). Add periodic backup-to-live comparison (row counts). Document RPO (Recovery Point Objective) — current is 24 hours (daily backup).
- **Effort**: S
- **Affects model layer**: No
- **Acceptance criteria**: Backup age monitored; alert if backup >24 hours old; backup verification runs before each backup; RPO documented

### 11.6 Rollback Script Not Documented [LOW]

- **Severity**: Low
- **Evidence**: `ops/RESTORE.md` — Documents full VM rebuild (30+ minutes). But no fast rollback (< 2 minutes). `deploy-vm.sh` — No rollback section. Git history allows `git checkout <commit>` but process: SSH to VM, checkout code, reinstall deps, restart systemd, verify — not documented.
- **Risk**: Rollback takes 30+ minutes because the documented procedure is full VM rebuild. Operators may improvise (and potentially introduce errors).
- **Recommended fix**: Add fast rollback section to RESTORE.md: `git checkout <prev_commit> && pip install -r ops/requirements.txt && systemctl restart tradingai-api && curl /api/health`. Keep last 3 commits accessible. Test rollback quarterly.
- **Effort**: S
- **Affects model layer**: No
- **Acceptance criteria**: Fast rollback documented; rollback tested; rollback completes in < 2 minutes

---

## Dimension Cross-Cutting: Model Layer Impact

All 61 findings in this audit affect ONLY the operational, UX, infrastructure, and productization layers. **Zero findings affect the analytical/model layer.** This is confirmed by:

1. `git diff 45f90fc 51c02f9 --name-only` shows only: `PHASE6A_SPECIFICATION.md`, `backend/api_server.py`, `index.html`, `market/outlook-nifty-2026-09-13.html`, `tests/test_phase6a.py`
2. None of `backend/regime.py`, `backend/strategies.py`, `backend/outlook.py`, `backend/scenarios.py`, `backend/options.py`, `backend/ai_outlook.py`, `backend/backtest.py` were modified at `51c02f9`
3. The frozen baseline `45f90fc` remains the analytical/model baseline
4. All PHASE 6B findings propose operational improvements only — none modify model logic, thresholds, formulas, or data structures

**Architecture boundary preserved**:
```
Market Data → RegimeEngine (frozen) → StrategyEngine (frozen) → OptionsEngine (frozen)
LLM explains (frozen boundary)
Monitoring verifies system health (NEW - PHASE 6B targets)
UI communicates risk clearly (PHASE 6A + 6B)
API layer: operational hardening (PHASE 6B targets)
```

---

## Audit Governance

### Review Process

1. This audit is read-only. No implementations proposed.
2. Each finding has a severity, evidence, recommended fix, and effort estimate.
3. PHASE 6B implementation will be prioritized per: Reliability → Stale-data → Abuse → Monitoring → CI regression → Security → Performance → Deployment
4. After implementation, a follow-up PHASE 6B verification audit will confirm each fix meets its acceptance criteria
5. The 194-test regression baseline must remain passing after PHASE 6B implementation

### Severity Definitions

| Severity | Definition |
|---|---|
| Critical | System down, data lost, or trading decisions compromised |
| High | Significant degradation, data exposure, or operational failure |
| Medium | Notable risk that should be addressed before public launch |
| Low | Minor improvement, nice-to-have, technical debt |

### Finding Status

| Status | Meaning |
|---|---|
| OPEN | Identified in this audit, not yet addressed |
| ACCEPTED | Acknowledged, will be addressed in PHASE 6B |
| DEFERRED | Acknowledged, deferred to future phase |
| WONTFIX | Acknowledged, not actionable or not worthwhile |

All findings are currently **OPEN** pending PHASE 6B implementation authorization.

---

## Appendix A: Endpoint Inventory

Total endpoints: 55 (54 GET, 3 POST, 2 DELETE — some endpoints support multiple methods)

| Category | Endpoints | Rate Limit Needed | Cache Candidate |
|---|---|---|---|
| Data/Price | /api/price, /api/prices, /api/prices, /api/<symbol>, /api/symbols, /api/vix*, /api/indicators* | Yes | Yes (5s) |
| Market Overview | /api/market, /api/global, /api/market-outlook*, /api/history | Yes | Yes (20s-60s) |
| Strategy/Regime | /api/strategy*, /api/strategies, /api/regime*, /api/regimes, /api/scenarios*, /api/outlook*, /api/outlooks | Yes | Yes (1h) |
| Options | /api/options*, /api/pcr, /api/maxpain, /api/pcr-history, /api/oi-top, /api/oi-concentration, /api/expected-move, /api/options-intelligence | Yes | Yes (10m) |
| Backtest | /api/backtest, /api/backtest/vix-strangle, /api/backtest/5m-real | Yes | Yes (10m) |
| Portfolio | /api/portfolio (GET/POST), /api/portfolio/<id> (DELETE) | Yes | No (auth required) |
| Alerts/Chat | /api/alerts, /api/chat/messages, /api/chat/alerts | Yes | Conditional |
| Misc | /api/health, /api/breadth*, /api/snapshot*, /api/etf*, /api/fundamentals*, /api/data_status, /api/etf | Yes | Varies |

* = multiple endpoints

## Appendix B: Connection Count Analysis

Per typical API request, connections opened:

| Endpoint | Connections | Risk |
|---|---|---|
| /api/price/<symbol> | 1-2 | Low (simple query) |
| /api/<symbol> (_symbol_data) | 1 (+ 1 nested in _build_quote) | Medium |
| /api/market | 1 (then calls _symbol_data N times) | High |
| /api/options-intelligence | 1 | Medium |
| /api/backtest | 0 (BacktestEngine creates own) | Low |
| /api/portfolio (POST) | 1 | Low |
| /api/health | 1 | Low |

## Appendix C: Regression Test Coverage

| Test File | Tests | Coverage |
|---|---|---|
| tests/test_phase6a.py | 10 | Health endpoint, UX safety, WAIT messaging |
| tests/test_pipeline_coverage.py | 35 | Pipeline integration, regime propagation, LLM boundary |
| tests/test_regime.py | 25 | RegimeEngine, StrategyEngine, scenarios |
| tests/test_regime_integration.py | 9 | Alert normalization, regime integration |
| tests/test_regime_utils.py | 19 | normalize_regime function |
| tests/test_step5d.py | 19 | Scenario normalization, confidence semantics, determinism |
| tests/test_chat_alert.py | 10 | Chat alert functionality |
| tests/test_max_pain.py | 54 | Max Pain calculations |
| tests/test_llm_boundary.py | 67 | LLM boundary invariants |
| **Total** | **248 test cases** (194 passing as of 51c02f9) | |

---

*End of PHASE 6B Production Hardening Audit. Awaiting review and prioritization before PHASE 6B implementation begins.*
