# PHASE 6B-2 — Scope Review (Read-Only)

**Status**: SCOPE REVIEW — NOT YET AUTHORIZED
**Frozen baselines**: `45f90fc` (analytical), `51c02f9` (PHASE 6A), `63ab095` (PHASE 6B-1)
**Regression baseline**: 220/220 passing
**Previous audit**: PHASE6B_PRODUCTION_HARDENING_AUDIT.md (61 findings)
**Previous implementation**: PHASE6B_STEP1_SPECIFICATION.md (7 findings addressed)

---

## 1. Reconciliation: 61 Findings vs 6B-1 Completed Work

### 6B-1 Findings Addressed (7 of 61)

| Finding | Severity | Dimension | 6B-1 Item | Status |
|---|---|---|---|---|
| 1.1 Inconsistent error schema | Critical | API Reliability | C.1 | ✅ Fixed |
| 1.2 No DB connection timeout | High | API Reliability | A.2 | ✅ Fixed |
| 1.3 Connection leaks | High | API Reliability | A.3 | ✅ Fixed |
| 1.4 Inconsistent partial data | Medium | API Reliability | A.4 | ✅ Fixed |
| 7.1 SQLite not WAL | Critical | Database | A.1 | ✅ Fixed |
| 6.1 No circuit breaker | High | Data-Source Failures | B.1 | ✅ Fixed |
| 6.2 No retry/backoff | High | Data-Source Failures | B.2 | ✅ Fixed |

### Remaining Findings (54 of 61)

| Dimension | Original | 6B-1 Fixed | Remaining | In 6B-2? |
|---|---|---|---|---|
| API Reliability | 8 | 4 | 4 | Partial (remaining items deferred) |
| Rate Limiting & Abuse | 3 | 0 | 3 | ✅ Yes — primary target |
| Monitoring & Alerting | 10 | 0 | 10 | ❌ 6B-3 |
| CI/CD | 3 | 0 | 3 | ❌ 6B-4 |
| Observability | 7 | 0 | 7 | ❌ 6B-3 |
| Data-Source Failures | 8 | 2 | 6 | Partial (resilience covered, gap detection deferred) |
| Database & Resources | 7 | 1 | 6 | Partial (foundational done, growth management deferred) |
| Security | 9 | 0 | 9 | ✅ Yes — primary target |
| Failure/Recovery | 8 | 0 | 8 | ❌ 6B-6 |
| Performance | 8 | 0 | 8 | ❌ 6B-5 |
| Production Deployment | 6 | 0 | 6 | ❌ 6B-6 |
| **Totals** | **61** | **7** | **54** | **6B-2 subset TBD** |

### 6B-2 Proposed Scope

Per the recommended priority ordering for a public options-trader audience:

> Reliability → Stale-data → **Abuse protection** → Monitoring → CI → Security → Performance → Deployment

Since Reliability (6B-1) and Stale-data are addressed, the next logical scope is **Abuse Protection + API Security**:

| 6B-2 Area | Audit Findings | Priority |
|---|---|---|
| **A. Rate Limiting** | 2.1 Zero rate limiting (Critical), 2.4 No request size limits (Medium), 2.5 No request timeout (Medium) | 🔴 Critical/Medium |
| **B. CORS Hardening** | 2.2 CORS wide open (High) | 🟠 High |
| **C. Input Validation** | 8.2 No input validation on portfolio POST (High) | 🟠 High |
| **D. Auth Boundary Assessment** | 2.3 No authentication (High), 8.1 No auth on portfolio (High) | 🟠 High |

### Explicitly NOT in 6B-2

| Area | Findings | Deferred to |
|---|---|---|
| Monitoring/Alerting | 3.1-3.10 | 6B-3 |
| CI/CD | 4.1-4.4 | 6B-4 |
| Observability | 5.1-5.5 | 6B-3 |
| Data-Source gap detection | 6.3-6.8 | 6B-3 |
| DB growth management | 7.2-7.6 | 6B-6 |
| Failure recovery | 9.1-9.8 | 6B-6 |
| Performance | 10.1-10.8 | 6B-5 |
| Deployment | 11.1-11.6 | 6B-6 |
| Remaining API reliability | 1.5-1.8 | 6B-2 or 6B-3 (TBD) |

### Out-of-Scope (Model Layer)

RegimeEngine, StrategyEngine, OptionsEngine, confidence mathematics, scenario normalization, LLM boundary, historical validation, data analysis — all unchanged.

Frozen chain preserved: `45f90fc → 51c02f9 → 63ab095 → (6B-2 TBD)`

---

## 2. 6B-2 Area Details

### A. Rate Limiting

**Findings**: 2.1 (Critical), 2.4 (Medium), 2.5 (Medium)
**Boundary**: Protect public API without changing successful response payloads or quantitative calculations
**Requirements**:
- Define endpoint categories: data endpoints, computation endpoints, list endpoints, health (exempt)
- Establish per-category request limits per IP
- Return standardized rate-limit errors (use ERROR_CODES "RATE_LIMITED" from 6B-1)
- Avoid interfering with legitimate website usage (crawlers/scrapers targeted, not real users)
- Health endpoint exempt for monitoring

**Implementation boundary**:
- Must not modify: successful response structures, model outputs, data calculations
- Must add: rate-limit counters, 429 responses, category classification
- Must preserve: all 220 existing tests

**Key design question**: Rate limits must be practical for a real website — too aggressive and legitimate users hit limits; too loose and abuse goes unchecked.

