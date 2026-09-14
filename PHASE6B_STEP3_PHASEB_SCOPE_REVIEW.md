# PHASE 6B-3 Phase B — Scope Review

**Status**: SCOPE REVIEW — AWAITING AUTHORIZATION

**Frozen commits**: `45f90fc` (analytical), `51c02f9` (6A), `63ab095` (6B-1), `8bbd4d7` (6B-2, FROZEN), `c39af34` (6B-3 Phase A, FROZEN)

**Audit basis**: `PHASE6B_PRODUCTION_HARDENING_AUDIT.md` (61 findings total)
**Previously addressed**: 13 findings (7 in 6B-1 + 6 in 6B-2)
**Phase A addressed**: 7 findings (3.1, 3.2, 3.3, 3.4, 5.1, 5.2, 5.3)
**Remaining for Phase B+**: 41 findings across 11 dimensions

**Note**: Finding 3.7 (Logs Are Plain Text) is effectively addressed by Phase A's 5.1 (Structured Logging) implementation — same fix (StructuredJsonFormatter + logging_config.py). Not double-counted.

---

## 1. Findings Remaining After Phase A

### By Dimension

| Dimension | Critical | High | Medium | Low | Total |
|---|---|---|---|---|---|
| CI/CD | 1 | 1 | 2 | 0 | 4 |
| Data-Source Failures | 0 | 0 | 5 | 1 | 6 |
| Security | 0 | 1 | 4 | 2 | 7 |
| Database & Resources | 0 | 1 | 3 | 1 | 5 |
| API Reliability | 0 | 0 | 3 | 1 | 4 |
| Failure/Recovery | 0 | 1 | 6 | 1 | 8 |
| Performance | 1 | 1 | 5 | 1 | 8 |
| Production Deployment | 0 | 1 | 3 | 2 | 6 |
| Monitoring & Alerting | 0 | 0 | 5 | 0 | 5 (3.5-3.6 + 3.8-3.10) |
| Rate Limiting & Abuse | 0 | 0 | 0 | 1 | 1 (2.3) |
| Observability | 0 | 0 | 1 | 0 | 1 (5.4) |
| **Totals** | **2** | **5** | **31** | **10** | **48** |

*Note: Totals include 3.7 which is effectively covered by Phase A's 5.1 implementation. Effective remaining: 47 findings.*

---

### Detailed Finding Inventory

#### P1: Critical (2 findings)

| ID | Finding | Dimension | Effort | Dependencies |
|---|---|---|---|---|
| 4.1 | No Automated Regression Gates | CI/CD | M | None — foundation |
| 10.1 | Blocking Backtest Endpoints | Performance | L | Async processing infrastructure |

#### P2: High (5 findings)

| ID | Finding | Dimension | Effort | Dependencies |
|---|---|---|---|---|
| 8.1 | No Authentication on Portfolio Endpoints | Security | L | Auth design decision |
| 7.2 | No Connection Pooling | Database | M | 6B-1 get_db() pattern (already fixed) |
| 9.1 | No Graceful Degradation for Market-Data Outage | Failure/Recovery | L | Caching infrastructure (4.1 for CI, 10.4 for response cache) |
| 10.2 | Expensive Options Endpoints | Performance | M | Response caching (10.4) |
| 11.1 | No Health Check on Deploy | Deployment | S | None |

#### P3: Medium (26 findings)

