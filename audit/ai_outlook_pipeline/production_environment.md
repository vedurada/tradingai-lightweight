# Production Environment Audit — AI Outlook Pipeline

Date: 2026-09-18 (market CLOSED)

## Environment

| Field | Value |
|-------|-------|
| Hostname | webserver |
| OS | Ubuntu 22.04.5 LTS (Jammy Jellyfish) |
| Python | 3.10.12 |
| VM IP | 129.159.224.81 |
| SSH user | ubuntu |
| Working directory | /home/ubuntu |
| Database path | /opt/tradingai/database/tradingai.db |
| Webroot | /var/www/tradingai.in/html/ |

## Git State (VM)

| Branch | Commit | Message |
|--------|--------|---------|
| main | 20450f0d | docs: Phase 0 audit report and AGENTS.md |
| tradingai.in_live_VM | 20450f0d | (same as main — VM is at Phase 0) |

## Git State (Workspace — for comparison)

| Branch | Commit | Message |
|--------|--------|---------|
| html/h31-shell-core-pages | 675e06b | doc: update AI outlook fix audit log with regimeText fix |
| html/h31-shell-core-pages | a8cadc6 | fix: add missing regimeText function to today/index.html |
| html/h31-shell-core-pages | 081ddcb | doc: AI outlook API endpoint fix audit log |

## Services

### Gunicorn (API)
```
Process: /usr/bin/python3 /home/ubuntu/.local/bin/gunicorn -w 3 --worker-class sync -b 127.0.0.1:8000 --timeout 90 --graceful-timeout 15 --keep-alive 5 --max-requests 1000 --max-requests-jitter 100 --access-logfile /opt/tradingai/logs/gunicorn-access.log --error-logfile /opt/tradingai/logs/gunicorn-error.log api_server:app
```
- 3 workers, sync class
- Running since: 2026-09-18 22:11:04 IST

### Systemd Service
```
● tradingai-api.service - TradingAI Flask API (gunicorn, port 8000)
   Loaded: loaded (/etc/systemd/system/tradingai-api.service; enabled; vendor preset: enabled)
   Active: active (running) since Fri 2026-09-18 22:11:04 IST
```

### Nginx
- Active reverse proxy on port 443
- Server: tradingai.in, www.tradingai.in
- SSL: TLSv1.2, TLSv1.3
- Reverse proxies to 127.0.0.1:8000

## Database
- Path: /opt/tradingai/database/tradingai.db
- Size: 264MB (275,836,928 bytes)
- Integrity: OK
- Backup: /opt/tradingai/backups/tradingai_pre_ai_outlook_pipeline_20260918_222245.db (264MB)
- Mode: WAL (implied by AGENTS.md)

## Cron Jobs (Relevant to AI Outlook Pipeline)

| Schedule | Script | Relevance |
|----------|--------|-----------|
| 0 3 * * * | cleanup.sh | Maintenance |
| * 9-15 * * 1-5 | data_fetcher_db.py | Populates ai_outlooks (twice-daily LLM + rule-based template) |
| */5 9-15 * * 1-5 | monitor.py | Calls run_research_collection() → ResearchCollector |
| 0 */2 9-15 * * 1-5 | alert.py | Alerts |
| */5 9-15 * * 1-5 | pnl_tracker.py evaluate | PnL |
| 35 9/15 * * 1-5 | daily_page.py | Daily pages (morning/close) |
| 30 9/19 * * 1-5 | **outlook.py** | **Twice-daily AI outlook (LLM) → ai_outlooks + market_outlooks** |
| 35 18 * * 1-5 | fo_fetcher.py | FO data |
| 30 6 * * 0 | backfill_yearly.py | Yearly backfill |
| 35 19 * * * | mf_fetcher.py | MF data |
| */2 * * * * | health check curl | Health monitoring |
| */2 * * * * | self-heal.sh | Self healing |

### CRITICAL: Missing from Cron
- **outlook_scheduler.py** — NEVER triggered (no cron entry, no systemd timer)
- **research_collector.collect()** — Called via monitor.py but _record_evidence() is broken

## API Server (from /api/health)
- Status: ok
- DB: ok
- Redis: not connected
- Webroot: ok
- Ready: true

## Key Observations
1. No cron entry for `outlook_scheduler.py` or `run_scheduler()`
2. No systemd timer for the 5-minute AI outlook pipeline
3. The only twice-daily AI outlook generator is `outlook.py` (9AM/7PM IST) → stores to `ai_outlooks` table
4. `data_fetcher_db.py` runs every minute during market hours and generates rule-based `ai_outlooks` (not LLM)
5. `monitor.py` calls `run_research_collection()` every 5 minutes during market hours
