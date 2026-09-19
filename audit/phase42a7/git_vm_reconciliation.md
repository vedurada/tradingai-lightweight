# Git ↔ VM ↔ nginx ↔ HTTPS ↔ API ↔ DB Reconciliation

Date: 2026-09-19 08:45 IST
Classification: DOCUMENTED DISCREPANCY — deployment method explanation

## RECONCILIATION CHAIN

```
WORKSPACE GIT
     ↓ (commit + push)
DEPLOY-VM.SH (rsync)
     ↓
VM FILESYSTEM (/var/www/tradingai.in/html, /opt/tradingai/backend)
     ↓ (nginx config)
NGINX (127.0.0.1:8000 proxy → gunicorn; static files from /var/www/tradingai.in/html)
     ↓
PUBLIC HTTPS (https://tradingai.in)
     ↓ (API calls)
GUNICORN (user process, 4 workers, 127.0.0.1:8000)
     ↓ (Flask app)
BACKEND CODE (/opt/tradingai/backend/)
     ↓ (SQLAlchemy)
SQLITE (/opt/tradingai/database/tradingai.db)
```

## 1. GIT STATE

### Workspace Git
- Branch: `html/h31-shell-core-pages`
- Commit: `0c39eaa` — "Phase 42A.7: Complete public HTML/data audit and live validation framework"
- Status: Modified `audit/phase42a7/all_public_html_inventory.csv`, `deploy-vm.sh` (hook)
- Untracked: `audit/phase42a7/VM_HTML_API_DB_trace.csv`, test files
- Pushed: Yes (origin/html/h31-shell-core-pages)

### VM Git
- Branch: `main`
- Commit: `20450f0d` — "docs: Phase 0 audit report and AGENTS.md"
- Status: 60+ modified files (backend code + HTML from rsync deployment)
- Note: VM git does NOT reflect deployed code state

### Assessment
**DISCREPANCY DOCUMENTED**: VM git shows commit `20450f0d` on branch `main`, but deployed files are from workspace commit `0c39eaa` via rsync deployment (`deploy-vm.sh`). The git state on VM is a deployment tracking artifact, not a code source. The deployed code is authoritative per the VM-first rule, and its source is the workspace git at `0c39eaa`.

This is expected per deployment architecture:
- `deploy-vm.sh` uses rsync to push workspace files to VM
- VM git is not updated by rsync (files overwrite git state)
- VM git reflects the last `git checkout` on VM, which was Phase 0 audit

The modified files on VM (visible via `git status`) are exactly the files that were rsynced from workspace and differ from VM git HEAD. This confirms successful deployment.

## 2. VM FILESYSTEM

### Webroot
- Path: `/var/www/tradingai.in/html/`
- Contains: 54+ HTML files (37 from sitemap + 17 unexpected from VM filesystem)
- Last rsync: Via deploy-vm.sh (workspace commit 0c39eaa)

### Backend
- Path: `/opt/tradingai/backend/`
- Git: main@20450f0d (stale, by design)
- Files: Modified via rsync (4 Phase 42A fixes + other deployment changes)
- Running code: Matches workspace version (rsynced)

### Key Verification
```bash
# Files modified on VM (rsync deployment evidence)
git -C /opt/tradingai/backend status --short
# Shows ~60 modified files matching rsync deployment
```

## 3. NGINX

- Status: ACTIVE (running since Wed 2026-09-16)
- Config: `/etc/nginx/sites-enabled/tradingai`
- Root: `/var/www/tradingai.in/html`
- SPA fallback: `/` → serves index.html (all unmatched routes)
- Static .html: `try_files $uri =404` (strict, no directory index)
- API proxy: `/api/` → `http://127.0.0.1:8000`
- Legacy redirects: `/home.html`→`/`, `/market.html`→`/today/index.html`, `/index.html`→`/`
- Unexpected routes: All non-/api/ routes without explicit .html extension serve SPA shell
- No explicit location blocks for: /alerts, /portfolio, /scanner, /stock, etc. (static-only)

## 4. HTTPS

