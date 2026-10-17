# Deployment (live 2026-10-14, OCI VM 129.159.224.81)

## Topology

Browser HTTPS to Cloudflare (Full-Strict) to nginx :80->301, :443 to
/opt/tradingai/frontend (static, .html no-store) + /api proxy to 127.0.0.1:8000
(rate 60r/m burst 30, CF real-IP) to gunicorn 2 workers x4 threads (gthread,
timeout 90s, max-requests 1000+jitter) to Flask app.api.app:app to
SQLite /opt/tradingai/database/tradingai.db (WAL, timeout=10) + yfinance.

## Install

- Python 3.10+, pip, nginx, certbot (tradingai.in + www, renew auto).
- pip install -r requirements.txt (flask 3.1.3, gunicorn 23.0.0, yfinance 0.2.66,
  requests, numpy, pandas, flask-cors, flask-limiter).

## systemd (live flags)

tradingai-api.service:
ExecStart=/usr/local/bin/gunicorn -w 2 --threads 4 --worker-class gthread \
 --bind 127.0.0.1:8000 --timeout 90 --graceful-timeout 15 --keep-alive 5 \
 --max-requests 1000 --max-requests-jitter 800 \
 --access-logfile /opt/tradingai/logs/gunicorn-access.log \
 --error-logfile /opt/tradingai/logs/gunicorn-error.log app.api.app:app
Restart=always. WorkingDirectory=/opt/tradingai.

- tradingai-market-data.service+timer: 5-min collector in market hours.
- tradingai-watchdog.service+timer: 2-min self-heal (API/homepage/disk/DB probes),
  cooldown-guarded restarts, logs/selfheal.log.
- Logrotate /etc/logrotate.d/tradingai with su ubuntu ubuntu.

## nginx (sites-enabled/tradingai)

- root /opt/tradingai/frontend
- limit_req_zone 60r/m, proxy_pass http://tradingai_api (127.0.0.1:8000)
- Serves .pre-*, .frozen-*, .backup_ as 410, security headers, CF real-IP.
- No service worker.

## Cron (ubuntu)

- paper_confluence.py --topup weekdays 15:45 IST
- tg_alerts.py --watch every 5 min 09-15 Mon-Fri (entry/exit Telegram only)
- weekly_review.py Sun 08:30
- events_coverage_check.py monthly (1st, 08:00) — warns before the scheduled-
  events calendar runs out of hand-encoded (HAND_ENCODED_END) or rule-generated
  (RECURRING_END) coverage; logs to logs/events_coverage.log.
- GA4 G-MJ3X88QYEL, Search Console, owner uptime monitor.

## Telegram

Bot @tradingai_CPR_bot to channel @tradingai_cpr. Format INST/date to
Direction/Level/Entry(ref)/SL to Strategy Exp Signal time, then outcome pill.
Archive frontend/alerts.html via scripts/build_alerts_page.py. Old records lack
Level/Expiry/Signal (not backfillable).

## Backups / freeze / rollback

- /home/ubuntu/backups/ + /opt/tradingai_backups/, freeze tarballs + sha.
- Freeze model: code 444/dirs 555; writable: database/, logs/, data/, research/, paper.html.
- Every change leaves *.pre-stamp beside source (excluded from git 2026-10-14).
- Rollback = copy back preserved files; frontend needs no restart;
  code needs systemctl restart tradingai-api.
- GATE: owner authorization per change; trigger/entry/exit/decay values unchanged Sep-28.

## Tests

- pytest tests/ -q. 32 files. Green: compliance, cpr_triggers, d1_calculator,
  fixall_economics, intrabar_entry, intraday_series, seo, unified_book, weekly_spreads.
- Slow/hang (>45s): test_core, test_phase7, test_phase8 (heavy multi-day replay).
  Add pytest-timeout, shrink fixtures.
- 72 failures in test_phase* (stale acceptance from older deployment; one references
  /opt/tradingai_new). Triage/retire before relying on suite. See docs/audit-2026-10-13.md.
- Note: /opt/tradingai is dr-xr-xr-x by default; chmod u+w for edits; .pytest_cache
  cannot write (warning only).

## Docs in repo

README.md, ARCHITECTURE.md, API.md, BACKTEST.md, DATABASE.md, DATA_SOURCES.md,
DEPLOYMENT.md (this file), SCENARIOS.md, STRATEGIES.md, FREEZE files, docs/ audits.
ARCHITECTURE drift fixed 2026-10-14 (CPR-trigger path is authoritative, not old scenarios).
