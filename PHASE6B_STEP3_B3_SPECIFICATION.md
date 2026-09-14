# PHASE 6B-3 B.3 — Implementation Specification: Failure Recovery

**Scope**: Failure Recovery & Graceful Degradation
**Status**: SPECIFICATION — AWAITING INDEPENDENT REVIEW
**Frozen baselines**: `45f90fc` (analytical/model), `51c02f9` (PHASE 6A), `63ab095` (PHASE 6B-1), `8bbd4d7` (PHASE 6B-2), `c39af34` (6B-3 Phase A), `3ec9473` (B.1), `cdf0f6a` (B.2)
**Regression baseline**: 350/350 passing

---

## Part 0: Implementation Boundaries

### Must NOT Change

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
- ❌ All 350 existing tests must remain green
- ❌ Model layer files: regime.py, strategies.py, outlook.py, scenarios.py, options.py, ai_outlook.py, backtest.py, indicators.py

### Must Add

- ✅ Graceful degradation protocol (DATA UNAVAILABLE / STALE / PARTIAL states)
- ✅ Failure state transitions for every scenario
- ✅ Recovery verification
- ✅ User-visible state communication (data_quality, data_freshness, data_completeness)
- ✅ DB error handling (503, not 500)
- ✅ Health/readiness endpoints
- ✅ Failure observability (error counts, pipeline status)
- ✅ Operational recovery (rollback, graceful restart)

### State Transition Protocol (Mandatory)

Every failure scenario must define:

```
Normal → Failure → User-visible state → Recovery → Normal
```

**Five defined states**:

| State | Code | Meaning |
|---|---|---|
| `LIVE DATA` | `data_quality: "LIVE"` | All expected data sources available, fresh |
| `STALE DATA` | `data_quality: "STALE"` | Cached data available, source unavailable or aged |
| `DATA UNAVAILABLE` | `data_quality: "DATA UNAVAILABLE"` | No data available (no cache, source down) |
| `PARTIAL DATA` | `data_completeness: {total, available, missing}` | Some sources available, others not |
| `SYSTEM DEGRADED` | `status: "degraded"` in /api/health | API functioning, multiple sources down |

### State Transition Examples

#### Example 1: Single Data Source Failure

```
LIVE DATA
  ↓ provider failure
DATA UNAVAILABLE (or STALE if cache exists)
  ↓ No regime/strategy/confidence generated from missing data
  ↓ No analytical behavior change
  ↓ provider recovers
fresh data verified
  ↓
LIVE DATA
```

#### Example 2: Data Stale but API Running

```
LIVE DATA
  ↓ data source not refreshed (cron missed, network delay)
STALE DATA (data_freshness: {age_minutes: 45, stale: true, last_fetch: "2026-09-14T03:45:00Z"})
  ↓ API available ≠ market intelligence valid
  ↓ User sees "Data is 45 minutes old"
  ↓ cron retry succeeds
fresh data verified
  ↓
LIVE DATA
```

#### Example 3: Database Failure

```
API OK
  ↓ DB lock or corruption
DB UNAVAILABLE → HTTP 503 {"error": {"code": "SERVICE_DEGRADED", "message": "Database temporarily unavailable", "data_quality": "UNAVAILABLE"}}
  ↓ No fabricated data
  ↓ No incomplete analytical results
  ↓ self-heal restores from backup
DB verified (integrity check + row count match)
  ↓
API OK
```

#### Example 4: External API Cascade Failure

```
LIVE DATA (all sources)
  ↓ yfinance failure
PARTIAL DATA (data_completeness: {total: 8, available: 5, missing: ["price", "indicators", "regime"]})
  ↓ No regime/strategy/confidence for missing sources
  ↓ Cache serves last-known for available sources
  ↓ yfinance recovers
all sources verified
  ↓
LIVE DATA (all sources)
```

---

## Part A: Graceful Degradation

### A.1 Finding: 9.1 — No Graceful Degradation for Market-Data Outage [HIGH]

**Effort**: M
**Affects model layer**: No

#### Current State

When price data is unavailable, endpoints return 404 or empty arrays with no indication of data staleness or alternative data availability. No cached fallback exists.

