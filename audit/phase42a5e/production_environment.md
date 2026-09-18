# Production Environment

| Field | Value |
|-------|-------|
| Hostname | webserver |
| Branch | main |
| Workspace Commit | 9f24e58 |
| VM Commit | 20450f0d (deployed files match workspace 9f24e58) |
| Session Date | 2026-09-18 |
| Validation Time | 2026-09-18T18:45:57+05:30 |
| Timezone | Asia/Kolkata (IST, +05:30) |
| Python | Python 3.10.12 |
| SQLite DB | /opt/tradingai/database/tradingai.db |
| SQLite Size | 260.8 MB |
| Nginx | active |
| Gunicorn | active (3 workers on 127.0.0.1:8000) |
| TradingAI API | active (systemd) |
| Market State | CLOSED (market hours 09:30-15:30 IST) |

## Cron Jobs (market hours)

| Schedule | Job | Log |
|----------|-----|-----|
| * 9-15 * * 1-5 | data_fetcher_db.py | /opt/tradingai/logs/data.log |
| */15 9-15 * * 1-5 | aggregate.py sweep | /opt/tradingai/logs/aggregate.log |
| */5 9-15 * * 1-5 | monitor.py | /opt/tradingai/logs/monitor.log |
| */5 9-15 * * 1-5 | pnl_tracker.py evaluate | /opt/tradingai/logs/pnl.log |
| 20 15 * * 1-5 | pnl_tracker.py close | /opt/tradingai/logs/pnl.log |
| 0 */2 9-15 * * 1-5 | alert.py | /opt/tradingai/logs/alerts.log |
| */15 9-15 * * 1-5 | generate_json.py | /opt/tradingai/logs/json.log |
| 35 9 * * 1-5 | daily_page.py morning | /opt/tradingai/logs/daily.log |
| 35 15 * * 1-5 | daily_page.py close + sitemap_gen.py | /opt/tradingai/logs/daily.log |
| 30 9 * * 1-5 | outlook.py (all symbols) | /opt/tradingai/logs/outlook.log |
| 0 19 * * 1-5 | outlook.py (evening) | /opt/tradingai/logs/outlook.log |
| 35 18 * * 1-5 | bhavcopy.py daily | /opt/tradingai/logs/bhav.log |
| 30 8 * * 1 | bhavcopy.py holidays | /opt/tradingai/logs/bhav.log |
| 30 18 * * * | vm-backup.sh | /opt/tradingai/logs/backup.log |

## Deployed Fix (Phase 42A.5D)

- Commit: 9f24e58
- All 5 HTML pages verified: regime.regime extraction present, 0 buggy patterns
- NIFTY, BANKNIFTY, SENSEX, FINNIFTY index pages fixed
- index.html homepage fixed
