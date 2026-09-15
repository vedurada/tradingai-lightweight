# PHASE 6B-2 — Implementation Specification

**Scope**: Abuse Protection + API Security
**Status**: READY FOR REVIEW
**Frozen baselines**: `45f90fc` (analytical), `51c02f9` (PHASE 6A), `63ab095` (PHASE 6B-1)
**Regression baseline**: 220/220 passing
**Audit source**: PHASE6B_PRODUCTION_HARDENING_AUDIT.md (61 findings, 7 addressed in 6B-1, 54 remaining)
**Scope approval**: See PHASE6B_STEP2_SCOPE_REVIEW.md (APPROVED)

---

## Part 0: Implementation Boundaries

### Must NOT Change (Verified by test)

- ❌ RegimeEngine calculations and thresholds
- ❌ StrategyEngine selection logic
- ❌ OptionsEngine computations
- ❌ Confidence mathematics
- ❌ Scenario normalization (Σ=1.00)
- ❌ LLM boundary (outlook.py merge logic)
- ❌ Backtest methodology
- ❌ Historical validation methodology
- ❌ Any quantitative/model output
- ❌ Successful API response payloads for any endpoint
- ❌ All 220 existing tests must remain green

### Must Add

- ✅ Rate limiting per endpoint category
- ✅ CORS restriction with allowlist
- ✅ Input validation on state-changing endpoints
- ✅ Authentication boundary documentation
- ✅ Tests for all new behavior

### Additive Only

- Error responses may use standardized schema (from 6B-1 `error_response()` utility)
- Rate-limit responses use 429 status with standardized error
- Validation failures return 400 with specific error messages
- All changes are additive to existing successful behavior

---

## Part A: Rate Limiting

### A.1 Finding: 2.1 — Zero Rate Limiting on 53 of 55 Endpoints [CRITICAL]

**Effort**: M
**Affects model layer**: No

**Specification**:

#### Endpoint Category Classification

All 55 endpoints classified by risk and function:

| Category | Rate Limit | Endpoints |
|---|---|---|
| **Health** | Exempt | `/api/health` |
| **Data/Price** | 60/min per IP | `/api/price/<symbol>`, `/api/prices/<symbol>`, `/api/symbols`, `/api/vix`, `/api/vix/history`, `/api/vix/daily`, `/api/indicators/<symbol>`, `/api/indicators` |
| **Market Overview** | 60/min per IP | `/api/market`, `/api/global`, `/api/market-outlook`, `/api/market-outlook/<date>`, `/api/history`, `/api/breadth`, `/api/breadth/history`, `/api/snapshot`, `/api/snapshots` |
| **Strategy/Regime** | 60/min per IP | `/api/strategy/<symbol>`, `/api/strategies`, `/api/regime/<symbol>`, `/api/regimes`, `/api/scenarios/<symbol>`, `/api/outlook/<symbol>`, `/api/outlooks` |
| **Options** | 30/min per IP | `/api/options/<symbol>`, `/api/options/expiries/<symbol>`, `/api/pcr`, `/api/maxpain`, `/api/pcr-history`, `/api/oi-top`, `/api/oi-concentration/<symbol>`, `/api/expected-move/<symbol>`, `/api/options-intelligence/<symbol>` |
| **Backtest** | 10/min per IP | `/api/backtest`, `/api/backtest/vix-strangle`, `/api/backtest/5m-real` |
| **Portfolio** | 30/min per IP | `/api/portfolio` (GET), `/api/portfolio` (POST), `/api/portfolio/<id>` (DELETE) |
| **Alerts/Chat** | 30/min per IP | `/api/alerts`, `/api/chat/messages`, `/api/chat/alerts` |
| **Misc** | 60/min per IP | `/api/etf`, `/api/etf-holdings`, `/api/fundamentals/<symbol>`, `/api/data_status` |

#### Implementation

1. **Install Flask-Limiter** (add to requirements if not present):
   ```python
   from flask_limiter import Limiter
   from flask_limiter.util import get_remote_address
   ```