#### Required Behavior

| Condition | Response | Data Quality |
|---|---|---|
| Fresh data available | Normal response | `data_quality: "LIVE"` |
| Source empty, cache exists | Last known data served | `data_quality: "STALE"`, `data_freshness: {age, stale: true, last_fetch}` |
| Source empty, no cache | Empty with explicit message | `data_quality: "DATA UNAVAILABLE"` |
| Partial sources available | Available data with missing list | `data_completeness: {total, available, missing: [...]}` |

#### Implementation

1. **Define data quality constants** in `backend/data_quality.py`:

```python
DATA_QUALITY_LIVE = "LIVE"
DATA_QUALITY_STALE = "STALE"
DATA_QUALITY_UNAVAILABLE = "DATA UNAVAILABLE"
DATA_QUALITY_PARTIAL = "PARTIAL"

CACHE_TTL_BY_SOURCE = {
    "price_1m": 300,       # 5 minutes
    "price_1d": 3600,      # 1 hour
    "vix": 3600,           # 1 hour
    "options": 600,        # 10 minutes
    "outlook": 86400,      # 1 day
    "regime": 86400,       # 1 day
    "strategy": 86400,     # 1 day
}
```

2. **Add response enrichment decorator** in `backend/api_server.py`:

```python
from datetime import datetime, timezone
from data_quality import (
    DATA_QUALITY_LIVE, DATA_QUALITY_STALE,
    DATA_QUALITY_UNAVAILABLE, DATA_QUALITY_PARTIAL,
    CACHE_TTL_BY_SOURCE,
)

def _data_age_minutes(timestamp):
    if not timestamp:
        return None
    if isinstance(timestamp, str):
        ts = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    else:
        ts = timestamp
    now = datetime.now(timezone.utc)
    return (now - ts).total_seconds() / 60

def _enforce_data_quality(endpoint_name):
    """Decorator that adds data_quality metadata to responses."""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            result = func(*args, **kwargs)
            # Only modify dict/list responses, not Flask Response objects
            if isinstance(result, (dict, list)):
                pass  # enrichment happens inside endpoint logic
            return result
        return wrapper
    return decorator
```

3. **Apply to data endpoints**: Each data endpoint checks its data source freshness and adds `data_quality` to response. The exact mechanism depends on endpoint structure — use helper function:

```python
def _enrich_with_freshness(response, source_tables, conn):
    """Add data_quality metadata to a response dict."""
    if not isinstance(response, dict):
        return response

    ages = []
    for table in source_tables:
        row = conn.execute(
            "SELECT MAX(timestamp) as ts FROM {table}".format(table=table)
        ).fetchone()
        if row and row["ts"]:
            age = _data_age_minutes(row["ts"])
            if age is not None:
                ages.append(age)

    if not ages:
        response["data_quality"] = DATA_QUALITY_UNAVAILABLE
        response["data_freshness"] = {"age_minutes": None, "stale": True}
    elif max(ages) > 30:
        response["data_quality"] = DATA_QUALITY_STALE
        response["data_freshness"] = {
            "age_minutes": round(max(ages)),
            "stale": True,
            "threshold_minutes": 30,
        }
    else:
        response["data_quality"] = DATA_QUALITY_LIVE
        response["data_freshness"] = {
            "age_minutes": round(max(ages)) if ages else None,
            "stale": False,
        }
    return response
```

4. **Critical rule**: `_enrich_with_freshness` NEVER generates new data. It only adds metadata about existing data. No analytical values are modified, created, or inferred.

#### Tests

| Test | Description |
|---|---|
| `test_fresh_data_live` | Fresh data → `data_quality: "LIVE"` |
| `test_stale_data_stale` | Aged data → `data_quality: "STALE"`, age reported |
| `test_no_data_unavailable` | No data → `data_quality: "DATA UNAVAILABLE"` |
| `test_partial_data_completeness` | Partial sources → `data_completeness` with missing list |
| `test_no_manufactured_values` | When unavailable, no new analytical values generated |
| `test_all_endpoints_has_quality` | Every data endpoint includes quality indicator |

#### Acceptance Criteria

