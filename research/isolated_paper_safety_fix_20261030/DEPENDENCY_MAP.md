# Isolated Dependency Map — Checkpoint: Dependency Closure and Import Proof

## Host gate
- hostname: webserver
- uname -a: Linux webserver 6.8.0-1060-oracle #63~22.04.1-Ubuntu SMP ... x86_64 GNU/Linux
- pwd: /home/ubuntu
- whoami: ubuntu
- OS: Ubuntu 22.04.5 LTS (x86_64)
- Verdict: PASS (Oracle VM, Ubuntu 22.04, x86_64)

## Workspace
- Path: /opt/tradingai/research/isolated_paper_safety_fix_20261030/
- Existing copies and checksums preserved; no overwrite performed.

## Copied dependencies (isolated workspace)
- app/core/config.py, app/core/db.py, app/core/decision_state.py, app/core/decision_trace.py, app/core/qualification.py (copied from /opt/tradingai/app/core)
- app/research/scalp_engine.py, app/research/scalp_validation.py, app/research/scalp_signal_store.py, app/research/cpr_trigger_engine.py, app/research/cpr_strategy_engine.py
- app/decision/view.py, app/decision/__init__.py
- app/market/nse_calendar.py, app/market/provider.py, app/market/cache.py, app/market/collector.py, app/market/events_calendar.py, app/market/flight.py
- app/scenarios/engine.py
- app/strategies/engine.py, app/strategies/scalp.py
- app/risk/engine.py
- scripts/paper_scalp_live.py, scripts/tg_alerts.py
- tests/test_hlc_engine.py, tests/test_scalp_paper_live_runtime.py, tests/test_scalp_exit_atomicity.py, tests/test_unified_book.py

## Required modules proven to resolve inside isolated workspace
- app.research.scalp_engine -> /opt/tradingai/research/isolated_paper_safety_fix_20261030/app  ISOLATED=True
- app.paper_trade.engine -> /opt/tradingai/research/isolated_paper_safety_fix_20261030/app  ISOLATED=True
- app.live.engine -> /opt/tradingai/research/isolated_paper_safety_fix_20261030/app  ISOLATED=True
- app.core.db -> /opt/tradingai/research/isolated_paper_safety_fix_20261030/app  ISOLATED=True
- app.research.scalp_validation -> ISOLATED=True
- app.research.scalp_signal_store -> ISOLATED=True
- app.research.cpr_trigger_engine -> ISOLATED=True
- app.research.cpr_strategy_engine -> ISOLATED=True
- app.decision.view -> ISOLATED=True
- app.market.nse_calendar -> ISOLATED=True
- app.market.provider -> ISOLATED=True
- app.core.qualification -> ISOLATED=True
- app.scenarios.engine -> ISOLATED=True
- app.strategies.engine -> ISOLATED=True
- app.risk.engine -> ISOLATED=True

## Excluded adapter
- app.strategies.scalp: NOT required by the four target test suites; excluded; not force-imported.

## Final gate
- DEPENDENCY_CLOSURE_COMPLETE - READY FOR ISOLATED FIXES
