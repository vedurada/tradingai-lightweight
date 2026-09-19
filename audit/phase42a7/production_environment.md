# Production Environment

Date: 2026-09-19 08:16 IST (Saturday, market CLOSED)

## VM State
- Hostname: webserver
- Deployed commit: 2a3c4b9 (html/h31-shell-core-pages)
- Branch: html/h31-shell-core-pages
- Webroot: /var/www/tradingai.in/html/
- Backend path: /opt/tradingai/backend/
- Database path: /opt/tradingai/database/tradingai.db
- Timezone: Asia/Kolkata (IST, +0530)

## Services
- nginx: active
  - ● nginx.service - A high performance web server and a reverse proxy server
     Loaded: loaded (/lib/systemd/system/nginx.service; enabled; vendor preset: enabled)
     Active: active (running) since Wed 2026-09-16 06:13:06 IST; 3 days ago
- gunicorn: active
  - ● tradingai-api.service - TradingAI Flask API (gunicorn, port 8000)
     Loaded: loaded (/etc/systemd/system/tradingai-api.service; enabled; vendor preset: enabled)
     Active: active (running) since Sat 2026-09-19 07:52:05 IST; 30min ago
- monitor.service: inactive
INACTIVE
  - ○ monitor.service - TradingAI Monitor & Research Collector
     Loaded: loaded (/etc/systemd/system/monitor.service; enabled; vendor preset: enabled)
     Active: inactive (dead) since Fri 2026-09-18 07:53:05 IST; 24h ago

## Cron Jobs (relevant)
* 9-15 * * 1-5 cd /opt/tradingai/backend && SKIP_LLM=1 /usr/bin/python3 data_fetcher_db.py >> /opt/tradingai/logs/data.log 2>&1
*/5 9-15 * * 1-5 cd /opt/tradingai/backend && /usr/bin/python3 monitor.py >> /opt/tradingai/logs/monitor.log 2>&1
30 9 * * 1-5 cd /opt/tradingai/backend && . /etc/tradingai/groq.env && { /usr/bin/python3 outlook.py --symbol NIFTY --webroot /var/www/tradingai.in/html && /usr/bin/python3 outlook.py --symbol BANKNIFTY --webroot /var/www/tradingai.in/html && /usr/bin/python3 outlook.py --symbol FINNIFTY --webroot /var/www/tradingai.in/html && /usr/bin/python3 outlook.py --symbol SENSEX --webroot /var/www/tradingai.in/html && /usr/bin/python3 /opt/tradingai/ops/inject_trust_headers.py --root /var/www/tradingai.in/html && /usr/bin/python3 /opt/tradingai/ops/prerender_snapshot.py --root /var/www/tradingai.in/html >> /opt/tradingai/logs/prerender.log 2>&1; } >> /opt/tradingai/logs/outlook.log 2>&1
0 19 * * 1-5 cd /opt/tradingai/backend && . /etc/tradingai/groq.env && { /usr/bin/python3 outlook.py --symbol NIFTY --webroot /var/www/tradingai.in/html && /usr/bin/python3 outlook.py --symbol BANKNIFTY --webroot /var/www/tradingai.in/html && /usr/bin/python3 outlook.py --symbol FINNIFTY --webroot /var/www/tradingai.in/html && /usr/bin/python3 outlook.py --symbol SENSEX --webroot /var/www/tradingai.in/html && /usr/bin/python3 sitemap_gen.py --webroot /var/www/tradingai.in/html && /usr/bin/python3 /opt/tradingai/ops/inject_trust_headers.py --root /var/www/tradingai.in/html && /usr/bin/python3 /opt/tradingai/ops/prerender_snapshot.py --root /var/www/tradingai.in/html >> /opt/tradingai/logs/prerender.log 2>&1; } >> /opt/tradingai/logs/outlook.log 2>&1


## DB State
- Size: 268M
- Integrity: ok
- Tables: 61

## Key Table Counts
- market_snapshots_5m: 2
- market_evidence_5m: 1
- ai_outlooks_5m: 0
- research_ai_call_log: 0
- ai_outlooks: 39148
- price_5m: 15960

## Latest Data Timestamps
- price_5m: 2026-09-18T04:40:00+00:00
- market_regime: 2026-09-18T16:40:59.127Z
- ai_outlooks (legacy): 2026-09-18T16:40:59.127Z

## API Health
{
    "data_freshness": {
        "nifty_price_minutes_ago": 614,
        "outlook_minutes_ago": 1614,
        "vix_minutes_ago": 613
    },
    "db_size_mb": 267.66,
    "deep_health": {
        "all_healthy": false,
        "details": {
            "market_outlooks": {
                "issues": [],
                "max_date": "2026-09-18",
                "min_date": "2026-06-18",
                "row_count": 206,
                "status": "ok"
            },
            "price_1d": {
                "issues": [],
                "max_date": "2026-09-18T00:00:00+05:30",

## LLM Configuration
- groq.env: -rw------- 1 ubuntu ubuntu 77 Sep 12 08:52 /etc/tradingai/groq.env
- LLM env vars present: 3

## Resource Usage
               total        used        free      shared  buff/cache   available
Mem:           956Mi       256Mi        79Mi       0.0Ki       620Mi       568Mi
/dev/sda1        45G   19G   27G  42% /
 08:23:52 up 10 days, 14:03,  1 user,  load average: 1.59, 0.58, 0.32

## Git State (VM)
20450f0d docs: Phase 0 audit report and AGENTS.md

## Recent Backups
total 2.2G
-rw-r--r-- 1 ubuntu ubuntu 268M Sep 19 08:10 tradingai_pre_live_ai_outlook_validation_20260919_081011.db
-rw-r--r-- 1 ubuntu ubuntu 268M Sep 19 07:42 tradingai_pre_ai_outlook_repair_20260919_074207.db
-rw-r--r-- 1 ubuntu ubuntu 264M Sep 18 22:22 tradingai_pre_ai_outlook_pipeline_20260918_222245.db
-rw-r--r-- 1 ubuntu ubuntu  13M Sep 18 22:04 tradingai_20260918_163447.db