- All data endpoints include `data_quality` or `data_completeness`
- STALE data clearly labeled with age
- DATA UNAVAILABLE clearly communicated
- No analytical values fabricated from missing data
- 350 existing tests still pass
- No model layer changes

---

## Part B: Failure Isolation

### B.1 Finding: 6.5 — VIX Data Source Failure Not Isolated [MEDIUM]

**Effort**: M
**Affects model layer**: No

#### Current State

VIX data from `vix_data` table is used in `/api/vix`, `/api/vix/history`, `/api/vix/daily`, `/api/global`, and in `backtest.py` (VIX-based strategies). If VIX data fetch fails, multiple endpoints and backtests are affected. No isolation.

#### Required Behavior

| Condition | Endpoint Behavior |
|---|---|
| VIX data fresh | Normal response |
| VIX data stale (>60 min) | Response with `data_quality: "STALE"`, VIX-specific warning |
| VIX data unavailable | VIX endpoints return `data_quality: "DATA UNAVAILABLE"`; non-VIX endpoints unaffected |
| VIX fetch fails | Alert triggers; non-VIX endpoints continue normally |

#### Implementation

1. **VIX-specific freshness check** — add to `/api/vix` and `/api/global`:

```python
def _check_vix_freshness(conn):
    row = conn.execute("SELECT MAX(timestamp) as ts FROM vix_data").fetchone()
    if not row or not row["ts"]:
        return DATA_QUALITY_UNAVAILABLE, None
    age = _data_age_minutes(row["ts"])
    if age > 60:
        return DATA_QUALITY_STALE, {"age_minutes": round(age), "threshold": 60}
    return DATA_QUALITY_LIVE, {"age_minutes": round(age)}
```

2. **Non-VIX endpoints must not fail due to VIX** — verify `/api/price`, `/api/market`, `/api/options*` do not depend on `vix_data` table. If they do, decouple them.

3. **VIX failure alert** — add to monitoring: VIX fetch failure triggers alert via existing monitoring infrastructure (6B-3 Phase A RequestMonitor).

#### Tests

| Test | Description |
|---|---|
| `test_vix_stale_flagged` | VIX data >60min → STALE |
| `test_vix_unavailable_does_not_affect_price` | VIX failure → price endpoint still works |
| `test_vix_unavailable_does_not_affect_market` | VIX failure → market overview still works |
| `test_vix_failure_alerted` | VIX fetch failure triggers alert |

---

### B.2 Finding: 6.6 — Options Data Source Failure Not Isolated [MEDIUM]

**Effort**: M
**Affects model layer**: No

#### Current State

Options endpoints all depend on `option_chain` and `option_expiries` tables. If options data fetch fails, all options endpoints return empty or null. `/api/options-intelligence` reports `data_quality: "LIVE"` even with 0 rows (misleading).

#### Required Behavior

| Condition | Endpoint Behavior |
|---|---|
| Options data fresh | Normal response with `data_quality: "LIVE"` |
| Options data stale (>1 hour) | Response with `data_quality: "STALE"` |
| Options data unavailable (0 rows) | `data_quality: "DATA UNAVAILABLE"`, explicit message |
| Single options endpoint failure | Other options endpoints continue; non-options unaffected |

#### Implementation

1. **Fix `data_quality` logic in options_intelligence** — change from always "LIVE" to actual data presence check:

```python
def _options_data_quality(conn):
    chain_count = conn.execute("SELECT COUNT(*) as c FROM option_chain").fetchone()["c"]
    expiry_count = conn.execute("SELECT COUNT(*) as c FROM option_expiries").fetchone()["c"]
    if chain_count == 0 and expiry_count == 0:
        return DATA_QUALITY_UNAVAILABLE
    # Check freshness
    row = conn.execute("SELECT MAX(fetched_at) as ts FROM option_chain").fetchone()
    if row and row["ts"]:
        age = _data_age_minutes(row["ts"])
        if age > 3600:
            return DATA_QUALITY_STALE
    return DATA_QUALITY_LIVE
```

2. **Add explicit messaging** for unavailable options data:

```python
if data_quality == DATA_QUALITY_UNAVAILABLE:
    response["message"] = "Options data unavailable — last fetch was X hours ago"
```

