# PHASE 7 — Pre-Deployment VM Cleanup: Inventory + Manifest

**Status**: 🟡 INVENTORY COMPLETE (read-only). Nothing deleted, nothing modified.
**VM**: `ubuntu@129.159.224.81`, `/opt/tradingai` at `3d4f7ca`, disk 31% (no pressure).
**Rule**: every DELETE/FIX below needs explicit approval. Local repo untouched.

---

## Keep (required, verified present)

| Item | State |
|---|---|
| Production DB `database/tradingai.db` 197M + WAL | KEEP — live, written 15:21 today |
| `tradingai-api.service` (active, running, 4 gunicorn workers) | KEEP |
| nginx config + SSL (site 200, HSTS live) | KEEP — note: `nginx -t` as ubuntu fails on key perms; under sudo: syntax ok, test successful |
| Market-hours crontab (fetch/monitor/alert/pnl/outlook/mf/etf/backup) | KEEP (structure; duplicates fixed separately below) |
| Logs 552K, webroot 948K (pre-Track-B: no ads.txt/consent.js — expected) | KEEP |

## Manifest — proposed actions

| # | Item | Location | Class | Action |
|---|---|---|---|---|
| C1 | Transfer bundles `live_vm.bundle`, `live_vm2.bundle`, `live_vm3.bundle` (~96M) | `/tmp/` | obsolete (push-transfer artifacts) | DELETE |
| C2 | `.pytest_cache/` | `/opt/tradingai/` | test artifact | DELETE |
| C3 | `backend/__pycache__/`, `tests/__pycache__/` | `/opt/tradingai/` | regenerable bytecode | DELETE |
| C4 | Duplicate crontab lines: `cleanup.sh` ×5 (keep 1), repeated `# TradingAI Market Hours Cron` headers ×4 | VM crontab | deploy-accumulated dupes | FIX (rewrite without dupes, same jobs) |
| C5 | Glued cron line 30: `self-heal.sh … 2>&1 echo */15 … aggregate.py sweep` — aggregate sweep never runs as a job | VM crontab | malformed (missing separator) | FIX (split into two proper entries) |
| C6 | Stale systemd ref `tradingai-data-fetcher.service` (not-found/failed, no unit file on disk) | systemd | ghost reference | `reset-failed` (cosmetic) |

## Root cause note (NOT part of cleanup — needs repo decision)

`deploy-vm.sh` line 64 rebuilds crontab each deploy but its `grep -v` filter does not
exclude `cleanup.sh`/headers (→ C4 dupes) and is missing a separator before the
aggregate `echo` (→ C5 glued line). Fixing the source requires a repo edit + commit;
proposed as a follow-up, not snuck into cleanup.

## Post-cleanup verification (planned)

 bundles gone · pycache gone · `crontab -l` has 1 cleanup line + split self-heal/aggregate lines ·
`systemctl --failed` empty · nginx serves 200 · `/api/health` ok · DB row counts unchanged.

---

🛑 **STOP — inventory only. Awaiting explicit approval of C1–C6 before any deletion.**
