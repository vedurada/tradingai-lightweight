# first_trigger Classification — Isolated Remediation Checkpoint

## Evidence

- app/strategies/scalp.py:2 imports first_trigger, today_state, run_opens_range from app.research.scalp_engine.
- app/research/scalp_engine.py defines run_range, run_opens_range, today_signals, today_state, scalp_signal, decay_win; it does NOT define first_trigger.
- app/research/cpr_trigger_engine.py:337 defines first_trigger(day_candles, lv); used internally at line 474 inside run_opens_range.
- Final usage scan (grep -rn over *.py excluding __pycache__ and *.pre-*): ScalpEngine / strategies.scalp referenced only inside app/strategies/scalp.py.

## Classification

- CONFIRMED_EXISTING_PRODUCTION_DEFECT: the adapter import from app.research.scalp_engine is broken because first_trigger is not defined there.
- OUTDATED_ADAPTER: the adapter appears superseded/orphaned and is not consumed by the four target test suites or discovered runtime paths.

## Resolution for isolated checkpoint

- Adapter app.strategies.scalp was NOT required by the four target test suites.
- It was NOT force-imported merely to satisfy isolation.
- No stub, duplicate, or redirect was created.
- No production source was changed.

## Decision

- Classification: OUTDATED_ADAPTER (with confirmed import-level breakage).
- Isolated fixes: not yet executed at this checkpoint.
