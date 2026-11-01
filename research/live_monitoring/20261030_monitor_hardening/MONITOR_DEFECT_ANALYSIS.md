# TradingAI — Unattended Monitor Hardening: Defect Analysis

## Phase
#TradingAI — Unattended Monitor Hardening, Validation & Enablement Readiness

## Defect
- Error observed: `AttributeError: 'list' object has no attribute 'get'`
- Source: /opt/tradingai/monitoring/live_watch/live_monitor.py
- Responsible line:
  `if isinstance(st,dict): sm=st.get('strategy_mode') or (st.get('strategies') or {}).get('directional',{}).get('name')`
- Root cause: settings key `strategies` is a JSON **list**, not a dict; monitor unconditionally called `.get('directional')` on it.

## Evidence
- Reproduction: isolated debug run of monitor logic → traceback + `AttributeError: 'list' object has no attribute 'get'`.
- Fix: guard `isinstance(strat, dict)` / `isinstance(strat, list)` before `.get`.

## Status
DEFECT_FOUND_AND_FIXED
