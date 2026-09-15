# PHASE 6B-3 Phase A Specification

**Monitoring & Observability Foundation**

**Status**: SCOPE APPROVED → AWAITING SPECIFICATION REVIEW

**Frozen baselines**: `45f90fc` (analytical) → `51c02f9` (6A) → `63ab095` (6B-1) → `8bbd4d7` (6B-2, FROZEN)

**Audit findings**: 3.1, 3.2, 3.3, 3.4, 3.5, 3.10, 5.1, 5.2, 5.3, 5.4, 6.3 (interface)

---

## Design Principles

1. **Monitoring observes, never influences**: No monitoring signal changes trading decisions, regime selection, strategy fallback, or confidence calculations
2. **In-memory only**: Consistent with 6B-2 rate limiter (single-instance). Production requires Redis/Prometheus. Limitation documented.
3. **No model layer changes**: Zero modifications to regime.py, strategies.py, indicators.py, options.py, outlook.py, scenarios.py, ai_outlook.py, backtest.py
4. **No successful response changes**: All existing API responses remain identical
5. **Clean observability interface**: JSON-structured metrics/alerts that can feed Prometheus/Grafana later
6. **No sensitive data in logs**: Never log user data, tokens, portfolio contents, or PII
7. **Low-cardinality metrics**: Group by endpoint, status code, error code — not by user, symbol, or request-specific values
8. **Configurable thresholds**: Alert thresholds are configuration values, not hardcoded

---

## Part A — Latency Tracking

### A.1 Request Duration Middleware

**File**: `backend/api_server.py` (new: `@app.before_request` and `@app.after_request` decorators)

**Mechanism**:
- `@app.before_request`: Record `request.start_time = time.monotonic()` in `g`
- `@app.after_request`: Calculate `duration_ms = (time.monotonic() - g.start_time) * 1000`
- Store in metrics system (A.3)

**Dimensions**:
- Endpoint name (e.g., `price`, `vix`, `backtest`)
- Duration in milliseconds (float)
- Success/failure category (success = 2xx, error = 4xx/5xx)

**Constraints**:
- Zero overhead on request path (< 1ms per request)
- Thread-safe (gunicorn workers are separate processes; each worker has own metrics)
- No impact on response payload

### A.2 Per-Endpoint Latency History

**Storage**: In-memory circular buffer per endpoint (last 1000 samples)

**Data**:
```python
{
    "endpoint_name": {
        "durations": [12.3, 8.1, 15.2, ...],  # last 1000 samples
        "count": 4523,
        "error_count": 12,
    }
}
```

**Access**: Via metrics endpoint (A.4) and structured log entries

### A.3 Latency Metrics Storage

**File**: `backend/monitoring.py` (NEW module)

**Class**: `RequestMonitor`

```python
class RequestMonitor:
    """In-memory request monitoring. Thread-safe per worker process."""
    
    def record_request(self, endpoint: str, duration_ms: float, status_code: int, error_code: str | None) -> None:
        """Record a request with timing and outcome."""
        pass
    
    def get_latency(self, endpoint: str, window: int = 1000) -> dict:
        """Return avg/min/max/p95 latency for endpoint over last N samples."""
        pass
    
    def get_summary(self) -> dict:
        """Return summary across all endpoints."""
        pass
```

**Thread safety**: Use `threading.Lock()` per endpoint data structure

---

## Part B — API Failure Counters

### B.1 Failure Counter

**File**: `backend/monitoring.py` (extends RequestMonitor)

**Method**:
```python
def record_failure(self, endpoint: str, status_code: int, error_code: str) -> None:
    """Record a failure with dimensions."""
    pass
```

**Dimensions** (low cardinality):
- Endpoint name (from route pattern, not actual values)
- HTTP status code (4xx, 5xx categories)
- Error code (from standardized error_response codes)