2. **Initialize in api_server.py** after CORS setup:
   ```python
   limiter = Limiter(
       app=app,
       key_func=get_remote_address,
       default_limits=["60/minute"],
       storage_uri="memory://",
   )
   ```

3. **Apply per category**:
   ```python
   # Health — exempt
   @app.route("/api/health")
   @limiter.exempt
   def health(): ...

   # Data/Price — 60/min
   @app.route("/api/price/<symbol>")
   @limiter.limit("60/minute")
   def latest_price(symbol): ...

   # Backtest — 10/min (computation-heavy)
   @app.route("/api/backtest")
   @limiter.limit("10/minute")
   def backtest(): ...

   # Portfolio — 30/min
   @app.route("/api/portfolio", methods=["GET"])
   @limiter.limit("30/minute")
   def portfolio_list(): ...
   ```

4. **Custom rate-limit error** (use 6B-1 error_response utility):
   ```python
   @app.errorhandler(429)
   def _handle_429(e):
       return error_response("RATE_LIMITED", "Too many requests, please wait", 429)
   ```

#### Bounded Retry Compatibility

Rate limiting must not interfere with legitimate retry behavior from 6B-1:
- Rate-limit windows are per-IP, not per-process
- 6B-1 retry decorators handle transient API failures (external APIs), not rate-limit responses
- A 429 response from our own API should NOT be retried by 6B-1 retry logic (add 429 to non-retryable errors)

#### Tests

| Test | Description |
|---|---|
| `test_rate_limit_enforcement` | Hit endpoint >60 times in 1 minute, verify 429 returned after limit |
| `test_rate_limit_recovery` | After window clears, requests succeed again |
| `test_rate_limit_health_exempt` | `/api/health` has no rate limit |
| `test_rate_limit_categories` | Verify different categories have different limits |
| `test_rate_limit_per_ip` | Two different IPs each get their own limit |
| `test_rate_limit_header` | 429 response includes `Retry-After` header |

#### Acceptance Criteria

- All 55 endpoints have rate limits configured
- 429 returned when limit exceeded
- Health endpoint exempt
- Legitimate single-user traffic unaffected (60/min is generous)
- 429 uses standardized error schema from 6B-1
- 220 existing tests still pass
- No model layer changes

### A.2 Finding: 2.4 — No Request Size Limits [MEDIUM]

**Effort**: S
**Affects model layer**: No

**Specification**:

1. **Set global request size limit**:
   ```python
   app.config['MAX_CONTENT_LENGTH'] = 1 * 1024 * 1024  # 1MB
   ```

2. **Return standardized 413 for oversized requests**:
   ```python
   @app.errorhandler(413)
   def _handle_413(e):
       return error_response("INVALID_REQUEST", "Request body too large", 413)
   ```

**Tests**:

| Test | Description |
|---|---|
| `test_request_too_large_rejected` | Request >1MB → 413 |
| `test_valid_requests_unchanged` | Requests ≤1MB succeed |

**Acceptance Criteria**:
- Requests >1MB return 413
- All existing valid requests still pass
- 220 existing tests still pass

---

### A.3 Finding: 2.5 — No Request Timeout Enforcement [MEDIUM]

**Effort**: M
**Affects model layer**: No

**Specification**:

1. **Per-endpoint timeout configuration**:
   ```python
   ENDPOINT_TIMEOUTS = {
       "health": 2,
       "data": 5,
       "market": 10,
       "options": 10,
       "backtest": 60,
       "strategy": 10,
       "portfolio": 5,
       "list": 5,
   }
   ```

2. **Implement via Flask before_request hook**:
   ```python
   import signal

   def _request_timeout_handler(signum, frame):
       raise TimeoutError("Request timeout")

   @app.before_request
   def _set_request_timeout():
       endpoint = request.endpoint
       if endpoint in ENDPOINT_TIMEOUTS:
           timeout = ENDPOINT_TIMEOUTS[endpoint]
           signal.signal(signal.SIGALRM, _request_timeout_handler)
           signal.alarm(timeout)

   @app.after_request
   def _clear_request_timeout(response):
       signal.alarm(0)
       return response
   ```