3. **Failure isolation** — verify each options endpoint can fail independently. One endpoint's failure must not cause others to fail.

#### Tests

| Test | Description |
|---|---|
| `test_options_unavailable_labeled` | Empty option_chain → DATA UNAVAILABLE |
| `test_options_quality_accurate` | data_quality reflects actual data presence |
| `test_options_failure_isolated` | One options endpoint failure doesn't affect others |
| `test_non_options_unaffected` | Options failure doesn't affect price/market/strategy |

---

### B.3 Finding: 6.3 — No External API Health Tracking [MEDIUM]

**Effort**: M
**Affects model layer**: No

#### Current State

`data_status` table exists (tracks `last_fetch` per source) but `/api/data_status` only returns raw rows. No success/failure tracking. No error count. No uptime percentage.

#### Required Behavior

| Metric | Source | Purpose |
|---|---|---|
| `success_count` | `data_status` table | Track successful fetches |
| `error_count` | `data_status` table | Track failed fetches |
| `last_error` | `data_status` table | Last error message |
| `uptime_pct` | Calculated from success/(success+error) | Source health |
| `consecutive_failures` | `data_status` table | Alert trigger |

#### Implementation

1. **Add columns to data_status** via migration:

```sql
ALTER TABLE data_status ADD COLUMN success_count INTEGER DEFAULT 0;
ALTER TABLE data_status ADD COLUMN error_count INTEGER DEFAULT 0;
ALTER TABLE data_status ADD COLUMN last_error TEXT;
ALTER TABLE data_status ADD COLUMN consecutive_failures INTEGER DEFAULT 0;
```

2. **Update fetch logic** — every fetch increments success_count or error_count:

```python
def _record_fetch_result(source, success, error_msg=None):
    conn = get_db()
    if success:
        conn.execute(
            "UPDATE data_status SET success_count = success_count + 1, consecutive_failures = 0 WHERE source = ?",
            (source,)
        )
    else:
        conn.execute(
            "UPDATE data_status SET error_count = error_count + 1, consecutive_failures = consecutive_failures + 1, last_error = ? WHERE source = ?",
            (error_msg, source)
        )
    conn.commit()
    conn.close()
```

3. **Alert on consecutive failures** — in data fetcher loop, after recording failure:

```python
if consecutive_failures >= 3:
    log_alert(f"DATA SOURCE FAILURE: {source} has {consecutive_failures} consecutive failures")
```

#### Tests

| Test | Description |
|---|---|
| `test_success_count_increments` | Successful fetch → success_count +1 |
| `test_error_count_increments` | Failed fetch → error_count +1 |
| `test_consecutive_failure_alert` | 3+ consecutive failures → alert logged |
| `test_pipeline_status_accurate` | /api/data/status shows correct counts |

---

## Part C: Database Recovery

### C.1 Finding: 9.4 — Database Failure Recovery [MEDIUM]

**Effort**: S
**Affects model layer**: No

#### Current State

`ops/self-heal.sh` checks DB integrity and attempts restore from backup. But: recovery is best-effort, no notification on failure, no verification beyond integrity check, no alert on recovery event.

#### Required Behavior

| Condition | System Response | User Response |
|---|---|---|
| DB healthy | Normal operation | Normal |
| DB corruption detected | self-heal restores from backup | API returns 503 during recovery |
| Recovery successful | Integrity + row count verified; alert fired | API returns to normal |
| Recovery failed | Alert on separate channel; 503 for all endpoints | "Service temporarily unavailable" |

#### Implementation

1. **DB connection error handler** in `backend/api_server.py` `get_db()`:

```python
def get_db():
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=10000")
        return conn
    except sqlite3.OperationalError as e:
        app.logger.error(f"DB connection failed: {e}")
        raise  # Let Flask error handler return 503
```

2. **503 error handler for DB failures**:

```python
@app.errorhandler(sqlite3.OperationalError)
def _handle_db_error(e):
    return error_response(
        "SERVICE_DEGRADED",
        "Database temporarily unavailable — please retry shortly",
        503,
    )
```