| ID | Finding | Dimension | Effort | Dependencies |
|---|---|---|---|---|
| 1.5 | Bare Except Clauses in Health Endpoint | API Reliability | S | None |
| 1.6 | Impure _symbol_data Called Internally | API Reliability | L | Refactoring of internal function |
| 1.7 | f-string SQL Queries | API Reliability | S | ALLOWED_TABLES constant |
| 3.5 | No Health Check Beyond /api/health | Monitoring | M | /api/health extension |
| 3.6 | Data Freshness Only Checks Last Timestamp | Monitoring | M | 3.5 (deep health check) |
| 3.8 | Distributed Tracing Absent | Monitoring | L | Request ID (Phase A correlation ID exists) |
| 4.2 | No Commit/PR Validation | CI/CD | S | 4.1 (CI infrastructure) |
| 4.3 | No Deployment Safety Check | CI/CD | S | 4.1 (CI infrastructure) |
| 4.4 | No Staging Environment | CI/CD | L | 4.1, 4.3 |
| 5.4 | Error Logs Don't Include Request Context | Observability | M | 5.1 (structured logging, Phase A) |
| 5.5 | Log Rotation Not Configured | Observability | S | 5.1 (structured logging) |
| 6.3 | No External API Health Tracking | Data-Source | M | Phase A monitoring |
| 6.5 | VIX Data Source Failure Not Isolated | Data-Source | M | 6.3 (health tracking) |
| 6.6 | Options Data Source Failure Not Isolated | Data-Source | M | 6.3 (health tracking) |
| 6.7 | Database Failure Not Handled Gracefully | Data-Source | M | Phase A monitoring |
| 6.8 | NSE Live Quote Source Has No Health Check | Data-Source | S | 6.3 (health tracking) |
| 7.3 | No DB Growth Management | Database | M | Cleanup cron job |
| 7.4 | No Concurrent Write Protection | Database | S | WAL mode (6B-1, already fixed) |
| 7.5 | _symbol_data Connection Not Closed on Exception | Database | S | 1.6 (refactor _symbol_data) |
| 8.3 | Debug Mode Off but Flask App Importable | Security | S | None |
| 8.4 | Secrets Stored in /etc/tradingai/ | Security | L | Secrets manager or documented rotation |
| 8.5 | nginx Cache May Expose Stale Auth Data | Security | S | Auth boundary decision (8.1) |
| 8.6 | No CSRF Protection | Security | S | Auth boundary decision (8.1) |
| 8.8 | Error Responses Leak Request Context | Security | S | 5.1 (structured logging) |
| 9.2 | No VIX Outage Fallback | Failure/Recovery | M | 6.3, 9.1 |
| 9.3 | No Options-Data Outage Fallback | Failure/Recovery | M | 6.3, 9.1 |
| 9.4 | Database Failure Recovery | Failure/Recovery | S | 6.7 |
| 9.5 | Stale Data Detection | Failure/Recovery | M | 3.6, 3.5 |
| 9.6 | API Restart Behavior | Failure/Recovery | M | SIGTERM handler |
| 9.7 | No Rollback Strategy | Failure/Recovery | S | 4.1, 11.1 |
| 9.8 | No Request Queuing | Failure/Recovery | L | Infrastructure (gunicorn config) |
| 10.3 | /api/market Rebuild Blocks All Endpoints | Performance | L | Background refresh thread |
| 10.4 | No Response Caching | Performance | M | TTL configuration per endpoint type |
| 10.5 | No Pagination on List Endpoints | Performance | M | None |
| 10.6 | Concurrent User Behavior Not Tested | Performance | M | 4.1 (CI gates for concurrency test) |
| 10.7 | No Per-Endpoint Timeout | Performance | S | Phase A ENDPOINT_TIMEOUTS exists |
| 10.8 | Database Query Efficiency | Performance | L | DB schema changes |
| 11.2 | No Process Supervisor Beyond systemd | Deployment | S | None |
| 11.3 | No Structured Deployment Logging | Deployment | S | 5.1 (structured logging) |
| 11.4 | Manual Cron Installation | Deployment | S | Self-heal.sh update |
| 11.5 | No Database Backup Verification | Deployment | S | None |
| 11.6 | Rollback Script Not Documented | Deployment | S | 9.7 (rollback strategy) |

#### P4: Low (10 findings)

| ID | Finding | Dimension | Effort | Dependencies |
|---|---|---|---|---|
| 1.8 | Error Messages Leak Internal Details | API Reliability | S | None |
| 2.3 | No Authentication on Any Endpoint | Rate Limiting | L | 8.1 (auth design) |
| 7.6 | Chat Message Cleanup Uses Subquery | Database | S | None |
| 8.7 | SQL Injection Analysis | Security | S | ALLOWED_TABLES constant (1.7) |
| 9.8 | No Request Queuing | Failure/Recovery | L | Infrastructure |
| 10.1 | Blocking Backtest Endpoints | Performance | L | Async processing |
| 11.3 | No Structured Deployment Logging | Deployment | S | 5.1 |
| 11.5 | No Database Backup Verification | Deployment | S | None |

---

## 2. Dependencies and Grouping

### Dependency Graph