**NOT tracked** (high cardinality):
- User ID, email, or account
- Symbol/ticker values
- Request parameters
- IP addresses

### B.2 Counter Storage

```python
{
    "endpoint_name": {
        "total_requests": 1234,
        "total_errors": 56,
        "by_status": {"4xx": 45, "5xx": 11},
        "by_error_code": {"INVALID_REQUEST": 30, "RATE_LIMITED": 10, "INTERNAL_ERROR": 16},
        "last_error_at": "2026-09-14T03:34:00Z",
    }
}
```

### B.3 External API Failure Counter

**File**: `backend/monitoring.py` (extends RequestMonitor)

**Purpose**: Track external API call failures (yfinance, data sources) for circuit breaker integration

```python
def record_external_failure(self, source: str, error_type: str) -> None:
    """Record external API failure.
    
    source: 'yfinance', 'nse', 'other'
    error_type: 'connection', 'timeout', 'parse', 'other'
    """
    pass
```

---

## Part C — Structured Logging

### C.1 Logging Configuration

**File**: `backend/monitoring.py` (logging setup)
**Configuration**: `backend/logging.yaml` or inline in `app.py`

**Format**: JSON with consistent fields for ALL log entries

```json
{
    "timestamp": "2026-09-14T03:34:16Z",
    "level": "INFO",
    "endpoint": "/api/price/NIFTY",
    "status_code": 200,
    "error_code": null,
    "latency_ms": 12.3,
    "correlation_id": "req-abc123",
    "message": "Request completed"
}
```

### C.2 Correlation ID

**Mechanism**: Generate UUID per request in `@app.before_request`, store in `g`

```python
g.correlation_id = f"req-{uuid.uuid4().hex[:12]}"
```

**Included in**: All structured log entries for that request, response headers (`X-Correlation-ID`)

### C.3 Log Fields (Standard)

Every structured log entry includes:
- `timestamp`: ISO 8601 UTC
- `level`: DEBUG/INFO/WARNING/ERROR/CRITICAL
- `endpoint`: Route pattern (not actual URL with parameters)
- `status_code`: HTTP response status
- `error_code`: From standardized error schema or null
- `latency_ms`: Request duration
- `correlation_id`: Unique request identifier

### C.4 Security Constraints

**NEVER include in logs**:
- User credentials, tokens, passwords
- Portfolio contents, positions, P&L
- Email addresses, phone numbers
- API keys or secrets
- Full request/response payloads

**SAFE to include**:
- Endpoint name and status code
- Error code (not error message details)
- Latency and timing data
- Correlation ID
- Generic user identifiers (not actual user data)

### C.5 Logging Setup

**File**: `backend/monitoring.py`

```python
def setup_logging(log_level: str = "INFO", log_file: str | None = None) -> logging.Logger:
    """Configure structured JSON logging."""
    pass
```

**Output**: stdout (default) and optional log file
**Format**: One JSON object per line (for easy parsing)

---

## Part D — Metrics Endpoint

### D.1 Endpoint Definition

**Route**: `/api/metrics`
**Authentication**: No auth required (internal/operational endpoint)
**Caching**: No cache (real-time data)
**Rate limit**: Exempt from rate limiting

### D.2 Response Format

```json
{
    "timestamp": "2026-09-14T03:34:16Z",
    "uptime_seconds": 86400.5,
    "request_counts": {
        "total": 12345,
        "by_endpoint": {
            "price": {"total": 5000, "errors": 23, "avg_latency_ms": 8.1, "p95_latency_ms": 45.2},
            "vix": {"total": 1200, "errors": 5, "avg_latency_ms": 12.3, "p95_latency_ms": 89.1}
        }
    },
    "failure_counts": {
        "by_error_code": {
            "INVALID_REQUEST": 1800,
            "RATE_LIMITED": 350,
            "INTERNAL_ERROR": 50
        },
        "by_endpoint": {
            "price": {"4xx": 200, "5xx": 23},
            "vix": {"4xx": 10, "5xx": 5}
        }
    },
    "circuit_breakers": {
        "yfinance": {"state": "CLOSED", "failures": 0, "last_failure": null},
        "nse": {"state": "CLOSED", "failures": 0, "last_failure": null}
    },
    "external_api_failures": {
        "yfinance": {"connection": 0, "timeout": 0, "parse": 0, "other": 0}
    },
    "data_freshness": {
        "NIFTY_price": {"last_updated": "2026-09-14T03:34:00Z", "age_seconds": 16, "stale": false},
        "VIX": {"last_updated": "2026-09-14T03:20:00Z", "age_seconds": 740, "stale": true}
    }
}
```