3. **Recovery verification** — after self-heal DB recovery, verify:
   - Integrity check passes
   - Row count matches expected (compare to backup metadata)
   - Alert fires on any recovery event

4. **Recovery alert**:

```python
# In self-heal.sh, after successful DB restore
echo "DB RECOVERY: {timestamp} rows_restored={count} integrity=ok" >> /opt/tradingai/logs/recovery.log
# And in monitoring, alert on recovery.log changes
```

#### Tests

| Test | Description |
|---|---|
| `test_db_corruption_returns_503` | DB failure → 503 (not 500) |
| `test_db_recovery_verified` | Recovery includes integrity + row count check |
| `test_recovery_alerted` | Recovery event triggers alert |
| `test_readonly_fallback` | If primary DB fails, read-only mode available |

---

### C.2 Finding: 6.7 — Database Failure Not Handled Gracefully [MEDIUM]

**Effort**: M
**Affects model layer**: No

#### Current State

All endpoints call `get_db()` which does `sqlite3.connect(DB_PATH)` with no error handling. If DB file is corrupted or locked, the request throws an unhandled exception → 500 error with stack trace.

#### Required Behavior

All endpoints must:
1. Return 503 (not 500) on DB failure
2. Return user-friendly message (no stack traces)
3. Not expose DB internals in error response

#### Implementation

This is addressed by C.1's error handler. The 503 handler at C.1 covers all DB-related failures across all endpoints.

**Note on 6.7 and 9.4 overlap**: These two findings describe the same problem (DB failure handling) from different perspectives — 6.7 from the data-source angle, 9.4 from the recovery angle. Implementation should be unified: single DB error handler (C.1) that covers both.

#### Tests

Covered by C.1 tests.

---

## Part D: Stale Data Communication

### D.1 Finding: 9.5 — Stale Data Detection [MEDIUM]

**Effort**: M
**Affects model layer**: No

#### Current State

`/api/health` detects stale data (NIFTY > 30 min, VIX > 60 min, outlook > 1 day) and reports `status: "degraded"`. But: no other endpoint tells the user that the data they're viewing is stale.

#### Required Behavior

**Critical rule**: `API available ≠ market intelligence valid`

| Data State | API Status | User-Facing Message |
|---|---|---|
| Fresh | `status: "ok"` | Normal |
| Stale (data aged) | `status: "degraded"` + per-endpoint `data_quality: "STALE"` | "Data is X minutes/hours old" |
| Unavailable | `status: "degraded"` + `data_quality: "DATA UNAVAILABLE"` | "Data unavailable" |

#### Implementation

1. **Add `data_freshness` to ALL data endpoints** — use the `_enrich_with_freshness` helper from Part A for all endpoints that serve data:
   - `/api/price/<symbol>` — freshness from `price_1m`
   - `/api/market` — freshness from `price_1m`, `vix_data`
   - `/api/vix*` — freshness from `vix_data`
   - `/api/options*` — freshness from `option_chain`
   - `/api/<symbol>` — freshness from all contributing sources

2. **Per-endpoint freshness thresholds**:

| Endpoint | Stale After | Unavailable After |
|---|---|---|
| `/api/price/<symbol>` | 5 min | 30 min |
| `/api/vix` | 60 min | 120 min |
| `/api/vix/history` | 120 min | 240 min |
| `/api/options-intelligence` | 1 hour | 4 hours |
| `/api/market` | 20 min | 60 min |
| `/api/strategy/<symbol>` | 1 day | 3 days |
| `/api/outlook/<symbol>` | 1 day | 3 days |

3. **Health endpoint enhancement** — add per-source status:

```python
@app.route("/api/health")
@limiter.exempt
def health():
    # ... existing code ...
    sources = {
        "nifty_price": _check_source_freshness("price_1m", threshold=30),
        "vix": _check_source_freshness("vix_data", threshold=60),
        "outlook": _check_source_freshness("outlook", threshold=1440),
        # ... etc
    }
    # sources = {"nifty_price": {"status": "ok", "age_minutes": 5}, ...}
    # all_stale = all(s["status"] != "ok" for s in sources.values())
    # any_stale = any(s["status"] == "stale" for s in sources.values())
    response["sources"] = sources
    response["overall"] = "ok" if not any_stale else ("degraded" if all_stale else "degraded")
    # ... existing code ...
```

