# Test Plan Scoping — TradingAI.in Live Market Readiness

User spec: 25 suites, ~600 tests, 15 gates (INF through OBS + SCENARIO + INV + RELEASE).

## 1. Infrastructure Assessment

| Tool | Available | Use |
|------|-----------|-----|
| Flask test_client | ✅ | API endpoint testing (status, schema, data) |
| pytest | ✅ | Backend unit/integration tests |
| curl/wget | ✅ | HTTP checks, redirect chains |
| Python + requests | ✅ | Data freshness, consistency checks |
| Browser automation | ❌ | No Playwright/Selenium installed |
| VM SSH access | ⚠️ | Requires manual creds |
| Load testing (k6/locust) | ❌ | Not available |

## 2. PHASE 1 — Must-Build (Release Blocking)

These tests directly correspond to release acceptance criteria: "0 P0 failures, 0 unresolved P1, 0 data-integrity violations."

### 2.1 API Infrastructure (INF + NET + API suites, ~70 tests)
Build: `tests/test_live_infra.py`

| Test ID | What | Tool |
|---------|------|------|
| INF-001 | VM reachable | curl |
| INF-005 | DB reachable | Python sqlite3 |
| INF-006 | DB reads | Python sqlite3 |
| INF-007 | DB writes | Python sqlite3 |
| INF-012 | Nginx running | curl http://localhost |
| INF-014 | Market fetch job | API /api/market check |
| NET-001 | HTTP→HTTPS redirect | curl -I http |
| NET-002 | HTTPS cert valid | openssl s_client |
| NET-004 | HSTS present | curl -I https |
| NET-014 | API proxied | curl https /api/market |
| NET-016 | 404 page renders | curl /nonexistent.html |
| API-001 | All endpoints 200 | pytest loop |
| API-002 | Valid JSON | pytest json() |
| API-005 | Required fields exist | pytest assert |
| API-008 | Null handled | pytest assert |
| API-015 | API latency | time.perf_counter |
| API-019 | Correct instrument | pytest assert |
| API-020-023 | NIFTY/BANKNIFTY/FINNIFTY/SENSEX correct | pytest assert |
| API-030 | No frontend-generated authoritative values | pytest assert |

### 2.2 Page Availability + Links (PAGE + LINK suites, ~45 tests)
Build: `tests/test_live_pages.py`

| Test ID | What | Tool |
|---------|------|------|
| PAGE-001-013 | Every page 200 | pytest + requests |
| PAGE-014 | 404 works | curl |
| PAGE-017 | No indefinite loading | Flask test_client + JS-free check |
| PAGE-018 | No blank page | HTML length check |
| PAGE-019 | No JS fatal error | Requires browser (defer) |
| LINK-001-020 | All internal links resolve | Python link extractor |

### 2.3 Data Freshness + Consistency (DATA + CONS suites, ~60 tests) — **P0 CRITICAL**
Build: `tests/test_live_consistency.py`

| Test ID | What | Tool |
|---------|------|------|
| CONS-001-008 | Ticker=API=Market=Outlook per instrument | pytest + API |
| CONS-009-018 | Regime/confidence/support/resistance/PCR/max-pain/strategy/risk consistent across sections | pytest + API |
| CONS-029-030 | Unavailable values use `—` not 0 | pytest |
| INV-001-020 | Data integrity invariants | pytest (hard asserts) |
| DATA-001-003 | Timestamp valid/future/advancing | API timestamp check |
| DATA-005-007 | Stale detection + labelling | data_quality module |
| DATA-008-013 | Price sanity (numeric, range, no NaN/Infinity/negative) | pytest |
| DATA-022-023 | Timestamp preserved across layers | API comparison |

### 2.4 Prerender (PRE suite, ~15 tests)
Build: `tests/test_live_prerender.py`

| Test ID | What | Tool |
|---------|------|------|
| PRE-001 | Valid API creates snapshot | Run prerender_snapshot.py |
| PRE-002 | Empty API doesn't overwrite | Run with mock empty API |
| PRE-007 | Existing snapshot remains valid | Check file timestamp |
| PRE-010 | Stale snapshot identifiable | Check stamp age |
| PRE-012 | No blank page after failed prerender | Check index.html length |
| PRE-014 | Prerender doesn't modify Track A data | Diff check |

### 2.5 Data Integrity Invariants (INV suite, 20 tests) — **HARDCODE ASSERTIONS**
Build: `tests/test_data_integrity.py` (import into existing pytest)

All 20 invariants as Python asserts. These are non-negotiable.

## 3. PHASE 2 — High Priority (Pre-Live)

### 3.1 AI Outlook (AI suite, ~35 tests)
| Test ID | Category | Tool |
|---------|----------|------|
| AI-001-004 | Initial outlook generation | Flask test_client |
| AI-005-008 | Bullish/Bearish/Sideways interpretation | pytest + regime engine |
| AI-016-021 | LLM failure modes | Mock LLM |
| AI-022-024 | No stale banners/loading | pytest |
| AI-025-029 | AI narrative bounds | pytest |
| AI-030-035 | Material change trigger | market_change.analyze() |