### B. CORS Hardening

**Finding**: 2.2 (High)
**Boundary**: Restrict origins without breaking frontend
**Requirements**:
- Replace `CORS(app)` with explicit allowlist
- Define allowed origins: `https://tradingai.in`, `https://www.tradingai.in`
- Separate development and production behavior (allow localhost in dev)
- OPTIONS preflight returns 403 for unauthorized origins

**Implementation boundary**:
- Must not modify: API response data, model calculations
- Must change: CORS configuration (one line change)
- Must test: frontend still works, unauthorized origins rejected

**Key design question**: Are there other origins that legitimately need access? Document all known origins before restricting.

### C. Input Validation

**Finding**: 8.2 (High)
**Boundary**: Validate API parameters without changing successful request handling
**Requirements**:
- Validate all portfolio POST fields: symbol (must be in config), entry_price (positive float), quantity (positive integer), direction (LONG/SHORT), dates (valid ISO)
- Return 400 with specific error messages for invalid fields
- Reject malformed/invalid values deterministically
- Prevent excessive/unreasonable request parameters (max length, max array size)

**Implementation boundary**:
- Must not modify: valid request handling, model calculations
- Must add: validation logic, error messages
- Must test: valid requests unchanged, invalid requests rejected with 400

**Key design question**: Validation rules should be config-driven (in config/instruments.json or config/settings.json) not hardcoded, so they can be adjusted without code changes.

### D. Authentication Boundary Assessment

**Findings**: 2.3 (High), 8.1 (High)
**Boundary**: Identify genuine auth requirements — do NOT add auth everywhere
**Requirements**:
- Map all 55 endpoints and classify: public, authenticated, admin
- Portfolio/private-user endpoints should not remain publicly writable
- Public market data endpoints remain unauthenticated
- Define what "authenticated" means in this context (API key, session, JWT?)
- Document the public/private boundary decision

**Implementation boundary**:
- Assessment only in 6B-2 (scope review)
- Implementation deferred to 6B-2 or 6B-5 pending review
- Must NOT add authentication everywhere merely because audit identified it
- Must preserve: public API accessibility for AdSense/public-site traffic

**Key design question**: TradingAI.in has public market-intelligence APIs. Authentication needs to be designed around the actual public/private boundary, not applied uniformly.

---

## 3. API Compatibility Concerns

### Frontend Compatibility
6B-2 changes must NOT break the existing frontend. Specifically:
- `/api/market` response structure unchanged
- `/api/<symbol>` response structure unchanged
- `/api/price/<symbol>` response structure unchanged
- `/api/options-intelligence` response structure unchanged
- All successful responses remain identical

### Rate-Limit Compatibility
- Rate limiting must not affect first request from a new IP
- Health endpoint must remain accessible without rate limits
- Website crawlers (AdSense, search) must not be incorrectly classified as abusive

### CORS Compatibility
- Frontend origin must be in allowlist before restriction takes effect
- Development workflow (localhost) must remain functional

---

## 4. Test Plan (6B-2)

| Test Category | Examples |
|---|---|
| Rate limiting | Request limit enforced per category, 429 returned after limit, health exempt, legitimate traffic unaffected |
| CORS | Unauthorized origin rejected, allowed origin permitted, OPTIONS preflight correct |
| Input validation | Invalid portfolio POST returns 400 with specific error, valid POST unchanged, edge cases tested |
| Auth boundary | All 55 endpoints classified, public endpoints accessible, portfolio endpoints reject unauthenticated |
| Regression | All 220 existing tests remain green |

---

## 5. Acceptance Criteria (6B-2)

If authorized:

1. **220 existing tests remain green**
2. **All new 6B-2 tests pass**
3. **Model layer untouched**: zero changes to regime.py, strategies.py, outlook.py, scenarios.py, options.py, ai_outlook.py, backtest.py, indicators.py
4. **Successful API responses unchanged**: all 55 endpoints return identical successful responses
5. **Rate limiting operational**: public endpoints protected, legitimate traffic unaffected
6. **CORS restricted**: unauthorized origins rejected, known origins permitted
7. **Input validation active**: invalid portfolio requests rejected with 400, valid requests unchanged
8. **Auth boundary documented**: all 55 endpoints classified with rationale

---

## 6. Out-of-Scope Reminder

The following are explicitly NOT part of 6B-2:

❌ RegimeEngine changes
❌ StrategyEngine changes
❌ Confidence recalibration
❌ Options historical validation
❌ 3+ year historical extension
❌ Backtest methodology changes
❌ LLM changes
❌ Trading strategy changes
❌ Monitoring/observability (6B-3)
❌ CI/CD (6B-4)
❌ Performance isolation (6B-5)
❌ Deployment hardening (6B-6)
❌ Circuit breaker integration into /api/global (created module, deferred)
❌ Retry integration into all fetch functions (created module, deferred)

---

## 7. Recommended Next Step

This document is a read-only scope review. No implementation authorized.

**Next action**: User independent review of this scope review.

If approved:
- Write `PHASE6B_STEP2_SPECIFICATION.md` (finding → requirement → implementation boundary → tests → acceptance criteria)
- Perform independent scope review of specification
- Then authorize implementation

If changes needed:
- Adjust scope per review feedback
- Update this document or write a revised version

---

*End of PHASE 6B-2 Scope Review. Awaiting user review before proceeding to specification.*