3. **Handle timeout errors**:
   ```python
   @app.errorhandler(TimeoutError)
   def _handle_timeout(e):
       app.logger.warning(f"Request timeout: {request.endpoint}")
       return error_response("INTERNAL_ERROR", "Request timed out", 504)
   ```

**Tests**:

| Test | Description |
|---|---|
| `test_data_endpoint_timeout` | Slow data endpoint → 504 after 5s |
| `test_health_endpoint_timeout` | Slow health endpoint → 504 after 2s |
| `test_backtest_timeout` | Slow backtest → 504 after 60s |

**Acceptance Criteria**:
- Each endpoint category has a timeout
- Endpoints exceeding timeout return 504
- Normal endpoints complete within their timeout
- 220 existing tests still pass

---

---

## Part B: CORS Hardening

### B.1 Finding: 2.2 — CORS Wide Open [HIGH]

**Effort**: S
**Affects model layer**: No

**Specification**:

#### Current State

`backend/api_server.py:18` — `CORS(app)` with no parameters. Allows ANY origin to make cross-origin requests to ANY endpoint including POST/DELETE.

#### Required Change

1. **Replace `CORS(app)` with explicit allowlist**:
   ```python
   CORS(
       app,
       origins=[
           "https://tradingai.in",
           "https://www.tradingai.in",
           "http://localhost:3000",
           "http://localhost:8080",
           "http://127.0.0.1:3000",
           "http://127.0.0.1:8080",
       ],
       methods=["GET", "POST", "OPTIONS"],
       allow_headers=["Content-Type", "Authorization"],
       supports_credentials=True,
   )
   ```

2. **Environment-based configuration**:
   ```python
   import os

   ALLOWED_ORIGINS = os.environ.get(
       "TRADINGAI_CORS_ORIGINS",
       "https://tradingai.in,https://www.tradingai.in,http://localhost:3000,http://localhost:8080",
   ).split(",")

   CORS(
       app,
       origins=ALLOWED_ORIGINS,
       methods=["GET", "POST", "OPTIONS"],
       allow_headers=["Content-Type", "Authorization"],
       supports_credentials=True,
   )
   ```

3. **Development vs Production**:
   - Development: `TRADINGAI_CORS_ORIGINS=http://localhost:3000,http://localhost:8080`
   - Production: `TRADINGAI_CORS_ORIGINS=https://tradingai.in,https://www.tradingai.in`

#### Tests

| Test | Description |
|---|---|
| `test_cors_allowed_origin` | Request from allowed origin → 200 with CORS headers |
| `test_cors_rejected_origin` | Request from unknown origin → 403 on OPTIONS preflight |
| `test_cors_post_allowed` | POST from allowed origin → succeeds |
| `test_cors_post_rejected` | POST from unknown origin → 403 |
| `test_cors_options_preflight` | OPTIONS request returns appropriate headers |

#### Acceptance Criteria

- CORS configured with explicit allowlist
- OPTIONS preflight returns 403 for unauthorized origins
- Allowed origins function correctly
- Development origins (localhost) remain functional
- 220 existing tests still pass
- No model layer changes
- No successful response changes

---

## Part C: Input Validation

### C.1 Finding: 8.2 — No Input Validation on Portfolio POST [HIGH]

**Effort**: S
**Affects model layer**: No

**Specification**:

#### Current State

`backend/api_server.py:962-982` — `portfolio_add` takes payload fields without validation:
- `symbol` — not checked against known symbols
- `entry_price` — can be negative, zero, or non-numeric
- `quantity` — can be negative, zero, or non-integer
- `direction` — defaults to LONG but accepts ANY value other than SHORT
- `entry_date` — not validated as ISO date

#### Required Validation Rules

