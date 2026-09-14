# PHASE 6B-3 B.6 — Scope Review (Production Hardening, Round 4)

**Status**: 🟡 REVIEW — awaiting approval. No implementation authorized.

**Position**: `45f90fc` 🔒 → `d4990e4` 🔒 (B.4) → `4b7260f` 🔒 (B.5) → **B.6 proposed**

**Method**: every finding in `PHASE6B_PRODUCTION_HARDENING_AUDIT.md` reconciled against
B.1–B.5 evidence (code/tests verified, not doc claims). Live-deployment gaps from the
B.5 VM hardening cycle assessed. Nothing is auto-carried into B.6.

---

## 1. Reconciliation — full finding disposition

Legend: ✅ addressed (no action) · 🟡 partial (remainder evaluated below) · 🔴 open.

### Dim 1 — API Reliability

| ID | Finding | Disposition | Evidence |
|---|---|---|---|
| 1.1 | Inconsistent error schema | 🟡 ~20 legacy `jsonify({"error"})` remain | `api_server.py:955` envelope exists; remains at 537,603,644,666,688,693,1074,1100,1134,1150,1521 |
| 1.2 | DB connection timeout | ✅ | `db_pool.py:50,53`, WAL + `busy_timeout` everywhere; `test_phase6b_1.py:37,48` |
| 1.3 | Connection leaks on error paths | 🟡 hot paths fixed; regime/strategy paths still raw `conn.close()` without try/finally | `api_server.py:996-1064` fixed; `regime:1069`, `strategy:1095` leak pool slots |
| 1.4 | Partial-data behavior | 🟡 `_data_completeness` used on main paths; list/error paths bare | `api_server.py:933,1054,2048`; `test_phase6b_b3.py:72` |
| 1.5 | Bare excepts in health | ✅ | zero `except:` in `api_server.py`; `test_phase6b_b2.py:64` |
| 1.6 | Impure `_symbol_data` via `test_request_context` | 🔴 untouched | `api_server.py:2038-2040` cold-miss path |
| 1.7 | f-string SQL | 🟡 `sql_guard` enforced at 2 sites only | `sql_guard.py:3,13`; unguarded at `api_server.py:298,311,358`, `database.py:293`, `data_fetcher_db.py:1009-1015` |
| 1.8 | Error detail leaks | 🟡 500→INTERNAL_ERROR + 503 mapping done; input echoes remain | `api_server.py:984,199-202`; echoes at 693, 991, 1521 |

### Dim 2 — Rate Limiting & Abuse

| ID | Finding | Disposition | Evidence |
|---|---|---|---|
| 2.1 | Rate limiting | ✅ | Limiter tiers `api_server.py:57-62,1712,1737,1762`; `test_phase6b_2.py:32-60` |
| 2.2 | CORS wide open | ✅ boundary (allowlist + nginx no-cache); CSRF remainder → separate track | `api_server.py:47-53`; zero `csrf` hits in `backend/` |
| 2.3 | No authentication | ✅ portfolio Bearer + isolation; public data open by design | `api_server.py:228-238`; `test_phase6b_b2.py:96-108` |
| 2.4 | Request size limits | ✅ | `MAX_CONTENT_LENGTH=1MB`; `api_server.py:55,173-175` |
| 2.5 | Request timeout enforcement | 🟡 **ineffective in prod**: SIGALRM skipped in gthread workers (B.5 `8a7a625` guard) | `api_server.py:67-114`; hung worker held to 90s gunicorn timeout only |

### Dim 3 — Monitoring & Alerting

| ID | Finding | Disposition | Evidence |
|---|---|---|---|
| 3.1 | Latency tracking | ✅ | timing middleware + `/api/metrics`; `test_phase6b_3_pea.py:57,66,211` |
| 3.2 | Failure counter | ✅ | counts + sustained-failure alerts in `/metrics:alerts` |
| 3.3 | Latency alerts | 🟡 in-app only; no external probe | `monitoring.py:132-149`; nothing in `ops/*.txt`, crontab |
| 3.4 | Alert thresholds not configured | 🔴 thresholds hardcoded, no central config | `monitoring.py:100-101`, `alert.py:154-159`; no `config/alerting.json` |
| 3.5 | Deep health | 🟡 done; no live/ready split | B.5 frozen; only `/health` + `/metrics` |
| 3.6 | Freshness depth | ✅ | B.5 frozen |
| 3.7 | Plain-text logs | ✅ | `logging_config.py:13-38` JSON formatter |
| 3.8 | Tracing | ✅ sufficient (correlation_id + X-Correlation-ID); distributed tracing not needed single-process | `test_phase6b_3_pea.py:229` |
| 3.9 | Central error tracking | 🟡 in-app counters only, process-local | Separate decision (Sentry = third-party dependency) |
| 3.10 | Pipeline visibility | 🟡 `data_status` + `_record_fetch_result` exist but schemas mismatched | `api_server.py:331-348` vs `db_schema:325` |