```
Foundation (no dependencies):
├── 4.1 Automated Regression Gates [CRITICAL]
├── 8.1 Authentication on Portfolio Endpoints
├── 8.3 Debug Mode Enforcement
├── 1.5 Bare Except Clauses
├── 1.7 f-string SQL Queries
├── 1.8 Error Messages Leak
├── 8.7 SQL Injection Analysis
├── 11.1 Health Check on Deploy
├── 10.7 Per-Endpoint Timeout
├── 7.6 Chat Cleanup Query

Level 1 (depend on foundation):
├── 4.2 Commit/PR Validation → 4.1
├── 4.3 Deployment Safety Check → 4.1
├── 5.4 Error Log Context → 5.1 (Phase A)
├── 5.5 Log Rotation → 5.1 (Phase A)
├── 11.3 Deploy Logging → 5.1 (Phase A)
├── 8.5 nginx Cache → 8.1
├── 8.6 CSRF Protection → 8.1
├── 8.8 Error Context → 5.1 (Phase A) + 8.1
├── 7.4 Concurrent Write → WAL (6B-1)
├── 10.7 Timeout → Phase A ENDPOINT_TIMEOUTS

Level 2 (depend on Level 1):
├── 4.4 Staging Environment → 4.1, 4.3
├── 9.7 Rollback Strategy → 4.1, 11.1
├── 11.6 Rollback Documented → 9.7
├── 9.4 DB Failure Recovery → 6.7
├── 6.8 NSE Health Check → 6.3
├── 9.5 Stale Data Detection → 3.6, 3.5
├── 10.6 Concurrency Tests → 4.1

Level 3 (depend on Level 2):
├── 9.2 VIX Outage → 6.3, 9.1
├── 9.3 Options Outage → 6.3, 9.1
├── 10.2 Options Caching → 10.4
├── 10.3 Market Rebuild → 10.4, background refresh
├── 11.4 Cron Installation → self-heal.sh update
├── 11.5 Backup Verification → None (independent)
```

### Critical Path

```
4.1 (CRITICAL) → 4.2, 4.3, 4.4 → 9.7 → 11.6
                 → 10.6 (concurrency tests)
                 → 11.1 → 9.7 → 11.6
```

### Natural Groupings

| Group | Findings | Rationale |
|---|---|---|
| **CI/CD Infrastructure** | 4.1, 4.2, 4.3, 4.4 | Foundation for all future changes |
| **Auth & Security Hardening** | 8.1, 8.3, 8.4, 8.5, 8.6, 8.7, 8.8 | Security posture improvement |
| **Failure Recovery & Outage Handling** | 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7, 9.8 | Resilience and graceful degradation |
| **Database Operational Hardening** | 7.2, 7.3, 7.4, 7.5, 7.6 | DB stability and growth management |
| **Data Source Isolation** | 6.3, 6.5, 6.6, 6.7, 6.8 | Per-source health and fallback |
| **Performance Hardening** | 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 10.8 | Scalability and throughput |
| **API Reliability Polish** | 1.5, 1.6, 1.7, 1.8 | Code quality and safety |
| **Deployment Infrastructure** | 11.1, 11.2, 11.3, 11.4, 11.5, 11.6 | Operational maturity |
| **Monitoring Extension** | 3.5, 3.6, 3.8 | Extend Phase A monitoring |

---

## 3. Proposed Phase B Scope

### Phase B: CI/CD & Deployment Foundation (FIRST)

**Priority**: CRITICAL → HIGH
**Rationale**: 4.1 is the only Critical finding. Without CI gates, every subsequent change has no automated safety net. All other phases depend on 4.1 existing.

| Finding | Severity | Effort | Acceptance Criteria |
|---|---|---|---|
| 4.1 No Automated Regression Gates | CRITICAL | M | CI runs pytest on every push; PR merge blocked if tests fail; results stored as artifacts |
| 4.2 No Commit/PR Validation | HIGH | S | Pre-commit hooks run on every commit; `.pre-commit-config.yaml` exists; hooks tested |
| 4.3 No Deployment Safety Check | MEDIUM | S | Post-deploy health check fails → deploy exits non-zero; rollback script tested |
| 4.4 No Staging Environment | MEDIUM | L | Staging VM exists; deploy-vm.sh deploys to staging first; validation documented |

