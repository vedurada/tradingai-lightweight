# Phase 41C — Initial State

**Date**: 2026-09-17 21:17 IST
**Phase**: 41C — Production Live Validation & Phase 41 Freeze

---

## Git State

| Item | Value |
|------|-------|
| Branch | `html/h31-shell-core-pages` |
| Commit | `9d2dc0f` |
| Commit Message | Phase 41B: Frontend integration — qualification, paper trade, evidence on 5 pages + shared module |
| Working Tree | Clean (0 files changed) |
| Ahead of Origin | 0 |
| Behind Origin | 0 |
| Pushed | Yes (pushed to origin/html/h31-shell-core-pages) |
| Tags | phase35-complete (frozen) |

## VM Deployment State

| Item | Value |
|------|-------|
| VM Host | 129.159.224.81 |
| VM User | ubuntu |
| SSH Key | ~/.ssh/oci_key |
| Deploy Script | deploy-vm.sh (last run: 2026-09-17 ~21:02 IST) |
| Last Code Sync | 2026-09-17 21:01 IST (rsync + deploy-vm.sh) |

## VM System State

| Item | Value |
|------|-------|
| OS | Ubuntu 22.04.5 LTS |
| Disk | 45G total, 16G used, 30G available (35%) |
| Memory | 956MB total, 284MB used, 211MB free, 534MB available |
| CPU | 2 |
| Swap | 2GB (/swapfile, 61MB used) |
| Uptime | 9 days, 2:51 |
| Load | 0.03, 0.15, 0.16 |

## Service State

| Service | Status |
|---------|--------|
| nginx | active (running since 2026-09-16 06:13 IST) |
| tradingai-api (systemd) | active |
| gunicorn | 4 processes running (restarted 2026-09-17 21:02 IST) |
| cron | 59 entries |

## Database State

| Item | Value |
|------|-------|
| Path | /opt/tradingai/database/tradingai.db |
| Size | 181.9 MB |
| Modified | 2026-09-17 21:01 IST |
| Mode | WAL |

## Key Files On VM (Webroot)

| File | Size | Modified | Content |
|------|------|----------|---------|
| /var/www/tradingai.in/html/index.html | 36354 | 21:05 IST | FIXED: Home page (was wrong today page before fix) |
| /var/www/tradingai.in/html/today/index.html | 25583 | 21:01 IST | Today Terminal |
| /var/www/tradingai.in/html/indices/nifty.html | 28029 | 21:01 IST | NIFTY (with Phase 41) |
| /var/www/tradingai.in/html/indices/banknifty.html | 25854 | 21:01 IST | BANKNIFTY (with Phase 41) |
| /var/www/tradingai.in/html/indices/sensex.html | 19494 | 21:01 IST | SENSEX (standard) |
| /var/www/tradingai.in/html/indices/finnifty.html | 22134 | 21:01 IST | FINNIFTY (standard) |
| /var/www/tradingai.in/html/static/js/phase41.js | 22061 | 21:01 IST | Phase 41 shared module |
| /opt/tradingai/index.html | 36354 | — | Correct home page source |
| /opt/tradingai/today/index.html | 25583 | — | Correct today page source |

## Phase 41B Changes Synced

| File | Status |
|------|--------|
| static/js/phase41.js | Synced |
| today/index.html | Synced (3 new sections + JS) |
| index.html | Synced (3 new sections + JS) |
| indices/nifty.html | Synced (3 new sections + JS) |
| indices/banknifty.html | Synced (3 new sections + JS) |
| audit/phase41b_frontend_report.md | Synced |
| backend/replay_runner.py | Synced to /opt/tradingai/ (untracked) |

## Known Issues at Time of Recording

1. **/var/www/tradingai.in/html/index.html had wrong content (25797 bytes = today page)** — Fixed at 21:12 IST by copying from /opt/tradingai/index.html (36354 bytes)
2. **backend/replay_runner.py** — Untracked, not committed but synced to VM

## Public URLs

| URL | Status |
|-----|--------|
| https://tradingai.in/ | 200 (after fix: correct home page) |
| https://tradingai.in/today/ | 200 |
| https://tradingai.in/market.html | 200 |
| https://tradingai.in/indices/nifty.html | 200 |
| https://tradingai.in/indices/banknifty.html | 200 |
| https://tradingai.in/indices/sensex.html | 200 |
| https://tradingai.in/indices/finnifty.html | 200 |
| https://tradingai.in/options/pcr.html | 200 |
| https://tradingai.in/strategies.html | 200 |
| https://tradingai.in/strategy-builder.html | 200 |
| https://tradingai.in/tools/backtest.html | 200 |
| https://tradingai.in/tools/position-size.html | 200 |
