# PHASE 6B-3 — Production Rebuild & Deployment Validation Record

**Status**: 🟢 VALIDATED (deployment milestone — not a code freeze; code freeze remains `8c9faff`)

**Deployed commit**: `b3bc5cf` (B.6 freeze record; code = `8c9faff`)

**Analytical freeze**: `8c9faff` 🔒 (lineage `45f90fc` → … → `d4990e4` → `4b7260f` → `8c9faff` preserved)

**Deployment timestamp**: 2026-09-14 ~13:57–14:01 IST (VM-local)

**Method**: clean rebuild from git — fresh `git clone git@github.com:vedurada/tradingai-lightweight.git`
at `/opt/tradingai`, from-scratch environment setup, live DB restore, full validation.
Stronger evidence than in-place upgrade. No model/engine code modified for this record.

---

## Deployment Evidence

| Item | Result |
|---|---|
| GitHub `origin/main` | ✅ `b3bc5cf`, verified via `ls-remote` |
| Fresh clone | ✅ Clean tree at `b3bc5cf`, `main...origin/main` in sync |
| Model files | ✅ 0/8 changed |
| Dependencies | ✅ Installed from scratch (yfinance, flask>=3.0, flask-cors, flask-limiter, gunicorn 23.0.0, pytest) |
| Database | ✅ Initialized via `db_schema.py`, live DB restored (price_1d: 17,372 rows) |
| Secrets | ✅ `/etc/tradingai/groq.env` preserved (never in git, never moved) |
| Systemd | ✅ Unit installed, daemon-reload, enabled, active |
| Nginx | ✅ Config installed, `nginx -t` clean, reloaded |
| Logrotate | ✅ `tradingai`, `tradingai-api`, `tradingai-gunicorn` installed |
| Crontab | ✅ Applied verbatim from frozen `deploy-vm.sh` logic (deduped one doubled line) |
| Webroot | ✅ Synced verbatim from frozen `deploy-vm.sh` logic |
| Tests (live VM) | ✅ 469/469 |
| Readiness | ✅ `READINESS PASS` (`/api/ready` → `{ready: true}`) |
| Health gate | ✅ `HEALTH GATE PASS` |
| Deep health | ✅ `all_healthy: true`, all 4 tables ok |
| DB size | ✅ 168.9 MB in `/api/health` |
| Warnings | ✅ None |
| Self-heal/backup | ✅ `backup_age 0d`, `backup_integrity: gzip verified`, `backup_row_compare: within 5%` |
| Public site | ✅ `https://tradingai.in` HTTP 200 |

---

## Safety & Rollback Assets (all preserved on VM)

| Asset | Location |
|---|---|
| Pre-rebuild safety backup (DB via sqlite backup API, crontab, nginx conf, groq.env) | `/opt/safety-20260914-1357/` |
| Previous production tree (code + DB + logs, 314M) | `/opt/tradingai.prev-20260914-1357/` |
| Previous webroot | `/var/www/tradingai.in/html.prev-20260914-1357/` |
| Previous nginx site config | `/opt/safety-20260914-1357/nginx-tradingai.conf.prev` |
| Rolling backup snapshots | `/opt/tradingai-backup/` (untouched) |

**Rollback procedure**: stop `tradingai-api`; `mv /opt/tradingai /opt/tradingai.failed-<ts>`;
`mv /opt/tradingai.prev-20260914-1357 /opt/tradingai`; restore webroot and nginx conf
from safety assets; `daemon-reload`, restart service, `nginx -t` + reload, run
`ops/health_gate.sh`. No DB surgery needed (previous tree carries its own DB).

---

## Incident During Rebuild (resolved, no production defect in final state)

Renaming the nginx site config aside left the backup file **inside** `sites-enabled/`,
producing a duplicate `limit_req_zone "api_limit"` emerg on `nginx -t` (and a failed reload;
the running workers kept serving the old config — public site never dropped).
Resolution: backup moved to `/opt/safety-20260914-1357/`; `nginx -t` clean; reloaded;
final gate PASS + public 200. Lesson: renames must move backups out of included config
directories — applied immediately during this same rebuild.

---

## Governance

- Analytical/model boundary: 🔒 FROZEN (this record is documentation-only).
- No B.7, no analytical tuning, no confidence changes, no new production features
  until a new scope review is explicitly opened.

---

🛑 **STOP.**

*End of Production Rebuild & Deployment Validation Record.*
