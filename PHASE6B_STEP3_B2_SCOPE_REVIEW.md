# PHASE 6B-3 Phase B.2 — Scope Review: Security Audit & Auth Boundary

**Status**: SCOPE REVIEW — AWAITING AUTHORIZATION

**Frozen commits**: `45f90fc` → `51c02f9` → `63ab095` → `8bbd4d7` → `c39af34` → `3ec9473`

**Audit basis**: `PHASE6B_PRODUCTION_HARDENING_AUDIT.md` (8.x Security, 1.x API Reliability)
**Context**: B.1 CI/CD Foundation is now frozen, providing automated regression safety net.

---

## Scope Discipline

Per user directive: **Do not start by adding authentication everywhere.**

First define the boundary through audit. Then classify endpoints. Then define minimum auth boundary. Then authorize implementation.

**B.2 scope review is audit and specification only. No implementation authorized.**

---

## 1. Security Audit: Endpoint Classification

### Methodology

All 62 Flask routes cataloged. Each classified by:
- Whether it serves public market data (must remain unauthenticated)
- Whether it accesses user-specific data (requires auth)
- Whether it modifies state (requires auth + CSRF consideration)
- Whether it exposes sensitive information

### Classification

#### Category A: Public Market Intelligence (56 endpoints — NO AUTH required)

These endpoints serve publicly accessible market data. Per TradingAI.in's purpose as a public market-intelligence platform, these must remain unauthenticated.

| Sub-category | Endpoints |
|---|---|
| Prices & Quotes | /api/symbols, /api/price/<symbol>, /api/prices/<symbol>, /api/prices, /api/prices, /api/<symbol>, /api/nifty, /api/banknifty, /api/sensex, /api/finnifty, /api/global, /api/market |
| VIX | /api/vix, /api/vix/history, /api/vix/daily |
| Indicators & Regime | /api/indicators/<symbol>, /api/indicators, /api/regime/<symbol>, /api/regimes |
| Strategy & Outlook | /api/strategy/<symbol>, /api/strategies, /api/scenarios/<symbol>, /api/outlook/<symbol>, /api/outlooks, /api/market-outlook, /api/market-outlook/<date> |
| Options | /api/options/<symbol>, /api/options/expiries/<symbol>, /api/pcr, /api/maxpain, /api/pcr-history, /api/oi-top, /api/oi-concentration/<symbol>, /api/expected-move/<symbol>, /api/options-intelligence/<symbol> |
| Breadth & Snapshots | /api/breadth, /api/index-breadth, /api/breadth/history, /api/snapshot, /api/snapshots |
| History & Views | /api/history, /api/investment/<symbol> |
| ETF & Fundamentals | /api/etf, /api/etf-holdings, /api/fundamentals/<symbol>, /api/company/<symbol>, /api/data_status |
| News & Corporate | /api/news, /api/news/<symbol>, /api/actions, /api/actions/<symbol> |
| Mutual Funds | /api/mf |
| Alerts | /api/alerts |
| Monitoring | /api/metrics, /api/health |

**Auth decision**: NO AUTH. These are public market-intelligence endpoints. Adding auth would contradict TradingAI.in's public content mission.

#### Category B: User-Specific State-Modifying (3 endpoints — AUTH required)

| Endpoint | Methods | Description | Auth Required | Reason |
|---|---|---|---|---|
| /api/portfolio | GET | List all portfolio holdings | YES | Returns user-specific financial data |
| /api/portfolio | POST | Add portfolio holding | YES | Modifies user financial data |
| /api/portfolio/<int:pid> | DELETE | Delete portfolio entry | YES | Modifies user financial data |
| /api/chat/messages | GET | Retrieve chat messages | CONSIDER | Chat is currently anonymous; evaluate auth need |
| /api/chat/messages | POST | Send chat message | YES | State modification; rate-limited |

**Auth decision**: Portfolio endpoints require auth. Chat POST requires auth (state modification). Chat GET may remain public if chat is intended as anonymous discussion forum.

#### Category C: Administrative/Operational (0 endpoints)

No admin-only endpoints identified in current API. All endpoints serve either public market data or user portfolio/chat data.

---

## 2. Finding-by-Finding Audit

### 8.1 No Authentication on Portfolio Endpoints [HIGH]

**Current state**: Portfolio GET/POST/DELETE have zero auth. Shared dataset (no user_id column).

**Classification**: This is the primary security finding. Portfolio data is user-specific financial data.

**Boundary decision**: Auth required for portfolio endpoints. Public market data stays public.

