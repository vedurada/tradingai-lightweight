# PHASE 6B-3 Phase B.2 — Specification: Authentication & Security

**Status**: SPECIFICATION — AWAITING INDEPENDENT REVIEW

**Frozen commits**: `45f90fc` → `51c02f9` → `63ab095` → `8bbd4d7` → `c39af34` → `3ec9473`
**Regression baseline**: 325/325 passing (after B.1)

---

## 1. Design Principles

1. **Minimum auth boundary**: Only portfolio endpoints require auth. Public market intelligence stays public.
2. **Resource isolation**: AuthN without AuthZ is insufficient. Every portfolio query must be filtered by user_id.
3. **Zero model-layer impact**: No changes to RegimeEngine, StrategyEngine, OptionsEngine, confidence math, or any analytical logic.
4. **Public response preservation**: All 56 public endpoints return identical responses with/without auth.
5. **API key security**: Keys never stored or logged in plaintext.
6. **Consistent auth**: All portfolio operations (GET/POST/DELETE) require auth.

---

## 2. Authentication Design

### API Key Mechanism

| Aspect | Specification |
|---|---|
| **Generation** | Cryptographically secure random string: `secrets.token_urlsafe(32)` (43 chars) |
| **Storage** | SHA-256 hash (salted) in database. Plaintext key returned ONLY at generation time. |
| **Transmission** | HTTP header: `Authorization: Bearer <api-key>` |
| **Lookup** | Server hashes received key with salt, looks up hash in `api_keys` table |
| **Missing/Invalid** | Return `401 Unauthorized` with `{"error": {"code": "UNAUTHORIZED", "message": "Authentication required", "timestamp": "<iso>"}}` |
| **Logging** | NEVER log API keys. Log only key ID (hash prefix) for debugging. |

### API Key Table Schema

```sql
CREATE TABLE api_keys (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    key_hash TEXT NOT NULL UNIQUE,
    key_salt TEXT NOT NULL,
    key_prefix TEXT NOT NULL,
    label TEXT DEFAULT 'default',
    is_active INTEGER DEFAULT 1,
    created_at TEXT NOT NULL,
    last_used_at TEXT,
    revoked_at TEXT,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
```

### User Table Schema (NEW)

```sql
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    api_key_id INTEGER UNIQUE,
    created_at TEXT NOT NULL
);
```

### Key Lifecycle

| Operation | Behavior |
|---|---|
| **Create** | User registers → system generates key → returns plaintext ONCE → stores hash+salt |
| **Use** | Client sends `Authorization: Bearer <key>` → server verifies hash → proceeds |
| **Rotate** | New key generated, old key marked revoked. Both active during rotation window. |
| **Revoke** | `is_active = 0`, `revoked_at = now()`. Key immediately rejected. |
| **Missing** | 401 response |
| **Invalid** | 401 response (key not found in table, or revoked, or inactive) |

---

## 3. Portfolio Authorization & Isolation

### The Critical Requirement

Authentication WITHOUT resource isolation is insufficient. One user's key must NEVER access another user's portfolio.

### Isolation Mechanism

Every portfolio query must include `WHERE user_id = ?` filter. No exceptions.

| Endpoint | Current Query | Spec Query |
|---|---|---|
| GET /api/portfolio | `SELECT * FROM portfolio ORDER BY created_at DESC` | `SELECT * FROM portfolio WHERE user_id = ? ORDER BY created_at DESC` |
| POST /api/portfolio | `INSERT INTO portfolio (symbol, ...)` | `INSERT INTO portfolio (user_id, symbol, ...)` |
| DELETE /api/portfolio/<pid> | `DELETE FROM portfolio WHERE id=?` | `DELETE FROM portfolio WHERE id=? AND user_id=?` |
| GET /api/portfolio/<pid> | (not currently exists) | `SELECT * FROM portfolio WHERE id=? AND user_id=?` |

### 401 vs 403 Behavior

| Condition | Response | Code |
|---|---|---|
| No Authorization header | Missing authentication | 401 |
| Invalid/expired/revoked key | Invalid authentication | 401 |
| Valid key but portfolio doesn't belong to user | Not authorized for this resource | 403 |
| Valid key but portfolio entry doesn't exist | Not found (404, not 403) | 404 |