| Field | Rule | Error Code | Error Message |
|---|---|---|---|
| symbol | Must be in `config/instruments.json` | INVALID_SYMBOL | Symbol is not tracked |
| entry_price | Must be positive float > 0 | INVALID_PRICE | Entry price must be positive |
| quantity | Must be positive integer >= 1 | INVALID_QUANTITY | Quantity must be a positive integer |
| direction | Must be "LONG" or "SHORT" | INVALID_DIRECTION | Direction must be LONG or SHORT |
| entry_date | Valid ISO date (YYYY-MM-DD) | INVALID_DATE | Invalid date format |
| strategy | Non-empty string | INVALID_STRATEGY | Strategy required |

#### Implementation

1. **Create validation utility** in `backend/api_server.py`:
   ```python
   from backend.db_schema import DB_PATH
   import json

   def load_instruments():
       config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config", "instruments.json")
       with open(config_path) as f:
           config = json.load(f)
       all_symbols = set()
       for inst in config["indices"] + config["stocks"]:
           all_symbols.add(inst["symbol"])
       return all_symbols

   _VALID_SYMBOLS = None

   def get_valid_symbols():
       global _VALID_SYMBOLS
       if _VALID_SYMBOLS is None:
           _VALID_SYMBOLS = load_instruments()
       return _VALID_SYMBOLS

   def validate_portfolio_payload(body):
       errors = {}
       symbol = (body.get("symbol") or "").strip().upper()
       if symbol not in get_valid_symbols():
           errors["symbol"] = "Symbol is not tracked"
       entry_price = body.get("entry_price")
       try:
           if entry_price is None or float(entry_price) <= 0:
               errors["entry_price"] = "Entry price must be positive"
       except (TypeError, ValueError):
           errors["entry_price"] = "Entry price must be a number"
       quantity = body.get("quantity")
       try:
           if quantity is None or int(quantity) < 1 or float(quantity) != int(quantity):
               errors["quantity"] = "Quantity must be a positive integer"
       except (TypeError, ValueError):
           errors["quantity"] = "Quantity must be an integer"
       direction = (body.get("direction") or "LONG").upper()
       if direction not in ("LONG", "SHORT"):
           errors["direction"] = "Direction must be LONG or SHORT"
       entry_date = body.get("entry_date")
       if entry_date:
           try:
               datetime.strptime(str(entry_date), "%Y-%m-%d")
           except ValueError:
               errors["entry_date"] = "Invalid date format (YYYY-MM-DD)"
       strategy = body.get("strategy")
       if not strategy or not str(strategy).strip():
           errors["strategy"] = "Strategy required"
       return errors
   ```

2. **Apply to portfolio_add**:
   ```python
   @app.route("/api/portfolio", methods=["POST"])
   def portfolio_add():
       body = request.get_json(silent=True) or {}
       errors = validate_portfolio_payload(body)
       if errors:
           return error_response("INVALID_REQUEST", json.dumps(errors), 400)
       # ... existing logic unchanged ...
   ```

3. **Apply to other endpoints that accept user input**:
   - `/api/<symbol>` — symbol parameter validated (already returns 404 for unknown)
   - `/api/portfolio/<id>` — id parameter validated as integer
   - `/api/backtest` — days parameter validated as positive integer, bounded (1-3650)
   - `/api/options/<symbol>` — symbol validated against known symbols

#### Tests

| Test | Description |
|---|---|
| `test_portfolio_post_valid` | Valid portfolio POST succeeds |
| `test_portfolio_post_invalid_symbol` | Unknown symbol → 400 with INVALID_SYMBOL |
| `test_portfolio_post_negative_price` | Negative entry_price → 400 with INVALID_PRICE |
| `test_portfolio_post_zero_quantity` | Zero quantity → 400 with INVALID_QUANTITY |
| `test_portfolio_post_invalid_direction` | Direction=BUY → 400 with INVALID_DIRECTION |
| `test_portfolio_post_bad_date` | Invalid date format → 400 with INVALID_DATE |
| `test_portfolio_post_missing_strategy` | Missing strategy → 400 with INVALID_STRATEGY |
| `test_portfolio_post_multiple_errors` | Multiple invalid fields → 400 listing all errors |
| `test_backtest_days_validation` | Negative/zero days → 400 |
| `test_valid_requests_unchanged` | All valid requests produce identical responses |

