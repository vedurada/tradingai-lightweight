# Phase 5.41 Stage 3A Final Validation — Failure Investigation

## Failures Investigated
1. test_signal_only_after_candle_completion (HLC) — final-candle signal idx check.
2. test_hlc_engine_is_default (HLC) — `_cpr_book_signal` in eval source.
3. test_scalp_paper_live_runtime (4 tests) — entry_time_guard, expired_signal, watch_replay, provider_failure.
4. test_unified_book (1 test) — entry_math_bear_next_open.

## Status
INVESTIGATION IN PROGRESS
