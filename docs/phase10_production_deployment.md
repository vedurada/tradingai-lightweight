# Phase 10 — Production Deployment & Operations

## Inspection (pre-change)

- nginx: config valid (`nginx -t` OK), unit **enabled** but process **dead
  since Sat 2026-09-19 19:21 IST**. `server_name tradingai.in
  www.tradingai.in`, `root /var/www/tradingai.in/html` (EMPTY — only `.`/`..`),
  `/api/*` → `127.0.0.1:8000`, valid Let's Encrypt cert, HTTP→HTTPS redirect.
- `tradingai-api.service`: `WorkingDirectory=/opt/tradingai_new`,
  `app.api.app:app`, running but unit **disabled** (no reboot survival).
- `/var/www/tradingai/html/`: ABSENT (legacy, inactive — left untouched).
- No strategy/code changes required for deployment.

## Changes applied

1. `systemctl enable tradingai-api.service` (verified `is-enabled`).
2. `systemctl start nginx` (verified active; already enabled).
3. Frontend deploy: webroot was empty, so backup
   (`/root/webroot-backup-2026-09-20.tgz`) is of an empty dir by record;
   copied `/opt/tradingai_new/frontend/` → `/var/www/tradingai.in/html/`,
   mode `u=rwX,go=rX`. Only the 5 validated pages + asset dirs; no legacy
   files existed or were introduced.
4. `systemctl restart tradingai-api` (Phase 9 code load) — done pre-deploy.

## Validation

- Localhost HTTPS 200: `/`, `index.html`, `indices/nifty.html`,
  `indices/banknifty.html`, `backtest.html`, `methodology.html`, `/api/health`.
- Public (direct, outside VM): all 6 pages HTTP 200; nifty title correct
  (`NIFTY 50 — AI Intraday Options Analysis | TradingAI`); `/api/health`
  returns LIVE with the project DB path (proxy works).
- Ghost path `/indices/market.html` → 301 (nginx guard, tested).
- `tests/test_phase10.py`: 6/6 pass (nginx active+enabled, API
  enabled+serving, webroot checksums == validated source, HTTPS pages,
  API proxy state contract, ghost-page guard).
- Full strategy suite unaffected (no app-code change in Phase 10);
  122/122 green on the same tree pre-deploy.

## Acceptance

nginx PASS / Gunicorn-API PASS / systemd persistence PASS / HTTPS PASS /
frontend deployed PASS / API proxy PASS / public pages PASS.

## Remaining ops notes

- No reboot test performed (would disrupt the running VM); persistence is by
  unit enablement, verified via `is-enabled`.
- Asset subdirs (`css/images/js`) deploy empty (source state); no broken
  references (pages are self-contained inline CSS/JS).
