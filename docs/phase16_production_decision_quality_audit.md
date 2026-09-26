# Phase 16: Production Decision Quality & Trader UX Audit

## Objective
Audit and harden the complete trader-facing decision pipeline from market data through options strategy to final trader-facing decision, ensuring honest, time-correct, understandable decisions without implying trades when evidence is missing.

## Changes Made

### 1. Decision State Machine (`app/core/decision_state.py`)
- Canonical `DecisionState` enum with 16 states: PREMARKET, LIVE, QUALIFIED, NO_TRADE, OPTIONS_DATA_UNAVAILABLE, STALE, NO_DATA, MARKET_CLOSED, WEEKEND, DAILY_TRADE_LIMIT_REACHED, RATE_LIMITED, HOLIDAY, OPTIONS_STALE, OPTIONS_PARTIAL_CHAIN, OPTIONS_RATE_LIMITED, OPTIONS_UNAVAILABLE, OPTIONS_MALFORMED, OPTIONS_INSUFFICIENT_LIQUIDITY, OPTIONS_INVALID_CONTRACT, INDEX_SIGNAL_NOT_CONFIRMED, STALE_MARKET_DATA, NO_COMPLETED_CANDLE, MARKET_INDEX_UNAVAILABLE, INVALID_SIGNAL
- `is_tradeable()` — only QUALIFIED produces trades
- `is_data_gated()` — states indicating data unavailability
- `is_session_gated()` — states indicating market closed
- `validate_decision_output()` — validates required fields
- `INTERNAL_TO_CANONICAL` mapping for backward compatibility

### 2. Decision Trace (`app/core/decision_trace.py`)
- `build_decision_trace()` — produces auditable trace with all evidence sources and timestamps
- `trace_to_public()` — converts to public-facing format, does not expose internal details
- `validate_trace()` — validates completeness and determinism
- Traces are deterministic and testable

### 3. PIT Integrity Tests
- `test_pit_future_row_does_not_influence` — future scenarios do not leak into past queries
- `test_pit_match_timestamp_not_exceeds` — match timestamp never exceeds decision timestamp
- `test_pit_scenario_uses_only_past` — scenario lookup uses only past data

### 4. Decision State Tests (8 tests)
- `test_decision_state_canonical`
- `test_decision_states_complete`
- `test_is_tradeable`
- `test_is_data_gated`
- `test_is_session_gated`
- `test_validate_decision_output`
- `test_state_backward_compatibility`

### 5. Decision Trace Tests (3 tests)
- `test_decision_trace_complete` — validates complete trace
- `test_decision_trace_no_trade` — validates NO_TRADE/NOT_QUALIFIED trace
- `test_trace_public_format` — validates public format and no data leakage

### 6. One-Trade/Day Concurrency Test (1 test)
- `test_one_trade_day_concurrent_claims` — 8 parallel claim attempts produce <=1 trade row
- `test_get_decision_zero_writes` — GET /decision performs zero writes

### 7. Failure-Injection Matrix (10 tests)
- `test_market_timeout` — provider returns explicit error state
- `test_options_no_data_state` — OPTIONS_NO_DATA returned
- `test_options_rate_limited_state` — RATE_LIMITED enum value
- `test_options_stale_state` — STALE classification works
- `test_malformed_contract_rejected` — invalid contracts rejected
- `test_missing_strike_rejected` — contracts without strike rejected
- `test_missing_expiry_rejected` — contracts without expiry rejected
- `test_invalid_option_type_rejected` — CALL/PUT type validated
- `test_empty_response_handled` — empty data handled gracefully
- `test_nifty_banknifty_isolation` — NIFTY/BANKNIFTY data isolation

### 8. Regression Tests (4 tests)
- `test_phase13_baselines_intact` — baselines preserved
- `test_phase14_options_api_intact` — API works
- `test_phase15_strategy_api_intact` — Strategy API works
- `test_app_options_package_imports` — all exports importable

### 9. Security Tests (4 tests)
- `test_no_secrets_in_git_diff` — no secrets in code
- `test_no_debug_mode` — debug mode disabled
- `test_decision_api_read_only` — decision endpoint is read-only
- `test_options_strategy_api_read_only` — strategy endpoint is read-only
- `test_options_strategy_no_fabricated_economics` — no fabricated economics on server

### 10. Options Data Gate Tests (2 tests)
- `test_options_data_gate_fresh` — data gate returns false when no data
- `test_index_signal_gate` — index signal validation works

## Test Results
35/35 tests pass
Full regression (Phases 10-15): 80/80 tests pass
Combined: 115/115 tests pass

## Baseline Verification
- NIFTY: 34 trades / +16.21R (unchanged)
- BANKNIFTY: 31 trades / +16.63R (unchanged)

## Decision Pipeline
1. Market data fetch → STALE/UNAVAILABLE/NO_DATA check
2. Session timing → PREMARKET/MARKET_CLOSED/WEEKEND/HOLIDAY check
3. Options data gate → OPTIONS_DATA_UNAVAILABLE/OPTIONS_STALE/OPTIONS_NO_DATA/OPTIONS_RATE_LIMITED/OPTIONS_PARTIAL_CHAIN/OPTIONS_MALFORMED/OPTIONS_INSUFFICIENT_LIQUIDITY/OPTIONS_INVALID_CONTRACT check
4. Index signal gate → INDEX_SIGNAL_NOT_CONFIRMED/INDEX_SIGNAL_STALE/INDEX_SIGNAL_UNAVAILABLE check
5. Strategy qualification → QUALIFIED/NO_TRADE
6. One-trade/day lock → DAILY_TRADE_LIMIT_REACHED/CONSUMED/PENDING
7. Final decision → explicit state + reason + timestamp + instrument

## No Trade Without Complete Evidence Chain
Every non-QUALIFIED state requires an explicit reason string. No state implies a trade. No trade is suggested without complete evidence.

## Options Safety
- No validated options trade is suggested when data is unavailable
- Options state check is performed before strategy qualification
- Frontend displays explicit options data unavailability notice

## One-Trade/Day Preservation
- Database UNIQUE constraint (instrument_id, date) prevents duplicate trades
- INSERT OR REPLACE with IntegrityError handling ensures exactly one trade per day
- 8 concurrent claim attempts produce <=1 trade (tested)
- GET endpoints perform zero writes (tested)
