# Phase 42A.10 Production Environment

## Timestamp
- UTC: 2026-09-19T04:58:27Z
- IST: 2026-09-19 10:28 IST (Saturday, market CLOSED)

## VM State
- Hostname: webserver
- VM IP: 129.159.224.81
- VM User: ubuntu

## Git State
- Workspace: html/h31-shell-core-pages at 2bc70d0 (Phase 42A.9 fix)
- VM (/opt/tradingai): main at 20450f0d (15 commits behind, by design)

## Deployed Commit
- Workspace: 2bc70d0 — "Phase 42A.9: Production frontend runtime forensic repair"
- VM files match workspace (verified by SHA256)

## Services
| Service | Status |
|---------|--------|
| nginx | active (running) |
| gunicorn | 4 workers on 127.0.0.1:8000 |
| tradingai-api | active |

## Database
- Size: 269MB
- Integrity: ok

## Phase 42A.9 Assets Verified
All 15 JS files + 1 CSS file return HTTP 200 on HTTPS ✅
All hashes match workspace ✅
All core pages return HTTP 200 ✅
All core APIs return HTTP 200 ✅

## Cron Configuration (Mon-Fri during market hours)
- */5 9-15 * * 1-5: monitor.py
- */5 9-15 * * 1-5: pnl_tracker.py evaluate
- 0 3 * * 1-5 (9:30 IST): data_fetcher_db.py
- 35 9 * * 1-5: daily_page.py morning
- 35 15 * * 1-5: daily_page.py close + sitemap_gen.py
- 0 */2 9-15 * * 1-5: alert.py
- 20 15 * * 1-5: pnl_tracker.py close

## AI Configuration
- GROQ_API_KEY: /etc/tradingai/groq.env (mode 600)
- AI scheduler controlled by backend, NOT browser triggers

## Market State
- Saturday 2026-09-19: MARKET CLOSED
- Last trading day: Friday 2026-09-18
- Last NIFTY close: 23,346.40
- Last BANKNIFTY close: 56,358.70
- Last VIX: 11.39 (2026-09-18T16:40:23Z)