### D.3 Metrics Available

| Metric | Source | Cardinality |
|--------|--------|-------------|
| Request count | Before/after request hooks | Per endpoint |
| Error count | Error response handler | Per endpoint + error code |
| Latency (avg/min/max/p95) | Timing middleware | Per endpoint |
| Circuit breaker state | circuit_breaker.py | Per external source |
| External API failures | Monitoring | Per source + error type |
| Data freshness | Health check data | Per data symbol |

---

## Part E — Alerts

### E.1 Alert Configuration

**File**: `backend/monitoring.py` (alert rules)

**Format**: Configurable thresholds in a dict or config file

```python
ALERT_RULES = {
    "sustained_api_failures": {
        "threshold": 10,       # errors per minute
        "window_seconds": 60,
        "severity": "WARNING",
    },
    "stale_data": {
        "max_age_seconds": 3600,  # 1 hour
        "severity": "WARNING",
    },
    "circuit_breaker_open": {
        "severity": "CRITICAL",
    },
    "abnormal_latency": {
        "p95_threshold_ms": 5000,
        "window_seconds": 300,
        "severity": "WARNING",
    },
}
```

### E.2 Alert Conditions

1. **Sustained API failures**: > 10 errors (4xx/5xx) from same endpoint within 60 seconds
2. **Stale data**: Any tracked data source older than configured max age
3. **Circuit breaker open**: Any circuit breaker transitions to OPEN state
4. **Abnormal latency**: p95 latency > 5000ms over 5-minute window

### E.3 Alert Output

**Primary**: Structured log entries at WARNING/CRITICAL level
```json
{
    "timestamp": "...",
    "level": "WARNING",
    "alert_type": "sustained_api_failures",
    "endpoint": "/api/price",
    "threshold": 10,
    "actual": 15,
    "window_seconds": 60,
    "message": "Sustained API failures detected"
}
```

**Constraints**:
- No external alerting platform required (Phase A)
- Alerts logged, not sent (Phase A)
- Avoid one-off alerts (alerts trigger on sustained conditions, not single events)
- Configurable thresholds (no hardcoded values)

### E.4 Alert Deduplication

**Mechanism**: Track last-alert timestamp per rule, minimum 5-minute interval between same alerts

```python
last_alerted = {
    "sustained_api_failures:/api/price": "2026-09-14T03:30:00Z",
    ...
}
```

---

## Part F — Implementation Plan

### Files to Create

| File | Purpose |
|------|---------|
| `backend/monitoring.py` | Core monitoring module (RequestMonitor, alert rules, metrics) |
| `backend/logging_config.py` | Structured logging setup |
| `tests/test_phase6b_3_pea.py` | Phase A tests (estimated 25-35 tests) |

### Files to Modify

| File | Change |
|------|--------|
| `backend/api_server.py` | Request timing middleware, correlation ID, metrics recording, metrics endpoint |
| `backend/api_server.py` (error handlers) | Include error_code in structured logs |
| `ops/requirements.txt` | No new dependencies (pure Python) |

### Implementation Sequence