### Dim 4 — CI/CD

| ID | Finding | Disposition | Evidence |
|---|---|---|---|
| 4.1 | Regression gates | ✅ | `.github/workflows/regression.yml`; `test_phase6b_b1.py:23-55` |
| 4.2 | Commit/PR validation | ✅ | `.pre-commit-config.yaml`; `test_phase6b_b1.py:63-127` |
| 4.3 | Deploy safety | ✅ | `ops/health_gate.sh`, `ops/rollback.sh`; `test_phase6b_b1.py:133-161` |
| 4.4 | Staging environment | 🟡 documented only, no live host | `ops/DEPLOYMENT.md:21`; single-VM deploys → infra/cost decision |

### Dim 5 — Observability

| ID | Finding | Disposition | Evidence |
|---|---|---|---|
| 5.1 | Structured logging | ✅ core done (fetcher plain-log remainder cosmetic) | `logging_config.py:13-38` |
| 5.2 | Metrics endpoint | ✅ | `api_server.py:244-259` |
| 5.3 | Timing middleware | ✅ (negative-ms + dead-block blemishes cosmetic, non-blocking) | `api_server.py:106-164` |
| 5.4 | Error log context | ✅ API-side done | `api_server.py:140-143`, `X-Correlation-ID` |
| 5.5 | Log rotation | ✅ | B.5 frozen, installed on VM |

### Dim 6 — Data-Source Failures

| ID | Finding | Disposition | Evidence |
|---|---|---|---|
| 6.1 | Circuit breaker | 🟡 **class exists, zero production call sites** | `circuit_breaker.py:9`; never instantiated |
| 6.2 | Retry with backoff | 🟡 wired only to `_fetch_yf_ohlcv_raw`; bhavcopy/nse_fo/fo_fetcher single-try | `data_fetcher_db.py:67` |
| 6.3 | External API health tracking | 🟡 plumbing in `/metrics`, called only by tests | `monitoring.py:43-53` |
| 6.4 | yfinance fallback | 🟡 stale-with-flags + live→1m→1d chain; no alternate provider | Separate vendor decision for provider #2 |
| 6.5 | VIX isolation | ✅ | `test_vix_stale_flagged`, isolation tests |
| 6.6 | Options isolation | ✅ | `api_server.py:1377`; isolation tests |
| 6.7 | DB failure handling | ✅ | 503 mapping + write retry; `test_503_on_db_failure` |
| 6.8 | NSE live health | ✅ | thresholds + age gate + freshness |

### Dim 7 — DB & Resource Stability

| ID | Finding | Disposition | Evidence |
|---|---|---|---|
| 7.1 | WAL mode | ✅ | PRAGMA everywhere; `test_wal_mode_enabled` |
| 7.2 | Pooling | ✅ | `db_pool.py`; pool in `/api/health` |
| 7.3 | Growth management | 🟡 **cleanup.sh exists but unscheduled, narrow, no size signal** | absent from crontab + deploy cron block |
| 7.4 | Concurrent write protection | 🟡 `_execute_write` for portfolio/chat only; `Database.execute` + fetcher writers lack it | `api_server.py:937-952` vs `database.py:252` |
| 7.5 | `_symbol_data` conn close | ✅ | try/finally; `test_no_connection_leaks_under_load` |
| 7.6 | Chat cleanup subquery | 🟡 wrapped in retry, not rewritten; small-scale test only | `api_server.py:2317,2322,2349` |

### Dim 8 — Security

| ID | Finding | Disposition | Evidence |
|---|---|---|---|
| 8.1 | Portfolio auth | ✅ | Bearer + isolation tests |
| 8.2 | Portfolio input validation | ✅ | `validate_portfolio_payload`; B.2 verified |
| 8.3 | Debug import | ✅ | assert + `debug=False` |
| 8.4 | Secrets in /etc/tradingai | 🟡 600 perms, out of git/backup; rotation undocumented | Separate decision (vault = infra) |
| 8.5 | nginx stale-auth cache | ✅ | `proxy_no_cache` portfolio locations |
| 8.6 | CSRF | 🔴 untouched, explicitly deferred | Separate cross-stack track (needs frontend token plumbing) |
| 8.7 | SQL injection | 🟡 same remainder as 1.7 | see 1.7 |
| 8.8 | Error context leak | 🟡 same remainder as 1.8 | see 1.8 |