### GET Behavior with Auth

- Valid key + belongs to user → returns user's portfolio entries
- Valid key + no entries → returns empty array `[]` (not error)
- Valid key + another user's entries → 403 Forbidden

### DELETE Behavior with Auth

- Valid key + entry belongs to user → delete, return `{"ok": true}`
- Valid key + entry doesn't exist → 404 Not Found
- Valid key + entry belongs to another user → 403 Forbidden
- No key → 401 Unauthorized

### POST Behavior with Auth

- Valid key → insert with `user_id` from key → return created entry with `user_id` field
- No key → 401 Unauthorized
- Invalid payload → 400 with validation errors (same as current 6B-2 validation)

---

## 4. Existing Portfolio Data Migration

### Problem

Current portfolio table has no `user_id` column. All portfolio entries are shared.

### Migration Plan

```sql
-- Add user_id column (nullable during migration)
ALTER TABLE portfolio ADD COLUMN user_id INTEGER;

-- If users table exists, assign entries to a default user
UPDATE portfolio SET user_id = (SELECT id FROM users WHERE username = 'default') WHERE user_id IS NULL;

-- Make user_id non-nullable after all entries assigned
-- (This is a schema change — must be documented as a deployment step)
```

### Migration Rules

1. `user_id` column added as NULLABLE initially
2. Existing entries assigned to a default system user
3. New entries always have `user_id` from auth context
4. After verification, `user_id` becomes NOT NULL
5. Migration must complete before auth is enforced
6. If migration fails, auth is NOT enforced (fail-safe)

---

## 5. Immediate Security Fixes

These fixes require no auth mechanism and can be implemented independently.

### 5.1 Debug Mode Enforcement (8.3)

**Change**: Add to `backend/api_server.py` top-level:

```python
assert os.environ.get("FLASK_DEBUG", "0") != "1", "FLASK_DEBUG must not be 1"
app.config["DEBUG"] = False
```

**Test**: Verify assertion fires when FLASK_DEBUG=1. Verify debug=False in app config.

### 5.2 SQL Injection Prevention (8.7 + 1.7)

**Change**: Create `backend/sql_guard.py`:

```python
ALLOWED_TABLES = {
    "price_1m", "price_1d", "price_5m", "price_15m",
    "vix_data", "vix_daily", "option_chain", "option_expiries",
    "live_quotes", "portfolio", "alerts", "chat_messages",
    "regime_data", "strategy_data", "scenarios", "outlook_data",
    "symbols", "market_data", "data_status", "indicators",
}

def assert_table_name(table: str) -> None:
    assert table in ALLOWED_TABLES, f"Disallowed table: {table}"
```

**Change**: Wrap all f-string SQL table names with `assert_table_name()`.

**Test**: Verify disallowed table names raise AssertionError. Verify allowed names pass.

### 5.3 Error Context Leak (8.8 + 1.8)

**Change**: Add custom error handlers in `api_server.py`:

```python
@app.errorhandler(404)
def handle_404(e):
    return error_response("NOT_FOUND", "Resource not found", 404)

@app.errorhandler(500)
def handle_500(e):
    app.logger.error(f"Internal error: {e}")
    return error_response("INTERNAL_ERROR", "An internal error occurred", 500)

@app.errorhandler(400)
def handle_400(e):
    return error_response("INVALID_REQUEST", "Invalid request", 400)
```

**Test**: Verify error responses contain no stack traces, no SQL errors, no file paths.

### 5.4 Bare Except Clauses (1.5)

**Change**: In `/api/health` function, replace `except:` with `except Exception:` and add logging.

**Test**: Verify no bare `except:` clauses exist in health endpoint.

---

## 6. Nginx Security Boundary (8.5)

### Change

Add to `ops/nginx-tradingai.conf`:

```nginx
# Portfolio endpoints must NOT be cached
location = /api/portfolio {
    proxy_no_cache 1;
    proxy_cache_bypass 1;
    # ... existing proxy settings
}

location = /api/portfolio/ {
    proxy_no_cache 1;
    proxy_cache_bypass 1;
    # ... existing proxy settings
}
```

