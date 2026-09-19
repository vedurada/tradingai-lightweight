# Live Validation Environment

Date: 2026-09-19 08:12 IST
Classification: PRE-MARKET (Saturday, market CLOSED)

## Git State
- Branch: html/h31-shell-core-pages
- Commit: 2a3c4b9 (Phase 42A: Repair AI Outlook pipeline — 4 defects fixed, validated, 32 audit artifacts)
- Status: Clean (except deploy-vm.sh modified by hook, scratch files untracked)
- Pushed: Yes (origin/html/h31-shell-core-pages)

## VM State
- Hostname: webserver
- OS: Ubuntu 22.04.5 LTS
- Timezone: Asia/Kolkata (IST, +0530)
- System clock synchronized: yes
- CPU: 1 (load avg: 0.63, 0.33, 0.20)
- RAM: 956MB total, 252MB used, 571MB available
- Swap: 2GB, 62MB used
- Disk: 45GB, 19GB used, 27GB available (42%)

## Services
- gunicorn: ACTIVE (4 workers, 127.0.0.1:8000, started 07:52)
- nginx: ACTIVE (started Wed 2026-09-16 06:13)
- monitor.service: INACTIVE (failed exit code 1 on 2026-09-18 07:53)
  - NOTE: cron triggers monitor.py directly every 5 min during market hours
- self-heal: cron-based, not running continuously

## Market Status
- Day: Saturday (market CLOSED)
- Time: 08:12 IST (market opens 09:15 IST on weekdays)
- Next market session: Monday 2026-09-21 09:15 IST

## Database
- Path: /opt/tradingai/database/tradingai.db
- Size: 268MB
- Integrity: OK (PRAGMA integrity_check: ok)
- Backup: /opt/tradingai/backups/tradingai_pre_live_ai_outlook_validation_20260919_081011.db (280MB, integrity OK)

## Key Table Row Counts
- market_snapshots_5m: 2 (from Phase 42A replay validation)
- market_evidence_5m: 1 (from Phase 42A replay validation)
- ai_outlooks_5m: 0 (no live 5m outlooks — market closed)
- research_ai_call_log: 0 (no LLM calls)
- ai_outlooks: 39,148 (legacy daily outlooks)
- market_outlooks: 206 (daily market outlooks)
- price_5m: 15,960 (5-minute candles, Aug 20 – Sep 18)
- market_regime: 39,124
- indicators: 39,124
- vix_data: 2,578

## Latest Data Timestamps
- price_5m: 2026-09-18T04:40:00+00:00 (Friday 10:10 IST)
- market_regime: 2026-09-18T16:40:59.127Z (Friday 22:10 IST)
- indicators: 2026-09-18T16:40:59.127Z (Friday 22:10 IST)
- vix_data: 2026-09-18T16:40:23.816315+00:00 (Friday 22:10 IST)
- ai_outlooks (legacy): 2026-09-18T16:40:21.734Z (Friday 22:10 IST)

## LLM Configuration
- groq.env: /etc/tradingai/groq.env (exists, 600 permissions, 1 line)
- LLM_API_KEY: SET (not displayed)
- LLM_API_URL: SET (not displayed)
- LLM_PROVIDER: SET (not displayed)
- LLM_STATUS: CONFIGURED (but no live session to test)

## API Endpoints Verified
- /api/health: 200 (degraded — expected, market closed)
- /api/ai-outlook/NIFTY: 200 (LEGACY fallback, data_state=LEGACY)
- /api/ai-outlook/BANKNIFTY: 200 (LEGACY fallback, data_state=LEGACY)
- /api/ai-outlook/timeline/NIFTY: 200 (1295 legacy outlooks)
- /api/ai-outlook/timeline/BANKNIFTY: 200 (1295 legacy outlooks)
- /api/market-outlook?symbol=NIFTY: 200 (206 daily outlooks)

## Frontend Pages Verified (HTTPS)
- /: 200
- /today/index.html: 200
- /indices/nifty.html: 200
- /indices/banknifty.html: 200
- /options/index.html: 200
- /strategies.html: 200
- /ai-track-record.html: 200
- /research/index.html: 200
- /backtest.html: 404 (pre-existing, not in scope)

## Deployed Code (VM /opt/tradingai/backend/)
- research_collector.py: _record_evidence() INSERTs evidence ✓
- ai_outlook_5m.py: _call_llm(prompt, symbol, market_state) ✓
- api_server.py: _ai_outlook_from_legacy() data_state=LEGACY ✓
- monitor.py: run_scheduler() function present ✓
- market_snapshot.py: create_snapshot() reads price_5m ✓

## Cron Jobs (Relevant)
- */5 9-15 * * 1-5: monitor.py (triggers scheduler during market hours)
- */2 * * * *: health check (restarts API if down)
- 30 9 * * 1-5: daily_page.py morning
- 35 15 * * 1-5: daily_page.py close + sitemap