### Dim 9 — Failure/Recovery

| ID | Finding | Disposition | Evidence |
|---|---|---|---|
| 9.1 | Market-data degradation | 🟡 flags+TTL done; outage-beyond-TTL → 404, no extended last-known-good | `api_server.py:411-433,517-535` |
| 9.2 | VIX fallback | ✅ (gap-alert remainder folded into 3.3 probe) | STALE-flag + isolation |
| 9.3 | Options fallback | 🟡 truthful labeling done; no cached last-known serving | `api_server.py:1377` |
| 9.4 | DB recovery | 🟡 restore+restart log-only; no alert, no row-verify | `self-heal.sh:51-58` |
| 9.5 | Stale detection | 🟡 main endpoints covered, not all | B.3 tests; remainder folded into H below |
| 9.6 | Restart behavior | 🟡 Restart=always done; no readiness gate / drain beyond gunicorn default | pairs with 3.5 split |
| 9.7 | Rollback | 🟡 HEAD~1 + restart + verify documented; no DB rollback, no canary | `ops/rollback.sh`; process decision for more |
| 9.8 | Request queuing | 🔴 no queue limit/depth signal | 3×2 gthread workers; B.4 G7 passed — complexity not justified on 1GB VM |

### Dim 10 — Performance

| ID | Finding | Disposition | Evidence |
|---|---|---|---|
| 10.1 | Blocking backtest | ✅ | async 202 + poll; equivalence test |
| 10.2 | Options cost | 🟡 TTL cache + 60.9% benchmark; options-intel uncached, per-expiry loops | `cache.py:18-19`; `api_server.py:1359-1392` |
| 10.3 | Market rebuild | 🟡 warm path non-blocking; cold miss still sync via `test_request_context` | `api_server.py:1934-2048` |
| 10.4 | Caching | 🟡 framework done; subset decorated (e.g. etf uncached) | `cache.py`, `api_server.py:411-436,1927` |
| 10.5 | Pagination | 🟡 key lists done; not all (e.g. `/api/etf` LIMIT 50) | `api_server.py:378-401` |
| 10.6 | Concurrency | ✅ | `test_10_concurrent_requests`; B.4 G7 |
| 10.7 | Per-endpoint timeout | 🟡 same as 2.5 (unenforced in prod) | see 2.5 |
| 10.8 | Query efficiency | 🟡 indexes + retry done; per-expiry loops remain | pairs with 10.2 |

### Dim 11 — Deployment

| ID | Finding | Disposition | Evidence |
|---|---|---|---|
| 11.1 | Deploy health check | ✅ | `ops/health_gate.sh`; gate PASS live |
| 11.2 | Process supervisor | ✅ | B.5 frozen, live on VM |
| 11.3 | Deploy logging | 🟡 JSON done but `/tmp/deploy.log` (ephemeral) | `deploy-vm.sh:12-20` |
| 11.4 | Cron install | ✅ | B.5 frozen |
| 11.5 | Backup verify | 🟡 gzip/age done; 7d vs 24h, no row-compare | `self-heal.sh:124-155` |
| 11.6 | Rollback docs | ✅ | `DEPLOYMENT.md:15-19`, `ops/rollback.sh` |

---

## 2. Live-deployment gaps (B.5 VM cycle) — all closed

`flask-limiter` dep · gthread SIGALRM · gate quoting/timing · backfill cascade ·
depth-check isolation · `Row.get` 500s · Flask/Werkzeug mismatch · outlook `date` column ·
`.gz` backup check · nginx `limit_req_zone`. No open live gaps remain; system healthy
(`deep_health all_healthy: true`, public 200). These do not create B.6 scope.

## 3. Threat assessment — does anything endanger the production boundary?

No immediate threat (system healthy, 446/446 live). Three genuine risks justify a B.6:
1. **Timeouts unenforced in prod** (2.5/10.7) — a hung upstream call holds a worker to the 90s gunicorn timeout; with 6 workers, a slow upstream can stall the API.
2. **No circuit breaker in production paths** (6.1/6.3) — prolonged yfinance/NSE outage ties up workers silently.
3. **DB growth unmanaged** (7.3) — unscheduled cleanup is the likeliest disk-full path.

---

## 4. Recommended B.6 scope — "Reliability Core" (9 items, all backend/ops-only)