1. Create `backend/monitoring.py` (RequestMonitor, alert rules)
2. Create `backend/logging_config.py` (structured logging)
3. Update `backend/api_server.py`:
   - Add `@app.before_request`: start timer + correlation ID
   - Add `@app.after_request`: record metrics + structured log
   - Add metrics endpoint (`/api/metrics`)
   - Update error_response to include correlation ID and log structured entry
4. Create tests
5. Run regression (261 existing + new tests)
6. Model boundary verification (8/8 untouched)

### Dependencies on 6B-1/6B-2

| 6B-1/6B-2 Component | Used By | Integration |
|---|---|---|
| CircuitBreaker class | Metrics (D.2) | Expose state in metrics endpoint |
| error_response() | Structured logging (C) | Include error_code in log entry |
| Standardized error codes | Failure counters (B) | Use as counter dimensions |
| Rate limiter | Metrics (D.2) | Track rate-limit events |

---

## Part G — Test Plan

### Test Categories

| Category | Tests | Verification |
|----------|-------|-------------|
| Latency tracking | ~8 | Timer records, avg/min/max/p95 calculation, per-endpoint isolation |
| Failure counters | ~6 | Counts by endpoint/status/error code, no high-cardinality leakage |
| Structured logging | ~8 | JSON format, required fields, correlation ID, no sensitive data |
| Metrics endpoint | ~6 | Response format, data accuracy, exemption from rate limiting |
| Alert rules | ~6 | Threshold triggering, deduplication, no one-off alerts |
| Regression | 261 | All existing tests still pass |
| Model boundary | 8 | All model files untouched |

### Test File: `tests/test_phase6b_3_pea.py`

**Structure**:
- TestLatencyTracking: Timer accuracy, per-endpoint isolation, error/success categorization
- TestFailureCounters: Counter dimensions, low-cardinality enforcement, failure recording
- TestStructuredLogging: JSON format, required fields, correlation ID, security
- TestMetricsEndpoint: Response format, data accuracy, exemption
- TestAlertRules: Threshold triggering, deduplication, severity levels
- TestRegressionGate: 261 existing tests pass
- TestModelIsolation: 8 model files unchanged

---

## Part H — Boundaries

### What Phase A Does
- ✅ Observe and record system behavior
- ✅ Expose operational metrics
- ✅ Log structured events
- ✅ Trigger alerts based on thresholds
- ✅ Expose circuit breaker state
- ✅ Track data freshness

### What Phase A Does NOT Do
- ❌ Change any trading decision
- ❌ Modify regime/strategy selection
- ❌ Alter confidence calculations
- ❌ Implement automatic fallback based on monitoring
- ❌ Change any API response payload (successful or error)
- ❌ Add authentication or security controls
- ❌ Introduce multi-instance capability
- ❌ Connect to external monitoring platforms (Prometheus/Grafana)
- ❌ Implement Phase B (remaining audit findings)
- ❌ Touch analytical features

---

## Part I — Acceptance Criteria

| Criteria | Target |
|----------|--------|
| Tests passing | 261 + ~35 new = ~296 total |
| Model files modified | 0/8 |
| Successful API responses | Identical to before |
| Error API responses | Identical format to before |
| Latency overhead per request | < 1ms |
| Metrics endpoint | Returns valid JSON with all metrics |
| Structured logs | Valid JSON with required fields |
| No sensitive data in logs | Verified by test |
| Alerts trigger on thresholds | Verified by test |
| No one-off alerts | Verified by test |
| Correlation ID on all logs | Verified by test |
| Circuit breaker state exposed | Verified via metrics endpoint |

---

## Part J — Out of Scope

These items are NOT authorized in Phase A:
- 6.3 No External API Health Tracking (Phase A builds interface, full implementation later)
- 9.4 Database Failure Recovery (separate scope)
- All Phase B infrastructure findings
- All analytical features (confidence calibration, data population, historical extension, predictive integrity)

---

*Specification complete. Awaiting independent specification review before implementation authorization.*