#### Acceptance Criteria

- All portfolio POST fields validated
- Invalid requests return 400 with specific error messages per field
- Valid requests produce identical responses (no behavioral change)
- Validation is config-driven (symbols from instruments.json)
- 220 existing tests still pass
- No model layer changes

---

## Part D: Authentication Boundary Assessment

### D.1 Finding: 2.3 — No Authentication on Any Endpoint [HIGH]
### D.2 Finding: 8.1 — No Authentication on Portfolio Endpoints [HIGH]

**Effort**: L (assessment only in 6B-2; implementation deferred)
**Affects model layer**: No

**Specification**:

#### Assessment Requirement

6B-2 will DOCUMENT and DEFINE the authentication boundary. Implementation may be deferred to 6B-2 or later pending review.

#### Endpoint Classification

All 55 endpoints classified into three categories:

| Category | Definition | Endpoints |
|---|---|---|
| **Public** | No authentication needed. Accessible to any client. | All market data endpoints: `/api/price`, `/api/prices`, `/api/symbols`, `/api/vix*`, `/api/indicators*`, `/api/market`, `/api/global`, `/api/market-outlook*`, `/api/history*`, `/api/breadth*`, `/api/snapshot*`, `/api/regime*`, `/api/strategy*`, `/api/strategies*`, `/api/scenarios*`, `/api/outlook*`, `/api/options*`, `/api/pcr`, `/api/maxpain`, `/api/pcr-history`, `/api/oi-top`, `/api/oi-concentration`, `/api/expected-move`, `/api/options-intelligence`, `/api/etf*`, `/api/fundamentals*`, `/api/data_status`, `/api/health` |
| **Private** | Require authentication. Associated with specific users. | `/api/portfolio` (GET), `/api/portfolio` (POST), `/api/portfolio/<id>` (DELETE), `/api/alerts`, `/api/chat/messages` (POST), `/api/chat/alerts` |
| **Admin** | Require admin privileges. Infrastructure operations. | None currently |

#### Key Principle

> TradingAI.in has public market-intelligence APIs. Market data must remain public. Authentication applies ONLY to user-specific data (portfolio, alerts, chat).

#### What 6B-2 Specifies (Not Necessarily Implements)