**Key question**: Does TradingAI.in intend portfolio to be per-user (requires auth) or shared (public)?

**Recommendation**: Per-user portfolio. Add auth boundary. This is the minimum auth scope.

### 8.2 No Input Validation on Portfolio POST [HIGH]

**Current state**: Portfolio POST accepts unvalidated fields. Negative quantities, invalid symbols, etc.

**Classification**: Data integrity issue, closely linked to 8.1 (auth is prerequisite for user isolation, but validation should exist regardless).

**Recommendation**: Implement validation independently of 8.1. Validation protects data integrity even in development/testing.

### 8.3 Debug Mode Enforcement [MEDIUM]

**Current state**: Debug is False but not enforced. Flask app importable.

**Classification**: Easy win. One-line assertion. No response changes.

**Recommendation**: Implement immediately in B.2 scope.

### 8.4 Secrets Management [MEDIUM]

**Current state**: API key on VM filesystem. Not in git. Backup excludes /etc/tradingai/.

**Classification**: Operational concern. Requires VM-level changes.

**Recommendation**: Document key rotation. Verify backup exclusion. Defer VM-level implementation to operational team.

### 8.5 nginx Cache Auth Exclusion [MEDIUM]

**Current state**: All /api/ responses cached 10s. Portfolio endpoints don't currently use cache but need explicit exclusion.

**Classification**: Config change. Low risk.

**Recommendation**: Implement. Add proxy_no_cache for portfolio endpoints.

### 8.6 CSRF Protection [MEDIUM]

**Current state**: No CSRF on state-changing endpoints. CORS already restricted (6B-2).

**Classification**: Depends on 8.1 (need auth before CSRF is meaningful).

**Recommendation**: Define CSRF approach in scope review. Implement after 8.1.

### 8.7 SQL Injection Analysis [LOW]

**Current state**: All SQL parameterized. Table names hardcoded but fragile.

**Classification**: Code quality / defense in depth.

**Recommendation**: Implement. Add ALLOWED_TABLES assertions. Low risk.

### 8.8 Error Context Leak [LOW]

**Current state**: Error messages echo user input. No custom error handlers.

**Classification**: Information disclosure. Low risk but easy fix.

**Recommendation**: Implement. Add custom error handlers.

### 1.5 Bare Except Clauses [MEDIUM]

**Current state**: 3 bare except: in health endpoint.

**Classification**: Code quality. Can mask critical errors.

**Recommendation**: Implement. Replace with except Exception:.

### 1.6 Impure _symbol_data [MEDIUM]

**Current state**: _build_market calls _symbol_data (creates Response objects internally).

**Classification**: Code quality / anti-pattern. No security impact.

**Recommendation**: Implement during B.2 or B.5. Low priority for security scope.

### 1.7 f-string SQL Queries [MEDIUM]

**Current state**: Table names in f-string SQL. Safe (hardcoded) but fragile.

**Classification**: Defense in depth.

**Recommendation**: Implement. Add ALLOWED_TABLES assertions. Pairs with 8.7.

### 1.8 Error Messages Leak Internal Details [LOW]

**Current state**: Error messages echo user input and may contain internal details.

**Classification**: Same as 8.8. Pair implementation.

**Recommendation**: Implement alongside 8.8.

---

## 3. Proposed B.2 Scope

### B.2 Sub-phase A: Security Audit & Boundary Definition (Scope Review Only)

**Deliverable**: This document + B.2 Specification

| Task | Description | Type |
|---|---|---|
| Endpoint classification | Complete (above) | Audit |
| Auth boundary definition | Portfolio endpoints require auth; public market data stays public | Audit |
| Finding prioritization | Define implementation order | Audit |
| Auth mechanism selection | Define API key approach | Audit |
| Response preservation plan | Document how public responses stay unchanged | Audit |

### B.2 Sub-phase B: Implementation (requires separate authorization)

| Finding | Severity | Effort | Dependencies | In B.2? |
|---|---|---|---|---|
| 8.3 Debug Mode Enforcement | MEDIUM | S | None | YES |
| 8.7 SQL Injection Analysis | LOW | S | None | YES |
| 8.8 Error Context Leak | LOW | S | None | YES |
| 1.5 Bare Except Clauses | MEDIUM | S | None | YES |
| 1.7 f-string SQL | MEDIUM | S | None | YES |
| 1.8 Error Messages | LOW | S | None | YES |
| 8.5 nginx Cache Exclusion | MEDIUM | S | None | YES |
| 8.1 Portfolio Auth | HIGH | L | Auth design | YES |
| 8.2 Portfolio Validation | HIGH | S | Auth or independent | YES |
| 8.6 CSRF Protection | MEDIUM | S | 8.1 | PHASED |
| 8.4 Secrets Management | MEDIUM | L | VM ops | DEFERRED |
| 1.6 Impure _symbol_data | MEDIUM | L | Refactor | PHASED |

