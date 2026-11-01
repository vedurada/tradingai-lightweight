BASELINE DISCREPANCY ANALYSIS — ISOLATED BASELINE
Phase: TradingAI — Reconcile Isolated Baseline Test Discrepancy
Host gate: PASS (webserver / Ubuntu 22.04.5 LTS / x86_64 / ubuntu / /opt/tradingai)
Workspace: /opt/tradingai/research/isolated_paper_safety_fix_20261030/

## Reported numbers
- Individual aggregate: 23 passed, 10 failed, 33 total.
- Combined aggregate: 26 passed, 7 failed, 33 total.

## Individual failures (10)
1. tests/test_hlc_engine.py::test_signal_only_after_candle_completion
2. tests/test_hlc_engine.py::test_backtest_and_live_signal_parity
3. tests/test_hlc_engine.py::test_hlc_engine_is_default
4. tests/test_scalp_paper_live_runtime.py::test_entry_time_guard_all_branches_without_nameerror
5. tests/test_scalp_paper_live_runtime.py::test_run_once_expired_signal_does_not_create_trade
6. tests/test_scalp_paper_live_runtime.py::test_do_watch_replay_does_not_duplicate_logical_alert
7. tests/test_scalp_paper_live_runtime.py::test_do_watch_provider_failure_not_recorded_as_success
8. tests/test_scalp_exit_atomicity.py::test_second_close_is_rejected_and_does_not_overwrite
9. tests/test_scalp_exit_atomicity.py::test_concurrent_closes_yield_exactly_one_winner
10. tests/test_unified_book.py::test_entry_math_bear_next_open

## Combined failures (7)
1. tests/test_hlc_engine.py::test_signal_only_after_candle_completion
2. tests/test_hlc_engine.py::test_hlc_engine_is_default
3. tests/test_scalp_paper_live_runtime.py::test_entry_time_guard_all_branches_without_nameerror
4. tests/test_scalp_paper_live_runtime.py::test_run_once_expired_signal_does_not_create_trade
5. tests/test_scalp_paper_live_runtime.py::test_do_watch_replay_does_not_duplicate_logical_alert
6. tests/test_scalp_paper_live_runtime.py::test_do_watch_provider_failure_not_recorded_as_success
7. tests/test_unified_book.py::test_entry_math_bear_next_open

## Discrepancies
- Failures present individually but NOT in combined: 3.
  - tests/test_hlc_engine.py::test_backtest_and_live_signal_parity
  - tests/test_scalp_exit_atomicity.py::test_second_close_is_rejected_and_does_not_overwrite
  - tests/test_scalp_exit_atomicity.py::test_concurrent_closes_yield_exactly_one_winner
- In combined run, exit_atomicity suite contributed 0 failures; in individual run it contributed 2.
- In combined run, hlc suite contributed 2 failures; in individual run it contributed 3 (extra: test_backtest_and_live_signal_parity).

## Likely investigation areas
- Shared SQLite/test fixtures via tests/conftest.py (single temp DB per process).
- Global state / monkeypatch leakage across modules in combined process.
- Ordering dependencies between suites.
- Missing module app.paper_trade.performance affecting exit_atomicity PERF event recording.