1. **Boundary documentation**: All 55 endpoints classified with rationale
2. **Auth method recommendation**: API key, session token, or JWT — specify recommended approach
3. **Portfolio isolation**: Define user-isolation rules (one user's portfolio only visible to that user)
4. **Implementation scope**: Specify whether auth is implemented in 6B-2 or deferred to 6B-3/6B-5
5. **Public site compatibility**: Auth must NOT break AdSense/public-site traffic on public endpoints

#### Tests

| Test | Description |
|---|---|
| `test_all_endpoints_classified` | All 55 endpoints have category assignment |
| `test_public_endpoints_accessible` | All public endpoints accessible without auth |
| `test_portfolio_unauthenticated_rejection` | Portfolio endpoint without auth → 401 |
| `test_market_data_no_auth_needed` | Market data endpoints work without auth |

#### Acceptance Criteria

- All 55 endpoints classified (Public/Private/Admin)
- Classification documented with rationale per endpoint
- Public market data endpoints confirmed as remaining unauthenticated
- Portfolio endpoints identified as requiring authentication
- No premature authentication of public endpoints
- 220 existing tests still pass

---

## Part E: 429 Error Compatibility with 6B-1 Retry

### E.1 Finding: Bounded retry must not retry 429

**Effort**: S
**Affects model layer**: No

**Specification**:

The 6B-1 retry decorator (`backend/retry.py`) must treat 429 as a terminal error, NOT a transient error:

```python
# In retry.py, add 429 to non-retryable detection
NON_RETRYABLE_HTTP_CODES = {400, 401, 403, 404, 429, 500}

def is_retryable_http(status_code):
    return status_code not in NON_RETRYABLE_HTTP_CODES and status_code >= 500
```

Or in the retry decorator, check for HTTP 429 explicitly and do not retry:
```python
if response is not None and getattr(response, 'status_code', 500) == 429:
    raise NonRetryableError("Rate limited — do not retry")
```

**Rationale**: A 429 from our own API means we've hit our own rate limit. Retrying will just hit it again. The rate-limit window must clear first.

**Tests**:

| Test | Description |
|---|---|
| `test_429_not_retried` | 429 response immediately raises, no retries |
| `test_500_retried` | 500 response is retried per backoff policy |

---

## Part F: Test Plan Summary

All new tests organized by area:

### Rate Limiting Tests (7)
1. Rate limit enforcement (429 after limit)
2. Rate limit recovery (window clears)
3. Health endpoint exempt
4. Different categories have different limits
5. Per-IP limits independent
6. 429 includes Retry-After header
7. 429 not retried by retry decorator

### Request Size Tests (2)
1. Request >1MB → 413
2. Valid requests ≤1MB succeed

### Request Timeout Tests (3)
1. Data endpoint slow → 504 after 5s
2. Health endpoint slow → 504 after 2s
3. Backtest slow → 504 after 60s

### CORS Tests (5)
1. Allowed origin succeeds
2. Rejected origin fails
3. POST from allowed origin succeeds
4. POST from rejected origin fails
5. OPTIONS preflight correct

### Input Validation Tests (12+)
1. Valid portfolio POST succeeds
2. Invalid symbol rejected
3. Negative price rejected
4. Zero quantity rejected
5. Invalid direction rejected
6. Bad date rejected
7. Missing strategy rejected
8. Multiple errors listed
9. Backtest days validation
10. Valid requests unchanged
11. Boundary values tested
12. Missing required parameters tested

### Auth Boundary Tests (4)
1. All endpoints classified
2. Public endpoints accessible without auth
3. Portfolio rejects unauthenticated
4. Market data works without auth

### Regression Tests
- All 220 existing tests remain green

### Model Layer Verification
- Zero changes to: regime.py, strategies.py, outlook.py, scenarios.py, options.py, ai_outlook.py, backtest.py, indicators.py

**Total new tests**: ~35

---

## Part G: Implementation Sequence

| Order | Item | Effort | Dependencies |
|---|---|---|---|
| 1 | Rate limiting infrastructure | M | None |
| 2 | CORS hardening | S | None |
| 3 | Input validation | S | None |
| 4 | 429 non-retry compatibility | S | Rate limiting |
| 5 | Auth boundary documentation | L | None (documentation only) |
| 6 | Auth boundary tests | M | Item 5 |
| 7 | Regression test | — | All above |

---

## Part H: Acceptance Summary

| # | Finding | Severity | Acceptance |
|---|---|---|---|
| A | 2.1 Zero rate limiting | Critical | All 55 endpoints have rate limits |
| A | 2.4 No request size limits | Medium | MAX_CONTENT_LENGTH set |
| A | 2.5 No request timeout | Medium | Per-endpoint timeouts configured |
| B | 2.2 CORS wide open | High | CORS restricted to allowlist |
| C | 8.2 No input validation | High | Portfolio POST validated |
| D | 2.3 No authentication | High | All endpoints classified |
| D | 8.1 No portfolio auth | High | Portfolio boundary defined |

**7 finding areas addressed. 0 model layer changes. 220/220 regression required.**

---

## Part I: Post-Implementation Verification

After implementation:

1. **Run 220/220 regression** — must pass
2. **Run all new 6B-2 tests** — must pass
3. **Verify model layer untouched** — `git diff 63ab095 HEAD --name-only` shows no model files
4. **Verify successful responses unchanged** — compare 200 responses before/after for all endpoints
5. **Verify rate limiting works** — test 429 enforcement and recovery
6. **Verify CORS** — test allowed/rejected origins
7. **Verify input validation** — test valid/invalid inputs
8. **Commit and freeze** — 6B-2 commit, then freeze before 6B-3

---

*End of PHASE 6B-2 Specification. Awaiting independent review before implementation.*
