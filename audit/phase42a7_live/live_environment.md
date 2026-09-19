# Live Validation Environment

Date: 2026-09-19 09:10 IST (Saturday, market CLOSED)
Classification: PRE-MARKET VALIDATION — Live session pending Monday 2026-09-21 09:15 IST

## Production VM
- Hostname: webserver
- Backend: /opt/tradingai/backend/ (git: main@20450f0d, stale by rsync deployment)
- Webroot: /var/www/tradingai.in/html/
- Database: /opt/tradingai/database/tradingai.db (268MB, integrity OK)
- Backup: /opt/tradingai/backups/tradingai_pre_42a7_finalfix_20260919_090520.db (268MB, integrity OK)

## Services
- nginx: ACTIVE (running since 2026-09-16)
- gunicorn: ACTIVE (user process, 4 workers, 127.0.0.1:8000, started 07:52)
- tradingai-api.service: exists but INACTIVE (gunicorn started manually, not via systemd)
- monitor.service: INACTIVE (cron triggers monitor.py directly during market hours)
- Self-heal: ACTIVE (*/2 cron checks API health, restarts tradingai-api if needed)

## API Health
- Status: degraded (market closed Saturday — expected)
- price_5m: stale (659 min ago, 2026-09-18 16:40)
- vix_data: stale (659 min ago, 2026-09-18 16:40)
- outlook: stale (1659 min ago, 2026-09-18 16:40)
- market_outlooks: ok (206 rows, max 2026-09-18)
- All APIs responding correctly

## Git State (Deployment Method)
- Workspace: html/h31-shell-core-pages @ c08c04a (Phase 42A.7 fixes committed and pushed)
- VM git: main@20450f0d (stale by design, rsync deployment)
- Deployment: rsync (3 HTML files deployed 2026-09-19 09:07 IST)

## Files Deployed (2026-09-19 09:07 IST)
- /var/www/tradingai.in/html/trade.html (12780 bytes, 1 loadData definition)
- /var/www/tradingai.in/html/ai-track-record.html (13844 bytes, 4 data-sym + 2 data-col)
- /var/www/tradingai.in/html/index.html (38189 bytes, updateFreshness function)

## Live Market Data (Saturday — STALE)
- price_5m latest: 2026-09-18T16:40:00 (Friday close)
- vix_data latest: 2026-09-18T16:40:23 (Friday close)
- ai_outlooks latest: 2026-09-18T16:40:59 (Friday daily outlook)
- No ai_outlooks_5m records (no live generation — market closed)
- No paper trades since Friday close

## Live Validation Schedule
- Monday 2026-09-21: Market open 09:15-15:30 IST
- Validation window: 09:15-15:30 IST
- Continuous monitoring of full pipeline chain
