# Deployment Integrity — Phase 42A.9

## Workspace vs VM File Comparison

### Core HTML Pages

| File | Workspace Hash | Workspace Size | VM Hash | VM Size | Match |
|------|---------------|----------------|---------|---------|-------|
| index.html | 4ce39cdc | 42187 | 4ce39cdc | 42187 | ✅ |
| trade.html | cd80567a | 13802 | cd80567a | 13802 | ✅ |
| strategies.html | 2fde1aa6 | 29420 | 2fde1aa6 | 29420 | ✅ |
| indices/nifty.html | 814bf4e5 | 29893 | 814bf4e5 | 29893 | ✅ |
| indices/banknifty.html | 40382760 | 27552 | 40382760 | 27552 | ✅ |
| indices/sensex.html | ba1285ae | 21048 | ba1285ae | 21048 | ✅ |
| indices/finnifty.html | 47a660e0 | 23854 | 47a660e0 | 23854 | ✅ |
| options/pcr.html | 2f239857 | 20065 | 2f239857 | 20065 | ✅ |

### CRITICAL MISSING FILES

| File | Workspace Hash | Workspace Size | VM Status |
|------|---------------|----------------|-----------|
| today/index.html | 3fac1bc8 | 25935 | ❌ MISSING (404) |
| tools/backtest.html | c9f85bc0 | 20877 | ❌ MISSING (404) |
| tools/intelligence.html | — | — | ❌ MISSING (404) |
| tools/journal.html | — | — | ❌ MISSING (404) |
| tools/position-size.html | — | — | ❌ MISSING (404) |
| tools/walkforward.html | — | — | ❌ MISSING (404) |

### Static Assets — CRITICAL: ALL MISSING ON VM

| File | Workspace Hash | VM Status |
|------|---------------|-----------|
| static/js/api.js | fa6c9bfe | ❌ MISSING (404) |
| static/js/ai-outlook.js | — | ❌ MISSING (404) |
| static/js/consent.js | — | ❌ MISSING (404) |
| static/js/live-blink.js | — | ❌ MISSING (404) |
| static/js/keep-scroll.js | — | ❌ MISSING (404) |
| static/js/banknifty.js | — | ❌ MISSING (404) |
| static/js/charts.js | — | ❌ MISSING (404) |
| static/js/dashboard.js | — | ❌ MISSING (404) |
| static/js/history.js | — | ❌ MISSING (404) |
| static/js/index-charts.js | — | ❌ MISSING (404) |
| static/js/market.js | — | ❌ MISSING (404) |
| static/js/nifty.js | — | ❌ MISSING (404) |
| static/js/options.js | — | ❌ MISSING (404) |
| static/js/phase41.js | — | ❌ MISSING (404) |
| static/js/scanner.js | — | ❌ MISSING (404) |
| static/js/strategies.js | — | ❌ MISSING (404) |
| static/css/main.css | d7429ad5 | ❌ MISSING (404) |

## Root Cause Analysis

### Why /assets/ returns 404

In the workspace:
- `/assets/js` → symlink → `../static/js` → workspace static JS files
- `/assets/css` → symlink → `../static/css` → workspace CSS files

The deploy-vm.sh copies:
```
cp $PROJECT_DIR/static/css/*.css /var/www/tradingai.in/html/assets/css/
cp $PROJECT_DIR/static/js/*.js /var/www/tradingai.in/html/assets/js/
```

But `/opt/tradingai/static/` directory **NEVER EXISTED** on the VM. The rsync deployment from workspace to `/opt/tradingai/` did not include `static/` (likely because static/ was added to workspace AFTER the last successful deploy-vm.sh run).

### Why /today/ and /tools/ are missing

The directories `/opt/tradingai/today/` and `/opt/tradingai/tools/` do NOT exist on VM. These subdirectories exist in workspace but were apparently not synced by the rsync step (deployed before these directories existed).

### nginx behavior with missing /assets/

- nginx root: `/var/www/tradingai.in/html`
- `/assets/js/api.js` → resolves to `/var/www/tradingai.in/html/assets/js/api.js` → **404**
- nginx regex location for `*.js|css` → `try_files $uri =404` → **404**
- The nginx config has NO special location block for `/assets/` (no alias, no rewrite)

## Git State Discrepancy

| Location | Branch | Commit |
|----------|--------|--------|
| Workspace | html/h31-shell-core-pages | 0a6af05 |
| VM (/opt/tradingai) | main | 20450f0d (15 commits behind main) |

VM git is on `main` at `20450f0d` — this is the source-of-truth deployment state. The workspace has newer commits (Phase 42A.8 at 82be1aa/0a6af05). Deploy-vm.sh rsyncs workspace → /opt/tradingai/, so the VM static files are supposed to come from workspace.

## Verified HTTP Statuses (Public HTTPS)

| URL | Status |
|-----|--------|
| https://tradingai.in/ | 200 (but JS assets 404) |
| https://tradingai.in/index.html | 200 (but JS assets 404) |
| https://tradingai.in/today/index.html | 404 |
| https://tradingai.in/tools/backtest.html | 404 |
| https://tradingai.in/indices/nifty.html | 200 (but JS assets 404) |
| https://tradingai.in/trade.html | 200 (but JS assets 404) |
| https://tradingai.in/strategies.html | 200 (but JS assets 404) |
| https://tradingai.in/assets/js/api.js | 404 |
| https://tradingai.in/assets/js/ai-outlook.js | 404 |
| https://tradingai.in/assets/css/main.css | 404 |
| https://tradingai.in/api/market | 200 |
| https://tradingai.in/api/price/NIFTY | 200 |
| https://tradingai.in/api/vix | 200 |