- All core pages return HTTP 200 via https://tradingai.in
- API endpoints return 200 (degraded mode — market closed Saturday)
- Redirects working: /home.html → /, /market.html → /today/index.html

## 5. API (Gunicorn)

- Process: Running (user process, not systemd-managed)
- Workers: 4 (config says 3, may have auto-scaled or leftover worker)
- Master PID: 1544251
- Started: 2026-09-19 07:52:05 IST
- Endpoint: 127.0.0.1:8000
- Systemd service: `/etc/systemd/system/tradingai-api.service` exists but INACTIVE
- API health: `{"status":"degraded","overall":"degraded"}` (market closed, expected)

### Health Check Result
- DB size: 267.84MB
- Tables checked: 4
- market_outlooks: ok (206 rows, max 2026-09-18)
- price_1d: ok (2705 rows)
- price_1m: degraded (data age 10.6h > max 1h)
- vix_data: ok (2578 rows)
- Overall: degraded (stale price/vix/outlook data — expected Saturday pre-market)

## 6. DATABASE

- Path: `/opt/tradingai/database/tradingai.db`
- Size: 268MB (267.84MB via API)
- Integrity: OK (verified via PRAGMA integrity_check)
- Tables: 61
- Backup: `/opt/tradingai/backups/tradingai_pre_phase42a7_*.db`

### Key Table Counts
- price_5m: 15960+
- market_regime: populated
- ai_outlooks: 39148 (legacy daily outlooks)
- ai_outlooks_5m: 0 (no live generation yet)
- market_snapshots_5m: 2 (replay-verified)
- market_evidence_5m: 1 (replay-verified)
- trade_journal: populated (Phase 9A)
- research_ai_call_log: 0 (no live AI calls)

## 7. DISCREPANCY ANALYSIS

| Layer | Expected | Actual | Status |
|-------|----------|--------|--------|
| Workspace git | 0c39eaa (html/h31-shell-core-pages) | 0c39eaa | ✓ |
| VM filesystem | Matches workspace via rsync | Matches workspace | ✓ |
| VM git | N/A (not deployment source) | 20450f0d (main, stale) | ⚠️ Expected |
| Nginx config | Serves from /var/www/tradingai.in/html | Correct | ✓ |
| HTTPS | 200 for all public pages | 200 | ✓ |
| API | 127.0.0.1:8000 via gunicorn | Running, responding | ✓ |
| DB | SQLite, integrity OK | OK | ✓ |
| Deployed code | Workspace 0c39eaa | Matches workspace | ✓ |

## 8. CRITICAL FIX STATUS (as of audit date)

| Fix | Workspace | VM | Deployed? | Status |
|-----|-----------|----|-----------|--------|
| trade.html duplicate loadData() | 2 definitions | 2 definitions | No | NOT FIXED |
| BANKNIFTY page duplicate link | Line 32 duplicate | Line 32 duplicate | No | NOT FIXED |
| NIFTY page index selector | 4 unique links | 4 unique links | Yes | CORRECT |
| ai-track-record data-sym/data-col | Missing | Missing | No | NOT FIXED |

## 9. RESOLUTION

The git↔VM discrepancy is a known deployment artifact. The rsync deployment method means:
1. Workspace git is the source of truth for code
2. VM filesystem matches workspace after rsync
3. VM git is stale by design (not updated by rsync)
4. Deployed code is verified by direct file comparison and API response

**No action required** for the git discrepancy itself. It is documented for transparency.

**Action required** for critical fixes: Apply fixes to workspace, commit, then deploy via rsync.

## 10. GUNICORN PROCESS MANAGEMENT NOTE

- Gunicorn running as user process (not systemd)
- `systemctl is-active gunicorn` returns INACTIVE (no systemd unit)
- `systemctl is-active tradingai-api` returns INACTIVE (service exists but not started via systemd)
- Process started 2026-09-19 07:52:05 (likely via self-heal.sh or manual restart)
- API is functional despite systemd showing inactive
- Self-heal cron (`*/2 * * * *`) restarts tradingai-api if health check fails
