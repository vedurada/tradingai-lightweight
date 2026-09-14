# PHASE 6B-3 B.3 — Independent Specification Review

**Status**: SPECIFICATION REVIEW — AWAITING REVIEWER DECISION

**Specification**: `PHASE6B_STEP3_B3_SPECIFICATION.md`

**Frozen boundary**: `cdf0f6a` 🔒

**Regression baseline**: 350/350

---

## 1. Reviewer Checklist

Each of the 13 findings must be traced through:

```
Finding → implementation location → state transition → user-visible behavior → recovery condition → test → regression gate
```

### Trace Matrix

| # | Finding | Part | Implementation | State Transition | User Behavior | Recovery | Test | Regression |
|---|---|---|---|---|---|---|---|---|
| A1 | 9.1 Graceful degradation | A | `data_quality.py`, `_enrich_with_freshness` | LIVE → DATA UNAVAILABLE/STALE → LIVE | Data quality labels on all endpoints | Provider recovery + freshness verify | `test_fresh_data_live`, `test_stale_data_stale`, etc. | 350 pass |
| A2 | 6.4 yfinance fallback | A | `_enrich_with_freshness` + cache | LIVE → STALE → LIVE | Last-known data with stale flag | Cron retry + freshness verify | `test_stale_data_stale` | 350 pass |
| A3 | 1.4 Partial data | A | `data_completeness` field | LIVE → PARTIAL → LIVE | Missing sources listed | All sources recover | `test_partial_data_completeness` | 350 pass |
| B1 | 6.5 VIX isolation | B | `_check_vix_freshness` | LIVE → STALE (VIX only) → LIVE | VIX flagged; other endpoints ok | VIX source recovers | `test_vix_stale_flagged`, `test_vix_unavailable_does_not_affect_price` | 350 pass |
| B2 | 6.6 Options isolation | B | `_options_data_quality` | LIVE → DATA UNAVAILABLE → LIVE | Quality accurate, other endpoints ok | Options source recovers | `test_options_unavailable_labeled`, `test_options_failure_isolated` | 350 pass |
| B3 | 6.3 API health tracking | B | `data_status` columns, `_record_fetch_result` | N/A (observability) | Error counts visible | — | `test_success_count_increments`, `test_consecutive_failure_alert` | 350 pass |
| C1 | 9.4 DB recovery | C | `get_db()` handler, `_handle_db_error` | OK → DB UNAVAILABLE (503) → OK | "Service temporarily unavailable" | self-heal + integrity + row count verify | `test_db_corruption_returns_503`, `test_db_recovery_verified` | 350 pass |
| C2 | 6.7 DB not handled | C | Same as C1 (unified) | Same as C1 | Same as C1 | Same as C1 | Same as C1 | 350 pass |
| D1 | 9.5 Stale data comms | D | Per-endpoint freshness + health sources | LIVE → STALE → LIVE | "Data is X minutes old" | Freshness verified | `test_health_reports_source_status`, `test_api_available_not_data_valid` | 350 pass |
| D2 | 6.8 NSE live health | D | Health + alert in D.1 | N/A (covered by D.1) | Live quotes status in health | Cron retry | Covered by D.1 tests | 350 pass |
| E1 | 9.6 Restart behavior | E | SIGTERM handler, startup check, self-heal verify | OK → SHUTDOWN → STARTUP CHECK → OK | Graceful, logged | Systemd restart | `test_startup_verification`, `test_sigterm_graceful` | 350 pass |
| E2 | 9.7 Rollback | E | `ops/rollback.sh` | Bad deploy → ROLLBACK → HEALTHY | < 2 min rollback | Re-run | `test_rollback_script_exists`, `test_rollback_completes_under_2min` | 350 pass |
| E3 | 6.8 NSE health | E | Same as D.2 | — | — | — | Covered by D.2 tests | 350 pass |

---

## 2. Critical Verifications

The independent reviewer must explicitly verify:

### 2.1 Data Integrity

| Rule | How Verified |
|---|---|
| Stale-data enrichment cannot alter regime/strategy/confidence | `test_no_manufactured_values` — simulate data unavailable, confirm no new analytical values in any response |
| PARTIAL never silently treated as LIVE | All responses include `data_quality` or `data_completeness`; PARTIAL has distinct value |
| Recovery requires freshness verification | State transition diagram requires "fresh data verified" before LIVE; test confirms |

### 2.2 Failure Isolation

| Rule | How Verified |
|---|---|
| VIX failure doesn't affect price/market/strategy | `test_vix_unavailable_does_not_affect_price`, `test_vix_unavailable_does_not_affect_market` |
| Options failure doesn't affect non-options | `test_non_options_unaffected` |
| 503 doesn't become successful intelligence | `test_db_corruption_returns_503` — response is 503 with `SERVICE_DEGRADED`, never 200 |

### 2.3 Model Layer Protection

| Rule | How Verified |
|---|---|
| No B.3 code modifies model files | `git diff cdf0f6a HEAD --name-only` — no model files |
| Rollback/shutdown scripts cannot modify model files | Script review: `ops/rollback.sh` only does git checkout + restart |
| No B.4 performance work in B.3 | Check all new code against B.4 scope (caching, pagination, async, query optimization) |

### 2.4 Regression Gate

| Rule | How Verified |
|---|---|
| 350 existing tests mandatory | Test run: `python3 -m pytest tests/ -q` — must show 350 passed |
| All 32 new tests pass | Test run: `python3 -m pytest tests/test_phase6b_b3.py -q` |
| No model files modified | `git diff --name-only` check |

---

## 3. Scope Boundary Verification

| In B.3 | Not in B.3 | Rationale |
|---|---|---|
| Graceful degradation | Circuit breaker extension | 6B-1 has circuit breaker |
| Failure isolation | Performance optimization | B.4 scope |
| DB recovery | Monitoring instrumentation | 6B-3 scope |
| Stale data comms | Rate limiting / CORS / Auth | B.2 scope |
| Operational recovery | Analytical behavior changes | NEVER |
| 32 new tests | Request queuing | TBD → B.4 |

---

## 4. Concerns for Reviewer

1. **PARTIAL → LIVE transition**: Must verify freshness, not just "provider responding." A provider can respond with bad data.
2. **Cache serving during outage**: Last-known-good data is served. Need clear audit trail that this is cached, not fresh.
3. **503 handler scope**: `sqlite3.OperationalError` handler covers all DB failures. Ensure it doesn't accidentally catch unrelated errors.
4. **Rollback script**: `git checkout` + `pip install` + `systemctl restart` — verify this works in production environment, not just dev.
5. **Graceful shutdown**: SIGTERM handling requires Flask/Gunicorn cooperation. Verify actual behavior under load.
6. **32 new tests**: Ensure test coverage for all 5 state transitions, not just normal paths.

---

## 5. Verdict

| Option | Status |
|---|---|
| **APPROVE** → explicitly authorize B.3 implementation | Awaiting reviewer |
| **REVISE** → update specification | Awaiting reviewer |

**Reviewer**: User (independent decision)
**Date**: 2026-09-14
**Boundary**: 🔒 `cdf0f6a` — 350/350

---

## 6. Decision Record

| Decision | Date | Notes |
|---|---|---|
| | | |

---

*End of PHASE 6B-3 B.3 Independent Specification Review. Awaiting reviewer decision.*
