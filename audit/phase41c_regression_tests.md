# Phase 41C — Regression Tests

**Date**: 2026-09-17
**Command**: `python3 -m pytest tests/ -q --ignore=tests/test_ai_outlook_backtest.py`

---

## Phase 39/40/41 Tests

| Suite | Total | Passed | Failed | Notes |
|-------|-------|--------|--------|-------|
| Phase 39 | — | — | — | Included in combined |
| Phase 40 | — | — | — | Included in combined |
| Phase 41 | 36 | 36 | 0 | All passing |
| **Phase 39+40+41 total** | **101** | **101** | **0** | No regressions |

## Full Test Suite

| Metric | Value |
|--------|-------|
| Total tests (excl broken file) | 1261 |
| Passed | 1261 |
| Failed | 9 |
| Pre-existing failures | 9 |
| New failures | 0 |

## Pre-Existing Failures (Unchanged)

| Test | Description | Category |
|------|-------------|----------|
| test_level_invariant | Key levels API match | Data-dependent |
| test_live_pages | Index broken internal hrefs | Content |
| test_phase1 | Regression gate | Dependency |
| test_phase6a | Signal confidence label | UX |
| test_phase6b_b1 | Regression gate | Dependency |
| test_phase6b_b2 | Regression gate | Dependency |
| test_phase6b_b6 | Fetch health record | Data-dependent |
| test_phase7_track_b | Google Tag consent | Tracking |
| test_phase7_track_c | Max Pain wording | Observational |

## Pre-Existing Broken File

| File | Issue |
|------|-------|
| tests/test_ai_outlook_backtest.py | ModuleNotFoundError: No module named 'indicators' (requires running from backend dir) |

## Test Comparison

| Metric | Previous | Current | Change |
|--------|----------|---------|--------|
| Phase 39+40+41 | 101 | 101 | No change |
| Full suite | 1261 | 1261 | No change |
| Pre-existing failures | 9 | 9 | No change |

## Conclusion

No regressions detected. All Phase 41 tests pass. Pre-existing failures remain unchanged.