#### Tests

| Test | Description |
|---|---|
| `test_health_reports_source_status` | /api/health includes per-source status |
| `test_stale_flag_in_data_response` | Data responses include stale flag when aged |
| `test_api_available_not_data_valid` | API ok doesn't imply data fresh |
| `test_freshness_thresholds_correct` | Each endpoint uses correct threshold |

---

### D.2 Finding: 6.8 — NSE Live Quote Source Has No Health Check [LOW]

**Effort**: S
**Affects model layer**: No

#### Current State

`_live_quote_row()` checks freshness (25 min max age) but if NSE live source is down, `live_quotes` table is empty, returns None. No alert that live source is down.

#### Required Behavior

- Live quotes staleness monitored separately (stricter than 25 min)
- Alert if live quotes >5 min stale
- `/api/health` includes `live_quotes` status

#### Implementation

1. **Add live quotes check to health endpoint** (covered by D.1)
2. **Alert on >5 min staleness** (covered by B.3 — failure observability)

#### Tests

Covered by D.1 tests.

---

## Part E: Operational Recovery

### E.1 Finding: 9.6 — API Restart Behavior [MEDIUM]

**Effort**: M
**Affects model layer**: No

#### Current State

Systemd has `Restart=always, RestartSec=10`. Self-heal detects unhealthiness and restarts. But: no graceful shutdown (SIGTERM not handled), no in-flight request drain, no startup verification.

#### Required Behavior

| Phase | Behavior |
|---|---|
| **Startup** | Verify health (DB connected, data fresh) before accepting traffic |
| **Normal operation** | Serve requests |
| **Shutdown** | SIGTERM → stop accepting new requests → drain in-flight → exit |
| **Restart** | Log event; self-heal verifies health after restart |

#### Implementation

1. **Startup verification** — Flask `@app.before_first_request` or equivalent:

```python
@app.before_first_request
def _startup_check():
    """Verify API is healthy before accepting traffic."""
    try:
        conn = get_db()
        conn.execute("SELECT 1").fetchone()
        conn.close()
    except Exception as e:
        app.logger.error(f"Startup check failed: {e}")
        raise
```

2. **Graceful shutdown** — SIGTERM handler:

```python
import signal

_shutdown_in_progress = False

def _handle_sigterm(signum, frame):
    global _shutdown_in_progress
    _shutdown_in_progress = True
    app.logger.info("SIGTERM received — graceful shutdown started")

signal.signal(signal.SIGTERM, _handle_sigterm)
```

3. **Post-restart verification** — in self-heal.sh, after restart:

```bash
# Wait for API to be ready
for i in {1..30}; do
    if curl -sf http://127.0.0.1:8000/api/health | grep -q '"status": "ok"'; then
        echo "RESTART OK: API healthy after restart"
        break
    fi
    sleep 1
done
```

#### Tests

| Test | Description |
|---|---|
| `test_startup_verification` | API doesn't accept traffic until healthy |
| `test_sigterm_graceful` | SIGTERM → in-flight requests complete |
| `test_restart_verified` | Self-heal verifies health after restart |

---

### E.2 Finding: 9.7 — No Rollback Strategy [MEDIUM]

**Effort**: S
**Affects model layer**: No

#### Current State

`ops/RESTORE.md` documents full VM rebuild (30+ minutes). No fast rollback. `deploy-vm.sh` has no rollback section.

#### Required Behavior

| Method | Time | Use Case |
|---|---|---|
| Fast rollback (git checkout + restart) | < 2 minutes | Bad code deploy |
| Full restore (VM rebuild) | 30+ minutes | Infrastructure corruption |

#### Implementation

1. **Create `ops/rollback.sh`**:

```bash
#!/bin/bash
# Fast rollback: checkout previous commit, reinstall, restart
set -euo pipefail

PREV_COMMIT=$(git rev-parse HEAD~1)
echo "Rolling back to $PREV_COMMIT"
git checkout "$PREV_COMMIT"
pip install -r requirements.txt
systemctl restart tradingai-api
sleep 5
curl -sf http://127.0.0.1:8000/api/health || {
    echo "ROLLBACK FAILED: API not healthy after rollback"
    git checkout main  # restore current
    exit 1
}
echo "ROLLBACK OK: API healthy after rollback to $PREV_COMMIT"
```