**Tests**: ~10-15 new tests (CI config validation, hook execution, deploy script exit codes)
**Model boundary**: Zero model files affected
**Duration estimate**: 1-2 sprints

---

### Phase C: Auth & Security Hardening

**Priority**: HIGH
**Rationale**: Security posture directly affects production viability. Auth boundary decision affects 8.x findings.

| Finding | Severity | Effort | Dependencies | Acceptance Criteria |
|---|---|---|---|---|
| 8.1 No Auth on Portfolio | HIGH | L | Auth design | Portfolio endpoints require auth; portfolios user-isolated; 401 for unauthenticated |
| 8.3 Debug Mode Enforcement | MEDIUM | S | None | Debug mode explicitly disabled; env var enforced; deployment checklist includes |
| 8.5 nginx Cache Auth Exclusion | MEDIUM | S | 8.1 | nginx config excludes auth endpoints from cache; test validates |
| 8.6 CSRF Protection | MEDIUM | S | 8.1 | CSRF tokens required for state-changing endpoints; Origin header validated |
| 8.7 SQL Injection Analysis | LOW | S | 1.7 | Table names assert against ALLOWED_TABLES; linter rule added |
| 8.8 Error Context Leak | LOW | S | 5.1 (Phase A) | Custom error handlers return JSON; no stack traces; Flask version hidden |
| 8.4 Secrets Management | MEDIUM | L | None | Key rotation documented; secrets not in backup; vm-backup excludes /etc/tradingai/ |
| 1.8 Error Messages Internal | LOW | S | None | Generic error messages in responses; internal details server-side only |

**Tests**: ~15-20 new tests
**Model boundary**: Zero model files affected
**Duration estimate**: 1-2 sprints

---

### Phase D: Failure Recovery & Data Source Isolation

**Priority**: HIGH → MEDIUM
**Rationale**: Production resilience — graceful degradation and outage handling directly affect user experience during data source failures.

| Finding | Severity | Effort | Dependencies | Acceptance Criteria |
|---|---|---|---|---|
| 9.1 Graceful Degradation | HIGH | L | Caching | Cached data served during outage with stale flag; outage alert triggers |
| 6.3 External API Health Tracking | MEDIUM | M | Phase A monitoring | Data status includes success/failure counts; per-source health; alert on consecutive failures |
| 6.5 VIX Isolation | MEDIUM | M | 6.3 | VIX endpoint serves stale data; non-VIX endpoints unaffected; alert on VIX failure |
| 6.6 Options Isolation | MEDIUM | M | 6.3 | Options quality reflects actual data; "DATA UNAVAILABLE" when no data |
| 6.7 DB Graceful Failure | MEDIUM | M | Phase A monitoring | DB failure returns 503; user-friendly message; WAL mode enabled |
| 6.8 NSE Health Check | LOW | S | 6.3 | Live quote staleness monitored; alert >5 min; /api/health includes status |
| 9.2 VIX Outage Fallback | MEDIUM | M | 6.3, 9.1 | Last VIX data served during outage; VIX health check; alert on gap |
| 9.3 Options Outage Fallback | MEDIUM | M | 6.3, 9.1 | Options serve cached data; quality indicator reflects status |
| 9.4 DB Failure Recovery | MEDIUM | S | 6.7 | DB recovery triggers alert; row count verification; corruption alerts |
| 9.5 Stale Data Detection | MEDIUM | M | 3.6, 3.5 | All endpoints include freshness info; stale flag present |
| 9.6 API Restart Behavior | MEDIUM | M | SIGTERM | Graceful shutdown; startup verifies health; restart logged |
| 9.7 Rollback Strategy | MEDIUM | S | 4.1, 11.1 | Rollback script exists; tested; <2 min; last 3 commits reachable |
| 9.8 Request Queuing | LOW | L | Infrastructure | Queue size configured; depth monitored; graceful degradation under spike |

**Tests**: ~25-30 new tests
**Model boundary**: Zero model files affected
**Duration estimate**: 2-3 sprints

---

### Phase E: Database & Performance Hardening

**Priority**: MEDIUM → HIGH
**Rationale**: Scalability and stability under load — essential for production with growing user base.