| # | Work | Findings | Rationale |
|---|---|---|---|
| B6.1 | Thread-safe timeout enforcement (deadline checks that work in gthread workers) | 2.5, 10.7 | Risk #1; B.5's guard exposed the gap |
| B6.2 | Wire circuit breaker + external-health recording into yfinance/NSE fetch paths | 6.1, 6.3 | Risk #2; classes already exist |
| B6.3 | Schedule `cleanup.sh` (cron + deploy block), add DB-size to `/api/health` | 7.3 | Risk #3; cheapest high-value item |
| B6.4 | try/finally connection close on remaining raw paths (regime/strategy) | 1.3 | Pool-exhaustion risk, small |
| B6.5 | `sql_guard` coverage for remaining dynamic table names | 1.7, 8.7 | Small, mechanical |
| B6.6 | Backup threshold 7d→24h + live-vs-backup row compare; row-verify on DB restore | 11.5, 9.4 | Small, closes recovery loop |
| B6.7 | Unify `data_status` schemas + consecutive-failure visibility | 3.10 | Small, monitoring correctness |
| B6.8 | Centralized alert-threshold config (`config/alerting.json`) | 3.4 | Small, removes hardcoding |
| B6.9 | Liveness/readiness split (`/api/ready` incl. DB check) + startup readiness gate | 3.5 rem, 9.6 | Small, deploy/restart safety |

Estimated shape matches B.5 (6 items) / B.4 (13 items): 9 small items, ~20 tests.

## 5. Explicitly NOT in B.6

| Item | Disposition | Reason |
|---|---|---|
| 8.6 CSRF | Separate cross-stack track | Needs frontend token plumbing; backend-only half-measure adds false assurance. Requires architectural decision. |
| 4.4 Live staging VM | Separate infra/cost decision | No code can create a second VM. |
| 3.9 Sentry / central tracking | Separate dependency decision | Third-party service + DSN handling. |
| 6.4 Second provider | Separate vendor/cost decision | No code substitute for a provider contract. |
| 8.4 Secrets vault | Deferred (600 perms + out-of-git sufficient for single VM) | Vault is infra; document rotation instead (docs task, not B.6). |
| 9.8 Request queuing | Deferred with rationale | B.4 G7 passed; queue machinery unjustified on 1GB VM / 6 workers. Revisit only on observed saturation. |
| 9.7 Rollback beyond HEAD~1 / DB rollback / canary | Deferred (process) | Current <2min rollback verified; more is process, not code. |
| 9.1/9.3 Extended last-known-good serving | Deferred to B.7 candidate | Touches stale-serving truthfulness boundary; needs its own spec care, not bundled. |
| 1.1/1.4/8.8 Error-schema completion + echo sanitization | Deferred to B.7 candidate | User-visible consistency work; safe but sizable (~20 endpoints); deserves dedicated review. |
| 10.2/10.4/10.5/10.8 Cache + pagination + options-loop remainder | Deferred to B.7 candidate | Perf follow-up; B.4 benchmarks already captured the bulk win. |
| 6.2 Retry for bhavcopy/nse_fo/fo_fetcher | Deferred to B.7 candidate | Small but lower risk-reduction than B6.2. |
| 3.3 External latency probe | Deferred to B.7 candidate | Nice-to-have; in-app detection exists. |
| 11.3 Deploy log persistent path | Deferred to B.7 candidate (one-line) | Trivial; bundle with B.7 to keep B.6 focused. |
| 1.6 `_symbol_data` purity refactor | Deferred with rationale | Hot-path refactor for code cleanliness alone; cold-miss path works and is tested. Risk without production need. |
| 7.4/7.6 Write-path + chat-cleanup remainder | Deferred | Covered paths verified under load; remainder is low-traffic. |

## 6. Protected boundaries (B.6 must preserve)

- `45f90fc` analytical baseline · `d4990e4` B.4 freeze · `4b7260f` B.5 freeze
- 0/8 model-file changes · no RegimeEngine / StrategyEngine / OptionsEngine changes
- No confidence/threshold, backtest-methodology, or analytical-tuning changes
- DATA UNAVAILABLE / STALE / PARTIAL / SYSTEM DEGRADED semantics preserved
- Observational-only monitoring; no trading-behavior changes

## 7. Recommended lifecycle

B.6 Scope Review (this doc) → **STOP → Approval** → B.6 Specification → STOP →
Authorization → Implementation → Acceptance → Independent Review → Freeze

---

🛑 **STOP — B.6 Scope Review complete. No implementation authorized. Awaiting approval,
amendment, or rejection of the recommended 9-item scope and the deferral list.**
