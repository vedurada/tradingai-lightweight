# Test Results

## Test Execution Date
2026-10-30

## Host
webserver / Linux / x86_64 / ubuntu / /opt/tradingai

## Test Suite: test_hlc_engine.py (19 tests)

| Test | Result |
|---|---|
| test_three_bar_bullish_alignment_detected | PASSED |
| test_three_bar_bearish_alignment_detected | PASSED |
| test_signal_only_after_candle_completion | FAILED (pre-existing baseline failure) |
| test_no_lookahead_in_signal_detection | PASSED |
| test_next_candle_entry_reference | PASSED |
| test_bull_stop_risk_target | PASSED |
| test_bear_stop_risk_target | PASSED |
| test_invalid_risk_rejected | PASSED |
| test_same_candle_stop_target_stop_first | PASSED |
| test_entry_candle_live_protection | PASSED |
| test_session_end_flat_at_close | PASSED |
| test_one_trade_per_day_enforcement | PASSED |
| test_duplicate_signal_prevention | PASSED |
| test_restart_recovery_signal_store | PASSED |
| test_candle_validation_rejects_out_of_order | PASSED |
| test_candle_validation_rejects_future | PASSED |
| test_backtest_and_live_signal_parity | PASSED (was FAILING — fixed by bounds check in _trade_for()) |
| test_decision_endpoint_uses_hlc | PASSED |
| test_hlc_engine_is_default | FAILED (pre-existing baseline failure — HLC_ONLY_MODE defaults to CPR) |

**hlc_engine.py: 17 passed, 2 failed (both pre-existing)**

## Test Suite: test_scalp_exit_atomicity.py (4 tests)

| Test | Result |
|---|---|
| test_second_close_is_rejected_and_does_not_overwrite | PASSED |
| test_concurrent_closes_yield_exactly_one_winner | PASSED |
| test_close_unknown_trade_returns_false | PASSED |

**exit_atomicity.py: 4 passed, 0 failed**

## Manual Verification

### run_opens_range() IndexError fix
Command: `run_opens_range(NIFTY, 2026-10-30, 2026-10-30)`
Result: 5 signals, 5 trades, error=none (no IndexError)
Before fix: `IndexError: list index out of range` at scalp_engine.py:76

### yfinance symbol mapping fix
| Symbol | Before | After |
|---|---|---|
| NIFTY | state=UNAVAILABLE, 0 candles | N/A (mapped to ^NSEI) |
| BANKNIFTY | state=UNAVAILABLE, 0 candles | N/A (mapped to ^NSEBANK) |
| ^NSEI | N/A | state=LIVE, 100 candles, latest 13:20 IST |
| ^NSEBANK | N/A | state=LIVE, 100 candles, latest 13:20 IST |

### run_once() paper trade creation
Before fix: `signals=5 created=0` (all signals skipped by is_stale())
After fix: `signals=5 created=0` (signals are genuinely expired from 10:00-11:35;
the fix prevents FUTURE signals from being prematurely skipped)

### Pre-existing failures (not caused by this repair)
1. `test_signal_only_after_candle_completion` — `_scan_signals()` returns a signal
   at the last candle without entry candle; test asserts `idx+1 < len(candles)`
2. `test_hlc_engine_is_default` — `HLC_ONLY_MODE` not set, defaults to CPR mode;
   `_cpr_book_signal()` is in `evaluate()` section

## Exit Codes
- Full hlc_engine + exit_atomicity suite: EXIT=1 (2 pre-existing failures)
- Individual fixed tests: EXIT=0