| Finding | Severity | Effort | Dependencies | Acceptance Criteria |
|---|---|---|---|---|
| 7.2 Connection Pooling | HIGH | M | 6B-1 get_db() | Connection pool implemented; creation time reduced; tests pass |
| 7.3 DB Growth Management | MEDIUM | M | Cleanup cron | Cleanup job runs daily; DB bounded; retention enforced; health includes size |
| 7.4 Concurrent Write Protection | MEDIUM | S | WAL (6B-1) | BEGIN IMMEDIATE for writes; 3-retry on lock errors; no lock errors under load |
| 7.5 _symbol_data Leak Fix | MEDIUM | S | 1.6 (refactor) | try/finally in _symbol_data; connection count stable after error storm |
| 10.1 Backtest Async | CRITICAL | L | Async infra | Backtests run async; 202 Accepted with job ID; API responsive during backtest |
| 10.2 Options Caching | HIGH | M | 10.4 | Options endpoints cached; response <3s; concurrent requests don't degrade |
| 10.3 Market Rebuild | HIGH | L | 10.4, background refresh | No blocking rebuilds; stale data during refresh; 194 tests pass |
| 10.4 Response Caching | MEDIUM | M | TTL config | All endpoints cached by category; hit rate >50%; tests pass |
| 10.5 Pagination | MEDIUM | M | None | All list endpoints paginate; max page_size enforced; total_count included |
| 10.6 Concurrency Tests | MEDIUM | M | 4.1 | 10 concurrent requests complete; no leaks; no corruption |
| 10.8 Query Efficiency | LOW | L | DB schema | Options <3s; composite indexes; batch queries |

**Tests**: ~20-25 new tests
**Model boundary**: Zero model files affected; DB schema changes are operational (indexes, PRAGMA settings)
**Duration estimate**: 2-3 sprints

---

### Phase F: Operational Polish & Monitoring Extension

**Priority**: MEDIUM → LOW
**Rationale**: Code quality, operational maturity, and monitoring depth. Important for maintainability but not blocking.

| Finding | Severity | Effort | Dependencies | Acceptance Criteria |
|---|---|---|---|---|
| 1.5 Bare Except Health | MEDIUM | S | None | No bare except; except Exception with logging |
| 1.6 Impure _symbol_data | MEDIUM | L | Refactoring | _build_market calls shared function; _symbol_data wraps in jsonify |
| 1.7 f-string SQL | MEDIUM | S | ALLOWED_TABLES | Assertions on table names; audit confirms safety |
| 3.5 Deep Health Check | MEDIUM | M | None | Live endpoint: process status; Ready endpoint: DB, data, external APIs |
| 3.6 Data Quality Health | MEDIUM | M | 3.5 | Health includes row counts, date ranges, value sanity |
| 3.8 Distributed Tracing | MEDIUM | L | Phase A correlation ID | Request ID in all logs; consistent across operations |
| 5.5 Log Rotation | LOW | S | 5.1 (Phase A) | Logrotate config exists; daily rotation; 7-day retention |
| 7.6 Chat Cleanup Query | LOW | S | None | Cleanup <1s on 100k rows; tested |
| 9.8 Request Queuing | LOW | L | Infrastructure | Queue configured; monitored; graceful degradation |
| 11.2 Process Supervisor | MEDIUM | S | None | Systemd memory limit; logrotate; memory-based restart tested |
| 11.4 Cron Installation | MEDIUM | S | Self-heal.sh | Self-heal installs crontab; verifies entry count |
| 11.5 Backup Verification | MEDIUM | S | None | Backup age monitored; alert >24h; verification before backup |

**Tests**: ~10-15 new tests
**Model boundary**: Zero model files affected
**Duration estimate**: 1-2 sprints

---

## 4. Explicit Out-of-Scope Items

### Analytical / Model Layer (Authoritative Exclusion)

The following remain outside PHASE 6B-3 authorization per the original scope review and independent review guidance:

- ❌ Confidence calibration indicator population
- ❌ Real RSI/MACD/ADX data population
- ❌ Options historical data (OCHL)
- ❌ 3+ year historical data extension
- ❌ Predictive-integrity reassessment
- ❌ Any changes to RegimeEngine, StrategyEngine, OptionsEngine logic
- ❌ Any changes to quantitative model parameters, thresholds, or formulas
- ❌ Any changes to LLM boundary or prompt logic
- ❌ Scenario normalization changes (frozen at 45f90fc)
- ❌ Backtest methodology changes