2. **Document in `ops/RESTORE.md`**:
   - Fast rollback section
   - When to use fast vs full rollback
   - Rollback testing procedure (quarterly)

3. **Keep last 3 commits reachable** — git history preserved (default).

#### Tests

| Test | Description |
|---|---|
| `test_rollback_script_exists` | `ops/rollback.sh` exists and is executable |
| `test_rollback_completes_under_2min` | Rollback < 2 minutes (measured) |
| `test_rollback_restores_health` | API healthy after rollback |

---

## Part F: State Transition Protocol (Summary)

### Complete State Machine

```
                     ┌──────────────────┐
                     │   LIVE DATA      │
                     │ data_quality:    │
                     │   "LIVE"         │
                     └────────┬─────────┘
                              │
              ┌───────────────┼───────────────┐
              │               │               │
    ┌─────────▼─────┐ ┌──────▼──────┐ ┌──────▼──────┐
    │ provider      │ │ data source │ │ API itself  │
    │ failure       │ │ not refreshed│ │ failure     │
    └───────┬───────┘ └──────┬──────┘ └──────┬──────┘
            │                │                │
    ┌───────▼───────┐ ┌──────▼──────┐ ┌──────▼──────────┐
    │ DATA          │ │ STALE DATA  │ │ SYSTEM          │
    │ UNAVAILABLE   │ │ data_quality│ │ DEGRADED        │
    │               │ │ "STALE"     │ │ status:"degraded"│
    └───────┬───────┘ └──────┬──────┘ └──────┬──────────┘
            │                │                │
            │                │                │
   ┌────────▼────────┐ ┌────▼───────┐ ┌──────▼───────┐
   │ No regime/      │ │ User sees  │ │ DB restore,  │
   │ strategy/       │ │ "Data is X │ │ API restart, │
   │ confidence      │ │ minutes old│ │ self-heal,   │
   │ generated       │ │"           │ │ cron retry   │
   └────────┬────────┘ └────┬───────┘ └──────┬───────┘
            │               │                │
            │               │                │
   ┌────────▼────────┐ ┌───▼────────┐ ┌──────▼───────┐
   │ provider        │ │ cron retry │ │ recovery     │
   │ recovers        │ │ succeeds   │ │ verified     │
   └────────┬────────┘ └────┬───────┘ └──────┬───────┘
            │               │                │
   ┌────────▼────────┐ ┌───▼────────┐ ┌──────▼───────┐
   │ fresh data      │ │ fresh data │ │ integrity +  │
   │ verified        │ │ verified   │ │ row count    │
   └────────┬────────┘ └────┬───────┘ └──────┬───────┘
            │               │                │
            └───────────────┼────────────────┘
                            │
                   ┌────────▼─────────┐
                   │   LIVE DATA      │
                   └──────────────────┘
```

### Critical Rules

| Rule | Enforcement | Test |
|---|---|---|
| DATA UNAVAILABLE → no regime/strategy/confidence generated | Decorator/enrichment only adds metadata, never values | `test_no_manufactured_values` |
| API available ≠ data valid | Each endpoint independently reports freshness | `test_api_available_not_data_valid` |
| STALE → clearly labeled with age | All responses include `data_freshness` | `test_stale_flag_in_data_response` |
| Recovery → verified | Integrity check + row count match | `test_db_recovery_verified` |
| Shutdown → graceful | SIGTERM handler drains in-flight | `test_sigterm_graceful` |
| 503 (not 500) for service failure | Custom error handler for DB failures | `test_db_corruption_returns_503` |

---

## Part G: Test Plan Summary

### Graceful Degradation Tests (6)
1. `test_fresh_data_live` — Fresh data → LIVE
2. `test_stale_data_stale` — Aged data → STALE with age
3. `test_no_data_unavailable` — No data → DATA UNAVAILABLE
4. `test_partial_data_completeness` — Partial → PARTIAL with missing list
5. `test_no_manufactured_values` — Unavailable → no new analytical values
6. `test_all_endpoints_has_quality` — Every data endpoint has quality indicator