**Test**: Verify portfolio endpoints have `proxy_no_cache` in nginx config. Verify public endpoints still cached.

---

## 7. Validation Rules (8.2 Re-evaluation)

### Current State

`validate_portfolio_payload()` exists from 6B-2 implementation. Rules:

1. Symbol must be in config/instruments.json
2. Entry price must be positive float
3. Quantity must be positive integer
4. Direction must be LONG or SHORT
5. Entry date must be valid ISO format
6. Strategy required

### B.2 Enhancement (with auth)

Same rules as 6B-2, PLUS:
7. `user_id` from auth context is injected into INSERT (not from payload)
8. `user_id` is logged but never exposed in response or logs

**Test**: Verify payload validation rules are unchanged from 6B-2. Verify valid requests unchanged.

---

## 8. CSRF Dependency (8.6)

### Status: PHASED — After auth design

**Reason**: CSRF protection requires auth to be meaningful. CSRF tokens are validated against authenticated sessions. Without auth, CSRF protection has no context.

**Dependency**: 8.1 Portfolio Auth must be implemented first.

**Future spec**: Define CSRF approach after B.2 auth is frozen and B.2 implementation begins.

---

## 9. Rate-Limit Interaction with Auth

| Parameter | Value | Notes |
|---|---|---|
| Public endpoints | 60/min (data), 10/min (computation), 30/min (options) | Unchanged from 6B-2 |
| Portfolio endpoints | 30/min per API key | Same as other endpoints |
| Rate limit key | API key hash (or IP for unauthenticated) | Auth doesn't change rate limit structure |
| 429 response | Same standardized error schema | Unchanged |

**Key principle**: Auth provides identity, not additional rate-limit capacity. A valid API key doesn't get higher limits.

---

## 10. Logging Rules

### API Key Protection

| Rule | Enforcement |
|---|---|
| Never log API key plaintext | Sanitize before logging |
| Never log Authorization header | Strip from log context |
| Log key prefix only | First 8 chars of hash for debugging |
| Never log request body | Especially POST payloads with key material |

### Implementation

```python
def sanitize_headers(headers):
    safe = dict(headers)
    if "Authorization" in safe:
        safe["Authorization"] = "***REDACTED***"
    return safe
```

**Test**: Verify no API key appears in any log output. Verify Authorization header redacted.

---

## 11. Response Preservation Plan

### Public Endpoints (56 routes)

All public endpoints behave identically with/without auth. The `before_request` auth check only enforces auth on `/api/portfolio` routes.

### Verification Tests

| Test | Target |
|---|---|
| GET /api/price/NIFTY without auth → 200 | Yes |
| GET /api/price/NIFTY with auth → 200, same data | Yes |
| GET /api/market without auth → 200 | Yes |
| GET /api/metrics without auth → 200 | Yes (exempt) |
| GET /api/health without auth → 200 | Yes |
| GET /api/portfolio without auth → 401 | Yes |
| GET /api/portfolio with valid auth → 200 | Yes |
| POST /api/portfolio without auth → 401 | Yes |
| POST /api/portfolio with valid auth → 201 | Yes |
| DELETE /api/portfolio/<id> without auth → 401 | Yes |
| DELETE /api/portfolio/<id> with auth (owner) → 200 | Yes |
| DELETE /api/portfolio/<id> with auth (non-owner) → 403 | Yes |

---

## 12. Test Plan

### Regression Tests

| Category | Count | Purpose |
|---|---|---|
| Existing regression | 325 | Baseline preservation |
| Auth boundary | 15-20 | AuthN/AuthZ verification |
| Isolation | 5 | Cross-user access prevention |
| Error handling | 10 | 401/403/404 behavior |
| Security fixes | 10 | Debug, SQL, errors, bare except |
| Logging | 5 | API key not in logs |
| **Total** | ~360-375 | Full coverage |

### Critical Test: Isolation Proof