### 3.2 Regime + Strategy (REG + STRAT, ~50 tests)
| Test ID | Category | Tool |
|---------|----------|------|
| REG-001-010 | All 6 transitions | pytest + regime engine |
| REG-011-020 | Old value removal + stability | pytest |
| STRAT-001-030 | Strategy generation conditions | pytest + strategies module |

### 3.3 Loading/Recovery (LOAD, ~25 tests)
| Test ID | What | Tool |
|---------|------|------|
| LOAD-001-004 | Normal/timeout/500/exit | Flask test_client |
| LOAD-005-008 | AI timeout/null/exit | Mock |
| LOAD-015-016 | One failure doesn't block others | pytest |
| LOAD-019-025 | No infinite loading | pytest |

### 3.4 Frontend Rendering (UI, ~30 tests)
| Test ID | What | Tool |
|---------|------|------|
| UI-001-009 | Critical sections render | Flask test_client HTML |
| UI-012 | No duplicate IDs | HTML parser |
| UI-022 | Unavailable = `—` | HTML check |
| UI-026-030 | Usability under failure | Flask + partial data |

## 4. PHASE 3 — Medium Priority (Post-Live Monitoring)

### 4.1 Indicators (IND, ~25 tests) — build `tests/test_indicators.py`
SMA/MACD/RSI/ADX/PCR/breadth calculation correctness.

### 4.2 Options Intelligence (OPT, ~35 tests) — build `tests/test_options.py`
PCR, max pain, OI, IV, expiry handling, malformed data.

### 4.3 Performance (PERF, ~25 tests) — requires k6/locust (not available)
API latency under load, concurrent users, memory leak check.

### 4.4 Failure Injection (FAIL, ~30 tests) — build `tests/test_failures.py`
Mock API failures, DB unavailable, network disconnect.

### 4.5 Trading Session Endurance (SESSION, ~25 tests) — manual/live
Run through full trading day. Cannot be automated without scheduling.

### 4.6 Data Source Recovery (SOURCE, ~20 tests) — build `tests/test_source.py`
Source switching, recovery, timestamp preservation.

### 4.7 Deployment/Rollback (DEPLOY, ~20 tests) — build `tests/test_deploy.py`
Commit matching, Track A/B/C boundaries, rollback test.

### 4.8 Security (SEC, ~20 tests) — build `tests/test_security.py`
Headers, secrets, injection, path traversal.

### 4.9 SEO/AdSense (ADS, ~20 tests) — manual checklist
Privacy/Terms accessibility, ad behavior.

### 4.10 Browser/Mobile (BROWSER, ~25 tests) — requires browser automation
Chrome/Safari/Edge, mobile widths, responsive layout.

## 5. Critical Scenarios (SCENARIO, 15 tests)
Build: `tests/test_scenarios.py`

| Scenario | Can Test? | Tool |
|----------|-----------|------|
| Normal bullish day | ✅ | pytest + regime engine |
| Normal bearish day | ✅ | pytest + regime engine |
| Sideways day | ✅ | pytest + regime engine |
| Sharp market fall | ✅ | Inject data + check reassessment |
| Sharp market rally | ✅ | Inject data + check reassessment |
| VIX shock | ✅ | Inject VIX + check risk change |
| Support breakdown | ✅ | Inject data + check outlook |
| Resistance breakout | ✅ | Inject data + check outlook |
| False breakout | ✅ | Inject data + check recovery |
| Rapid whipsaw | ✅ | Inject rapid changes |
| AI unavailable | ✅ | Mock LLM failure |
| Entire data source unavailable | ✅ | Mock API failure |
| One index unavailable | ✅ | Mock single failure |
| DB temporarily unavailable | ⚠️ | Requires DB mock |
| Browser loses network | ❌ | Requires browser automation |

## 6. Test Implementation Priority Matrix

| Priority | Suites | Tests | Effort | Timeline |
|----------|--------|-------|--------|----------|
| 🔴 P0 | INF+NET+API+DATA+CONS+INV+PRE | ~170 | Medium | Week 1 |
| 🔴 P0 | PAGE+LINK | ~45 | Low | Week 1 |
| 🟠 P1 | AI+REG+STRAT+LOAD+UI | ~145 | High | Week 2-3 |
| 🟡 P2 | IND+OPT+FAIL+SOURCE | ~110 | High | Week 4-5 |
| 🟢 P3 | PERF+BROWSER+SEC+ADS+DEPLOY+OBS+SESSION | ~130 | Very High | Week 6+ |
| **Total** | | **~600** | | |

## 7. Key Dependencies

1. **Browser automation**: Need Playwright/Selenium for UI, BROWSER, some LOAD tests
2. **Load testing**: Need k6 or locust for PERF suite
3. **VM access**: Need SSH for INF-001, INF-002, INF-003, INF-004, INF-008, INF-012-017, OBS
4. **Mock infrastructure**: Need to build mock decorators for FAIL, SOURCE, AI-016-021 tests
5. **LLM mock**: Need to mock gpt calls for AI failure mode tests

## 8. Recommended Immediate Actions

1. **Week 1**: Build P0 test suite (~215 tests) — these are release blocking
2. **Week 2**: Extend to P1 (~145 more tests)
3. **Week 3**: Run P0+P1 against live VM for 1 trading session
4. **Week 4+**: Phase 3 suites as infrastructure allows
5. **Ongoing**: SESSION tests via manual daily checklist during market hours