### Infrastructure Not in Current Authorization

- ❌ Full async processing infrastructure (Celery/Redis) — only scoped if Phase B includes 10.1
- ❌ Redis/external caching — only in-memory operational metrics (Phase A)
- ❌ Full CI/CD pipeline with branch protection — scoped to Phase B.1 only
- ❌ Security certification or penetration testing
- ❌ Third-party monitoring integration (Sentry, Datadog, etc.) — lightweight self-monitoring only
- ❌ Multi-instance deployment architecture — single VM assumed

---

## 5. Acceptance Criteria (Phase B Aggregate)

### Regression Requirements

| Requirement | Target |
|---|---|
| Existing tests passing | 298/298 (current baseline) |
| New Phase B tests | Per-phase estimate (total ~75-90 new) |
| Model files modified | 0/8 |
| Successful response changes | None |
| Analytical baseline | Unchanged at 45f90fc |

### Model Boundary Protections

| Protection | Mechanism |
|---|---|
| File-level verification | `git diff --name-only` must show 0 model files |
| Import verification | `grep -r "from monitoring\|from logging_config\|import monitoring" backend/regime.py backend/strategies.py ...` — must return nothing |
| Response verification | Health/Price/VIX response structure unchanged |
| Test gate | All 298 existing tests must pass before and after |
| Independent review | Each Phase B sub-phase requires independent review before freeze |

### Operational Criteria

| Criterion | Target |
|---|---|
| CI runs on every push | Yes |
| PR merge blocked on test failure | Yes |
| Deploy fails on health check failure | Yes |
| Rollback completes in <2 minutes | Yes |
| All endpoints have rate limits | Yes (6B-2 already done) |
| All endpoints have per-request timeouts | Yes |
| Monitoring is observational only | Yes |

---

## 6. Implementation Authorization Assessment

### Should Implementation Be Authorized as a Subsequent Step?

**Recommendation**: YES, but with phased authorization.

| Phase | Scope | Authorization |
|---|---|---|
| Phase B.1 | CI/CD Foundation (4.1-4.4) | Recommend IMMEDIATE authorization — Critical gate |
| Phase B.2 | Auth & Security (8.x, 1.x) | Recommend authorization after B.1 |
| Phase B.3 | Failure Recovery (9.x, 6.x) | Recommend authorization after B.2 |
| Phase B.4 | Performance & DB (10.x, 7.x) | Recommend authorization after B.3 |
| Phase B.5 | Operational Polish (3.5+, 5.4+, 11.x) | Recommend authorization after B.4 |

Each sub-phase requires:
1. Independent specification review
2. Independent implementation review
3. Gate verification (all gates pass)
4. Formal freeze decision before proceeding to next sub-phase

### Sequencing Rationale

1. **CI/CD first (4.1-4.4)**: Every subsequent change needs automated safety. 4.1 is the only Critical finding.
2. **Auth before security hardening**: 8.1 (auth) is prerequisite for 8.5 (nginx cache auth), 8.6 (CSRF), 8.8 (error context).
3. **Failure recovery before performance**: Graceful degradation (9.1) must exist before optimizing performance (10.x). A fast API that fails silently is worse than a slow API that communicates clearly.
4. **DB/performance last**: These are optimizations that require stable infrastructure (CI gates, auth, failure recovery) already in place.

---

## 7. Summary

### Phase B Aggregate

| Metric | Value |
|---|---|
| Total findings | 41 (+3.7 effectively covered) |
| Critical | 2 (4.1, 10.1) |
| High | 5 (8.1, 7.2, 9.1, 10.2, 11.1) |
| Medium | ~26 |
| Low | ~10 |
| Proposed sub-phases | 5 (B.1 through B.5) |
| Estimated new tests | 75-90 |
| Model files affected | 0/8 |
| Estimated total effort | 5-8 sprints across all sub-phases |
| First sub-phase | B.1 CI/CD Foundation |

### Next Action

Authorize Phase B.1 (CI/CD Foundation: 4.1-4.4) as the first sub-phase.
All other sub-phases require separate authorization after B.1 completion and freeze.

🔒 STOP boundary remains active at c39af34 until Phase B.1 authorization.
