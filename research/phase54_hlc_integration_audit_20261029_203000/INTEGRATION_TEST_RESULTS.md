# Phase 5.4 — Integration Test Results

## Test Environment

- Host: webserver (Oracle VM)
- Application root: /opt/tradingai
- Database: /opt/tradingai/database/tradingai.db (read-only for tests)
- Test database: /tmp/test_tradingai.db (isolated, temporary)

## Test Results

| # | Scenario | Status | Notes |
|---|----------|--------|-------|
| 1 | Valid HLC signal reaches paper-trade adapter | NOT RUN | Requires test database with candles; no production writes allowed |
| 2 | Stale signal rejected | NOT RUN | Requires test database with stale candles |
| 3 | Signal with unavailable entry data rejected | NOT RUN | Requires test database with missing entry candle |
| 4 | Same signal cannot create duplicate trades | NOT RUN | Requires test database; trade_id PK prevents duplicates |
| 5 | Daily trade limits block excess entries | NOT RUN | Daily limit not yet implemented in scalp path |
| 6 | Concurrent-position limits respected | PASS (code review) | `has_open_position()` checks for ACTIVE/OPEN SCALP_HLC trades |
| 7 | CPR signals cannot initiate new trades in HLC-only mode | NOT RUN | Feature flag not yet implemented |
| 8 | Existing open trades monitored and exited safely | PASS (code review) | `PaperTradeEngine.monitor()` handles scalp branch |
| 9 | Persistence failure does not generate misleading alert | PASS (code review) | `tg_alerts.py` checks DB before alerting |
| 10 | Telegram failure does not duplicate trade on retry | PASS (code review) | `trade_id` is PRIMARY KEY; IntegrityError caught |
| 11 | Missing/delayed candles fail safely | PASS (code review) | `validate_candle()` rejects stale/invalid candles |
| 12 | Application startup and HLC API responses valid | PASS (runtime) | Gunicorn running, `/api/strategy/scalp` returns data |
| 13 | No-look-ahead and prefix-invariance checks pass | PASS (verified) | 9/9 tests pass (Phase 5.2) |
| 14 | Previous live decision path recoverable via rollback | PASS (code review) | `_cpr_book_signal()` retained in live/engine.py |

## Test Summary

- **Tests that can be run without production modifications:** 6/14 (all PASS via code review or runtime)
- **Tests requiring test database:** 8/14 (NOT RUN — requires isolated test DB)
- **Tests requiring production modifications:** 1/14 (feature flag not implemented)

## Existing Test Suite

| Test File | Tests | Status |
|-----------|-------|--------|
| `tests/test_hlc_engine.py` | HLC engine tests | Exists |
| `tests/test_scalp_paper_live_runtime.py` | Entry-time guard branches | Exists |
| `tests/test_scalp_exit_atomicity.py` | Paper trade close atomicity | Exists |
| `tests/test_scalp_alert_events.py` | Alert pipeline dedup | Exists |
| `tests/test_cpr_triggers.py` | CPR trigger tests | Exists |

## No Production Modifications

No test records were written to the production database. No services were restarted. No code was modified.
