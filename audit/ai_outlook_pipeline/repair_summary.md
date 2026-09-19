# AI Outlook Pipeline Repair Summary

Date: 2026-09-19 (Saturday, market CLOSED)
Classification: REPLAY/VALIDATION (all tests against historical data)

## Repairs Applied

| # | Priority | Defect | File | Fix |
|---|----------|--------|------|-----|
| 1 | P1 | `_record_evidence()` never inserts | backend/research_collector.py | Rewrote to query market_regime/indicators/price_5m/vix_data, build JSON evidence records, INSERT OR IGNORE into market_evidence_5m |
| 2 | P0 | `_call_llm()` hardcodes NIFTY | backend/ai_outlook_5m.py | Changed signature to `_call_llm(prompt, symbol, market_state)`, passes actual symbol and state to `engine.generate()`. Added `_prepare_ai_input()` to map snapshot fields to AI engine format |
| 3 | P0 | No production scheduler trigger | backend/monitor.py | Added `run_scheduler()` function, integrated into `check_health()` during market hours |
| 4 | P1 | `_ai_outlook_from_legacy()` hardcodes data_state=LIVE | backend/api_server.py | Changed to data_state=LEGACY, added source_type=LEGACY, is_current_5m=false |

## Supporting Fixes

- backend/market_snapshot.py: `create_snapshot()` now reads OHLCV from price_5m when not provided (fixes scheduler snapshot creation)

## Verification Results (REPLAY/VALIDATION)

- market_snapshots_5m: 1 NIFTY + 1 BANKNIFTY snapshot created
- market_evidence_5m: 1 NIFTY evidence created (BEARISH, confidence=75, LIVE)
- Idempotency: PASSED (second run created no duplicates)
- Symbol routing: NIFTY→NIFTY ✓, BANKNIFTY→BANKNIFTY ✓
- Legacy fallback: data_state=LEGACY ✓, source_type=LEGACY ✓
- Regression tests: 12 passed, 1 skipped, 0 failed

## Known Pre-existing Failures (unrelated)

- test_ai_outlook_backtest.py: ModuleNotFoundError (indicators module)
- test_phase6a/test_phase6b/test_phase7: UI/API invariant tests (pre-existing)