### Failure Isolation Tests (4)
7. `test_vix_stale_flagged` — VIX stale → flagged
8. `test_vix_unavailable_does_not_affect_price` — VIX failure → price unaffected
9. `test_options_unavailable_labeled` — Options empty → DATA UNAVAILABLE
10. `test_options_failure_isolated` — Options failure → other endpoints unaffected

### DB Recovery Tests (4)
11. `test_db_corruption_returns_503` — DB failure → 503
12. `test_db_recovery_verified` — Recovery verified
13. `test_recovery_alerted` — Recovery event → alert
14. `test_readonly_fallback` — Read-only mode available

### Stale Data Tests (4)
15. `test_health_reports_source_status` — Health includes per-source
16. `test_stale_flag_in_data_response` — Stale flag in data responses
17. `test_api_available_not_data_valid` — API ok ≠ data valid
18. `test_freshness_thresholds_correct` — Correct thresholds per endpoint

### Operational Recovery Tests (6)
19. `test_startup_verification` — Startup check before traffic
20. `test_sigterm_graceful` — Graceful shutdown
21. `test_restart_verified` — Post-restart health verified
22. `test_rollback_script_exists` — Rollback script exists
23. `test_rollback_completes_under_2min` — Rollback < 2 min
24. `test_rollback_restores_health` — Health after rollback

### Failure Observability Tests (4)
25. `test_success_count_increments` — Success tracking
26. `test_error_count_increments` — Error tracking
27. `test_consecutive_failure_alert` — 3+ failures → alert
28. `test_pipeline_status_accurate` — Pipeline status accurate

### Regression Tests
- All 350 existing tests remain green

**Total new tests**: 32

---

## Part H: Acceptance Summary

| # | Finding | Severity | Acceptance |
|---|---|---|---|
| A | 9.1 No graceful degradation | High | DATA UNAVAILABLE/STALE clearly communicated; no manufactured data |
| A | 6.4 yfinance fallback | Medium | Last-known data served with stale flag |
| A | 1.4 Inconsistent partial data | Medium | Every endpoint has data_completeness |
| B | 6.5 VIX failure not isolated | Medium | VIX failure doesn't affect non-VIX endpoints |
| B | 6.6 Options failure not isolated | Medium | Options failure isolated; quality accurate |
| B | 6.3 External API health tracking | Medium | Success/error counts; consecutive failure alerts |
| C | 9.4 DB failure recovery | Medium | Recovery verified; alerts fired |
| C | 6.7 DB failure not handled | Medium | 503 (not 500); user-friendly |
| D | 9.5 Stale data detection | Medium | Per-endpoint freshness; health reports sources |
| D | 6.8 NSE live quote health | Low | Staleness monitored; alert at 5 min |
| E | 9.6 API restart behavior | Medium | Graceful shutdown; startup verification |
| E | 9.7 Rollback strategy | Medium | Fast rollback < 2 min; documented |
| E | 6.8 NSE health | Low | Covered by D |

**13 findings addressed. 0 model layer changes. 350/350 regression required. 32 new tests.**

---

## Part I: Post-Implementation Verification

After implementation:

1. **Run 350/350 regression** — must pass
2. **Run all 32 new B.3 tests** — must pass
3. **Verify model layer untouched** — `git diff cdf0f6a HEAD --name-only` shows no model files
4. **Verify state transitions** — for each failure scenario, verify Normal → Failure → User-visible state → Recovery → Normal is testable and deterministic
5. **Verify no manufactured data** — simulate data unavailability; confirm no new regime/strategy/confidence values generated
6. **Verify 503 on DB failure** — simulate DB lock; confirm 503 (not 500)
7. **Verify graceful shutdown** — send SIGTERM; confirm in-flight requests complete
8. **Verify rollback** — execute rollback; confirm API healthy in < 2 minutes
9. **Commit and freeze** — B.3 commit, then freeze before B.4

---

*End of PHASE 6B-3 B.3 Specification: Failure Recovery. Awaiting independent review before implementation.*