---

## 4. Auth Boundary Definition

### Minimum Authentication Boundary

```
Public endpoints (56 routes): NO AUTH
├── All market data endpoints
├── All monitoring endpoints
└── All news/ETF/fundamentals endpoints

Protected endpoints (3 routes): AUTH REQUIRED
├── /api/portfolio GET
├── /api/portfolio POST
└── /api/portfolio/<int:pid> DELETE

Chat endpoints (2 routes): TBD
├── /api/chat/messages GET: PUBLIC (anonymous chat) or AUTH?
└── /api/chat/messages POST: AUTH REQUIRED (state modification)
```

### Auth Mechanism (For Specification Phase)

Options to evaluate:
1. **API Key header**: `Authorization: Bearer <key>` — simple, stateless
2. **Session cookie**: Flask session — requires server-side state
3. **API Key query param**: `?api_key=<key>` — less secure, easier for testing

**Recommendation**: API Key header (option 1). Stateless, works for mobile/web, doesn't require server-side session storage.

### Response Preservation Plan

| Endpoint | Current Behavior | With Auth | Change |
|---|---|---|---|
| /api/price/NIFTY | Returns price data | Same | None |
| /api/health | Returns status | Same | None |
| /api/metrics | Returns metrics | Same (exempt from auth) | None |
| /api/portfolio (unauth) | Returns all data | 401 | Change |
| /api/portfolio (auth) | Returns all data | Returns user's data | Change |

**Key principle**: All public endpoints behave identically with and without auth. Auth only affects portfolio endpoints.

---

## 5. Acceptance Criteria (B.2 Scope)

### Regression Requirements

| Requirement | Target |
|---|---|
| Existing tests passing | 325/325 (current baseline after B.1) |
| New B.2 tests | Per specification (~15-25 new) |
| Model files modified | 0/8 |
| Public API responses | Unchanged for all public endpoints |
| Auth only affects portfolio | Yes |

### Model Boundary Protections

| Protection | Mechanism |
|---|---|
| File-level | `git diff --name-only` → 0 model files |
| Import-level | No auth/security imports in model files |
| Response-level | Public endpoints return identical responses with/without auth |
| Test-level | All 325 existing tests must pass |

### Security Tests

| Test | Target |
|---|---|
| Portfolio without auth returns 401 | Yes |
| Portfolio with valid auth returns data | Yes |
| Public endpoints return same data with/without auth | Yes |
| Debug mode enforced | Yes |
| SQL assertions present | Yes |
| Error handlers return JSON | Yes |
| No bare except in health | Yes |
| nginx excludes portfolio from cache | Yes |

---

## 6. Out of Scope for B.2

- ❌ Full auth system with user management, registration, login
- ❌ OAuth/SSO integration
- ❌ Rate limiting changes (6B-2 already done)
- ❌ CORS changes (6B-2 already done)
- ❌ CSRF implementation (phased — depends on auth design)
- ❌ VM-level secrets management
- ❌ _symbol_data refactoring (phased — code quality)
- ❌ Any model-layer changes
- ❌ Any analytical features

---

## 7. Proposed Sequence

```
B.2 Scope Review (THIS DOCUMENT)
     ↓
B.2 Specification (auth design, response plan, tests)
     ↓
Independent Review of Specification
     ↓
Explicit Implementation Authorization
     ↓
Implementation (8.3, 8.7, 8.8, 1.5, 1.7, 1.8, 8.5 first; 8.1, 8.2 next)
     ↓
Tests + Security Gates
     ↓
Independent Review
     ↓
B.2 Freeze 🔒
     ↓
STOP
```

**B.2 scope review is audit and specification only. No implementation authorized until specification review passes and explicit authorization is given.**

---

## 8. Authorization Request

**B.2 Scope Review**: Ready for review.

**B.2 Implementation**: Not authorized. Awaiting specification review and explicit authorization.

**Next action**: Review this scope document and decide:
- **Authorize B.2 specification** → Proceed to specification phase
- **Modify scope** → Update this document
- **Reject** → Re-evaluate B.2 scope

🔒 STOP boundary remains at `3ec9473` (B.1 frozen).
