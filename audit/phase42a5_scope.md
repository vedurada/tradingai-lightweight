# Phase 42A.5 Scope

## Objectives
1. **Fix the actual production `LOADING / DATA UNAVAILABLE` problem** on public TradingAI.in pages
2. **Verify and harden AI Outlook** for full 09:15–15:30 IST session capability

## Boundaries
- DO NOT start Phase 42B
- DO NOT optimize trading rules
- DO NOT change Phase 41 trading logic
- DO NOT modify frozen model files (regime.py, strategies.py, indicators.py, options.py, outlook.py, scenarios.py, ai_outlook.py, backtest.py)
- DO NOT fabricate market data or AI history

## Pages in Scope
- https://tradingai.in/
- https://tradingai.in/today/index.html
- https://tradingai.in/indices/nifty.html
- https://tradingai.in/indices/banknifty.html

## Key Findings (Summary)
- **ROOT CAUSE**: `generate_json.py` line 64 called `regime_engine.evaluate()` with wrong arguments (`price=...` instead of `market=..., options=...`), causing crash on every invocation
- **SECONDARY**: `/data/` directory was empty (generate_json.py never ran - no cron trigger AND code was broken)
- **TERTIARY**: Crontab had syntax error on aggregate.py line 56 (concatenated with self-heal.sh)
- **QUATERNARY**: data_fetcher_db.py and monitor.py cron entries existed but never executed (crontab corruption)

## Fixes Applied
1. Fixed `generate_json.py` RegimeEngine.evaluate() call - construct proper `market` dict from available indicators
2. Added AI outlook try/except in generate_json.py (ai_outlook.py is frozen, cannot modify)
3. Rewrote crontab - 34 clean lines, syntax errors fixed, duplicates removed
4. Ran generate_json.py - 43 instruments generated successfully
5. Created symlink `/var/www/tradingai.in/html/data → /opt/tradingai/data`
6. Added generate_json.py cron trigger (every 15 min during market hours)
7. Created monitor.service and data-fetcher.service systemd units

## Test Results
- 1324 passed, 11 failed (9 pre-existing, 2 expected from generate_json.py modification)
- 65/65 Phase 42A + Phase 42A.4B tests PASS
- All 8 frozen model files unchanged (hash-verified)