```python
def test_isolation_two_users_cannot_access_each_other():
    # User A creates portfolio entry
    key_a = create_api_key("user_a")
    r_a = client.post("/api/portfolio", headers={"Authorization": f"Bearer {key_a}"}, json=valid_payload)
    entry_id = r_a.json["id"]

    # User B tries to access User A's entry
    key_b = create_api_key("user_b")
    r_b = client.get(f"/api/portfolio/{entry_id}", headers={"Authorization": f"Bearer {key_b}"})
    assert r_b.status_code == 403

    # User B lists portfolio — should be empty
    r_b_list = client.get("/api/portfolio", headers={"Authorization": f"Bearer {key_b}"})
    assert r_b_list.status_code == 200
    assert len(r_b_list.json) == 0

    # User A can still see their own entry
    r_a_list = client.get("/api/portfolio", headers={"Authorization": f"Bearer {key_a}"})
    assert len(r_a_list.json) == 1
    assert r_a_list.json[0]["id"] == entry_id
```

---

## 13. Files to Create

| File | Purpose |
|---|---|
| `backend/auth.py` | API key generation, validation, hashing, user lookup |
| `backend/sql_guard.py` | ALLOWED_TABLES assertions |
| `config/auth.json` | Auth configuration (key settings, token TTL) |
| `tests/test_phase6b_b2.py` | 40-50 B.2 tests |
| `PHASE6B_STEP3_B2_SPECIFICATION.md` | This document |

## 14. Files to Modify

| File | Change |
|---|---|
| `backend/api_server.py` | Auth middleware, error handlers, portfolio user_id filtering, debug assertion |
| `backend/api_server.py` (portfolio) | Add user_id to INSERT, filter by user_id to SELECT/DELETE |
| `ops/nginx-tradingai.conf` | proxy_no_cache for portfolio endpoints |
| `ops/rollback.sh` | Handle schema migration rollback |
| `ops/DEPLOYMENT.md` | Document migration steps |

## 15. Files NOT Touched

- `backend/regime.py` — unchanged
- `backend/strategies.py` — unchanged
- `backend/indicators.py` — unchanged
- `backend/options.py` — unchanged
- `backend/outlook.py` — unchanged
- `backend/scenarios.py` — unchanged
- `backend/ai_outlook.py` — unchanged
- `backend/backtest.py` — unchanged
- All successful public API responses — unchanged
- All quantitative model logic — unchanged

## 16. Model Boundary Protection

| Protection | Mechanism |
|---|---|
| File-level | `git diff --name-only` → 0 model files modified |
| Import-level | No auth/security imports in model files |
| Response-level | Public endpoints return identical responses |
| Test-level | All 325 existing tests must pass before AND after |
| Independent review | Required before freeze |

## 17. Explicit Out-of-Scope

- ❌ User registration/login UI
- ❌ OAuth/SSO/SAML integration
- ❌ Session management (cookie-based)
- ❌ CSRF implementation (phased — depends on auth)
- ❌ Multi-factor authentication
- ❌ Password storage/reset
- ❌ User management API
- ❌ Role-based access control
- ❌ Admin dashboard
- ❌ VM-level secrets management
- ❌ Audit logging platform
- ❌ Any changes to analytical/model layer
- ❌ Any changes to confidence, regime, strategy logic
- ❌ Historical data or indicator population
- ❌ Predictive integrity work

## 18. Dependencies

| Finding | Depends On |
|---|---|
| 8.1 Portfolio Auth | Auth design (this spec) |
| 8.2 Validation re-eval | 8.1 (auth context for user_id) |
| 8.6 CSRF | 8.1 (auth required first) |
| 8.4 Secrets | VM operations (deferred) |

## 19. Sequence

```
This Specification ✅
↓
Independent Specification Review ⏳ AWAITING
↓
Explicit Implementation Authorization ⏳
↓
Implementation (immediate fixes first, auth second) ⏳
↓
Tests + Security Gates ⏳
↓
Independent Review ⏳
↓
B.2 Freeze 🔒 ⏳
↓
STOP ⏳
```

---

## 20. Authorization Request

**Specification review**: Ready for independent review.
**Implementation**: Not authorized until specification review passes and explicit authorization given.

**Next action**: Independent specification review.

🔒 STOP boundary remains at `3ec9473` (B.1 frozen). No implementation authorized.
