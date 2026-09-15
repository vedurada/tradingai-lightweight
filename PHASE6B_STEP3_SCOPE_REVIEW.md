# PHASE 6B-3 Scope Review

**Status**: SCOPE REVIEW — AWAITING AUTHORIZATION

**Frozen commits**: `45f90fc` (analytical), `51c02f9` (6A), `63ab095` (6B-1), `8bbd4d7` (6B-2, FROZEN)

**Audit basis**: `PHASE6B_PRODUCTION_HARDENING_AUDIT.md` (61 findings total)
**Addressed in 6B-1**: 7 findings (1.1, 1.2, 1.3, 1.4, 7.1, 6.1, 6.2)
**Addressed in 6B-2**: 6 findings (2.1, 2.2, 2.4, 2.5, 8.2, E.6)
**Remaining**: 48 findings across 11 dimensions

---

## Scope Decision

Per independent review guidance:

> 6B-3 should remain infrastructure/production hardening only, rather than mixing in confidence calibration, real RSI/MACD/ADX population, options historical data, 3+ year historical extension, predictive-integrity reassessment. Those belong to a later analytical validation phase.

**Included**: Monitoring/observability + CI/regression gates + security hardening + failure recovery infrastructure
**Excluded**: All analytical/model-layer features (confidence calibration, data population, historical extension, predictive integrity)

---

## Dependency Reconciliation (6B-1/6B-2 → 6B-3)

| 6B-1/6B-2 Change | Creates Dependency On | 6B-3 Finding |
|---|---|---|
| Circuit breaker (6B-1 B.1) | Needs upstream health data for meaningful trip decisions | 6.3 No External API Health Tracking |
| Retry with 429 non-retry (6B-1/6B-2) | Needs monitoring to detect rate-limit-induced failures | 3.2 No API Failure Counter |
| Standardized error schema (6B-1 C.1) | Needs structured logging for error context | 5.1 No Structured Logging, 5.4 Error Logs Don't Include Request Context |
| Rate limiting (6B-2) | Needs observability to verify effectiveness | 3.1 No Latency Tracking, 3.3 No Latency Alerts |
| Per-endpoint timeouts (6B-2) | Needs metrics to calibrate timeout values | 3.1 No Latency Tracking, 5.3 No Request Timing Middleware |
| CORS + input validation (6B-2) | Needs security monitoring | 8.3-8.8 Security findings |

---

## 6B-3 Proposed Findings (48 remaining, by priority)

### P1: Critical (1 finding)

| ID | Finding | Severity | Effort | Rationale |
|---|---|---|---|---|
| 4.1 | No Automated Regression Gates | CRITICAL | M | Core CI infrastructure; gates all future changes |

### P2: High (7 findings)

| ID | Finding | Severity | Effort | Rationale |
|---|---|---|---|---|
| 3.1 | No Latency Tracking | HIGH | M | Required for rate limiting + timeout calibration |
| 3.2 | No API Failure Counter | HIGH | S | Required for circuit breaker meaningfulness |
| 5.1 | No Structured Logging | HIGH | M | Required for all monitoring/alerting |
| 6.4 | No Fallback for yfinance Outage | MEDIUM→HIGH | M | Prerequisite for 6.5, 6.6 (data source isolation) |
| 9.1 | No Graceful Degradation for Market-Data Outage | HIGH | L | Complements 6.4 (outage handling) |
| 10.2 | Expensive Options Endpoints | HIGH | M | Performance hardening |
| 11.1 | No Health Check on Deploy | HIGH | S | Deployment safety gate |

### P3: Medium (16 findings)

| ID | Finding | Severity | Effort | Rationale |
|---|---|---|---|---|
| 3.3 | No Latency Alerts | MEDIUM | S | Depends on 3.1 latency tracking |
| 3.4 | Alert Thresholds Not Configured | MEDIUM | S | Depends on 3.1, 3.2 |
| 3.5 | No Health Check Beyond /api/health | MEDIUM | S | Extends existing health monitoring |
| 3.6 | Data Freshness Only Checks Last Timestamp | MEDIUM | M | Per-endpoint freshness (depends on 9.5) |
| 3.7 | Logs Are Plain Text | MEDIUM | M | Depends on 5.1 structured logging |
| 3.8 | Distributed Tracing Absent | MEDIUM | L | Observability enhancement |
| 4.2 | No Commit/PR Validation | HIGH | S | CI gate |
| 4.3 | No Deployment Safety Check | MEDIUM | S | Deployment safety |
| 4.4 | No Staging Environment | MEDIUM | L | CI/CD infrastructure |
| 5.2 | No Metrics Endpoint | MEDIUM | M | Dashboard for monitoring |
| 5.3 | No Request Timing Middleware | MEDIUM | S | Depends on 3.1, complements 10.7 |
| 5.4 | Error Logs Don't Include Request Context | MEDIUM | S | Depends on 5.1 |
| 5.5 | Log Rotation Not Configured | LOW | S | Operational hardening |
| 7.3 | No DB Growth Management | MEDIUM | M | DB operational hardening |
| 9.2 | No VIX Outage Fallback | MEDIUM | M | Data source isolation |
| 9.3 | No Options-Data Outage Fallback | MEDIUM | M | Data source isolation |

### P4: Low (24 findings)

Remaining lower-priority operational findings including: 1.5-1.8 (API reliability polish), 6.5/6.6/6.8 (data source health), 7.2/7.4/7.5/7.6 (DB operational), 8.3-8.8 (security hardening), 9.4-9.8 (failure recovery), 10.1/10.3-10.8 (performance), 11.2-11.3 (deployment).

---

## 6B-3 Proposed Phases

### Phase A: Monitoring & Observability Foundation (first)
- 3.1 Latency Tracking
- 3.2 API Failure Counter
- 5.1 Structured Logging
- 5.3 Request Timing Middleware
- 5.2 Metrics Endpoint
- 3.3/3.4 Latency Alerts & Thresholds

### Phase B: CI/Regression Gates
- 4.1 Automated Regression Gates (CRITICAL)
- 4.2 Commit/PR Validation
- 4.3 Deployment Safety Check

### Phase C: Failure Recovery & Security
- 9.1 Graceful Degradation
- 6.4 yfinance Outage Fallback
- 9.2/9.3 Data Source Outage Fallback
- 8.x Security hardening
- 7.x DB operational hardening

### Phase D: Operational Polish
- 3.5-3.8 Health/Freshness/Tracing
- 5.4/5.5 Logging polish
- 10.x Performance optimizations
- 11.x Deployment infrastructure

---

## Out of Scope for 6B-3

These items are deferred to a separate analytical validation phase:
- Confidence calibration indicator population
- Real RSI/MACD/ADX data population
- Options historical data (OCHL)
- 3+ year historical extension
- Predictive-integrity reassessment
- Any finding affecting model/analytical layer behavior

---

## Authorization Request

**PHASE 6B-3**: Infrastructure/production hardening — Monitoring/Observability + CI/Regression Gates first
**Estimated tests**: ~30-40 new tests
**Model layer impact**: 0 files (per audit, all 61 findings are operational/UX/infrastructure)
**Stop boundary**: After Phase A implementation and verification

**Authorize 6B-3 Phase A?** → Yes / No / Modify scope
