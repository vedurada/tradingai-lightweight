# Phase 5.41 Stage 3A — Test Commands and Outputs

## Executed Tests

### T1: tests/test_hlc_engine.py
Command: `cd /opt/tradingai && python3 -m pytest tests/test_hlc_engine.py -q --no-header`
Start: ~08:2x IST 2026; End: ~08:2x IST 2026
Result: 2 FAILED, 17 PASSED (2 warnings)
Failures:
- test_signal_only_after_candle_completion: AssertionError (final-candle signal idx check)
- test_hlc_engine_is_default: AssertionError (`_cpr_book_signal` in eval source)

### T2: tests/test_scalp_paper_live_runtime.py + tests/test_scalp_exit_atomicity.py + tests/test_unified_book.py
Command: `cd /opt/tradingai && python3 -m pytest tests/test_scalp_paper_live_runtime.py tests/test_scalp_exit_atomicity.py tests/test_unified_book.py -q --no-header`
Result: 5 FAILED, 9 PASSED
Failures:
- test_scalp_paper_live_runtime.py::test_entry_time_guard_all_branches_without_nameerror
- test_scalp_paper_live_runtime.py::test_run_once_expired_signal_does_not_create_trade
- test_scalp_paper_live_runtime.py::test_do_watch_replay_does_not_duplicate_logical_alert
- test_scalp_paper_live_runtime.py::test_do_watch_provider_failure_not_recorded_as_success
- test_unified_book.py::test_entry_math_bear_next_open

## Status
ACTUAL OUTPUT CAPTURED
