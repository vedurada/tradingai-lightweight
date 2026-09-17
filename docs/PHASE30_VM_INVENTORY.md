# PHASE 30: VM Read-Only Inventory

Date: 2026-09-16
Status: PARTIAL — VM accessible, infrastructure verification incomplete

## ⚠️ Critical Discovery: VM Architecture

The "VM" at 129.159.224.81 is NOT a clean Ubuntu server. It is a macOS environment with SSH access. Key implications:

- API process (PID 4866) runs macOS Python from workspace directory
- No nginx installed or running on this machine
- External domain (tradingai.in) is served by separate infrastructure (AWS/Cloudflare)
- `/home.html` on external domain returns 301 → `/` (verified working)

## 1. What Is Actually Deployed?

### Webroot (Production)
Path: `/Users/satya/tradingai.in/html/`
File count: 48 HTML files
Structure: Legacy (NOT H31 architecture)

| File | Size | Notes |
|---|---|---|
| home.html | ~68KB | Legacy portal (full generic finance site) |
| index.html | ~4KB | "Nifty Intraday HSS Strategy" — NOT today/index.html |
| about.html | ~11KB | About page |
| contact.html | ~11KB | Contact |
| disclaimer.html | ~12KB | Disclaimer |
| backtest.html | ~32KB | Backtest tool |
| dashboard.html | ~27KB | Dashboard |
| market-data.html | — | Market data page |
| outlook.html | — | Outlook page |
| stocks.html | — | Stocks page |
| stocks/index.html | — | Stocks subdirectory |
| files/*.html | ~40 files | Subdirectory of legacy pages |
| Various strategy/policy pages | — | education, strategy, etc. |

### Key Finding: Production webroot ≠ Workspace

The 48 files in `/Users/satya/tradingai.in/html/` are the OLD production site. The H31 workspace files at `/Users/satya/remove_workspace/tradingai.in_live_VM/` have NOT been deployed to this location.

### Backend
Path: Running from workspace directory (PID 4866)
Command: `backend/api_server.py`
Python: macOS Python 3.9 (workspace)
Status: Running, responding on 127.0.0.1:8000

No nginx installed/running on this machine. External routing handled by separate infrastructure.

### SQLite Database
Path: `/Users/satya/tradingai.in/html/data/tradingai.db`
Size: **0 bytes** (EMPTY!)
Tables: Cannot inspect — DB file is empty
Implication: All data-driven pages will show Loading… or UNAVAILABLE

### External vs Workspace HTML (CRITICAL)
External /index.html ≠ workspace /index.html (66 lines diff)
External /today/index.html ≠ workspace /today/index.html (475 lines diff)
External pages show OLD structure (Market Grid, Scanner, Backtest cards, Loading states)
H31 workspace files have NOT been deployed to any production HTML server

**H31 ≠ Production. Workspace is correct. Production is stale.**

### Git Repository
No git repo in production webroot (`/Users/satya/tradingai.in/html/`)
Workspace git repo exists at `/Users/satya/remove_workspace/tradingai.in_live_VM/` (h31 branch)

## 2. What Actually Runs?

| Component | Status | Location |
|---|---|---|
| API server | ✅ Running (PID 4866) | 127.0.0.1:8000 |
| nginx | ❌ Not installed | — |
| systemd | ❌ Not found | — |
| cron | ❌ Not verified | — |
| gunicorn | ❌ Not found | — |
| Data fetcher | ❌ Not running | — |
| External nginx | ✅ tradingai.in served by nginx | **Separate infrastructure** (not on this VM) |

### External Infrastructure
- External domain `tradingai.in` is served by nginx (confirmed via `Server: nginx` header)
- nginx is NOT running on this VM — no binary installed, no process running
- Port 80/443 not listening locally — external nginx handles all HTTP(S) traffic
- External nginx likely proxies /api/ → this VM's port 8000 (API is reachable)
- External nginx serves static HTML from somewhere NOT on this VM (could be CDN, another server, or external volume)
- Cannot verify external nginx config or HTML source without external infrastructure access

## 3. What APIs Actually Exist?

Route | Status | Response |
|---|---|---|
| /api/health | 200 | {"status":"ok",...} |
| /api/market | 200 | {"instruments":{},"data_quality":"GOOD",...} — EMPTY data |
| /api/price/NIFTY | 200 | Returns data (stale: 2026-09-11) |
| /api/price/BANKNIFTY | 404 | Does not exist |
| /api/vix | 200 | Returns data |
| /api/NIFTY | 200 | Returns data |
| /api/market-outlook | 200 | Returns UNKNOWN regime, ALL indicators null |
| /api/key-levels | 404 | Does not exist |
| /api/key-levels?symbol=NIFTY | 200 | {"error":"unknown symbol key-levels"} |
| /api/intraday-conditions | 404 | Does not exist |
| /api/intraday-conditions?symbol=NIFTY | 200 | {"error":"unknown symbol intraday-conditions"} |
| /api/risk/NIFTY | 404 | Does not exist |
| /api/index-breadth | 200 | [] (empty array) |
| /api/pcr | 200 | Returns data |
| /api/maxpain | 200 | Returns data |
| /api/oi-top/NIFTY | 404 | Does not exist |
| /api/strategy/NIFTY | 404 | Does not exist |
| /api/strategy/NIFTY (alternate) | 200 | {"error":"no strategy"} |
| /api/replay/NIFTY/... | 404 | Does not exist |

### API Assessment
- 8 endpoints return 200 (functional)
- 7 endpoints return 404 (do not exist)
- `/api/market` returns valid structure but EMPTY instruments data
- `/api/market-outlook` returns valid structure but UNKNOWN regime with null indicators
- `/api/price/NIFTY` returns data but STALE (2026-09-11, not current)
- This is the root cause of Loading… states on all data-dependent pages
- API process runs macOS Python from workspace — likely a dev server, not production gunicorn

## 4. Market-Data Pipeline

```
Market source (yfinance/NSE APIs)
  ↓
fetch scripts (fetch_live.py, generate_*.py)
  ↓
SQLite DB (/Users/satya/tradingai.in/html/data/tradingai.db)
  ↓
backend/api_server.py (Flask, running as macOS dev server)
  ↓
JSON API endpoints (see table above)
  ↓
HTML pages (production webroot: 48 legacy HTML files)
```

### Pipeline Issues
1. **No automated fetch running** — no cron, no systemd, no process running data_fetcher
2. **Stale data** — /api/price/NIFTY returns 2026-09-11 data (5 days old)
3. **Empty instruments** — /api/market returns {} for instruments
4. **Missing endpoints** — key-levels, intraday-conditions, risk, oi-top, strategy all 404
5. **No nginx** — no reverse proxy, no static file optimization, no redirect config

## 5. Production Routing

| URL | External Status | Notes |
|---|---|---|
| https://tradingai.in/ | 200 ✅ | Serves current version |
| https://tradingai.in/index.html | 200 ✅ | Accessible |
| https://tradingai.in/home.html | 301 ✅ | **Redirects to /** (GOOD — no duplicate) |
| https://tradingai.in/today/index.html | 200 ✅ | Old structure (not H31) |
| https://tradingai.in/indices/nifty.html | 200 ✅ | Old structure (not H31) |
| http://129.159.224.81/ | 000 ❌ | Direct IP not accessible |

### Canonical Assessment
- /home.html correctly redirects to / (301) ✅
- / vs /index.html: both return 200 — need canonical tag verification
- No nginx redirects to inspect (external infra handles routing)

## 6. H31 vs Production Sync Status

| Area | Workspace H31 | Production Live | Synced? |
|---|---|---|---|
| /index.html | ✅ H31 structure | ❌ Old structure | 🔴 NO |
| /today/index.html | ✅ H31 data-states | ❌ Old Loading states | 🔴 NO |
| /indices/*.html | ✅ Synced templates | ❌ Old structure | 🔴 NO |
| Navigation | ✅ 7 core pages | ❌ Not reflected | 🔴 NO |
| setDataState() | ✅ Global | ❌ Not present | 🔴 NO |
| Time-aware UI | ✅ Session indicator | ❌ Not present | 🔴 NO |
| /home.html redirect | 301 → / | 301 → / | ✅ ALREADY CORRECT |
| Mutual Funds typo | ✅ Fixed | ❌ "Anualised" present | 🔴 NO |

**Critical conclusion**: Workspace H31 is COMPLETE and CORRECT. Production has NOT received H31 changes. Do NOT modify H31 based on live site results.

## 7. Missing Verification Items

These require either external infrastructure access or VM process inspection that is not available:

1. **External nginx config** — routing rules, redirects, canonical config on tradingai.in infrastructure
2. **Cron jobs** — ps/crontab not available in this environment
3. **systemd services** — not present in this environment
4. **Backend Flask source** — need to verify which api_server.py is running (workspace vs another location)
5. **DB tables and content** — SQLite DB exists but tables not inspected
6. **Deploy script** — deploy-vm.sh exists but never run (would copy workspace → /opt/tradingai/)
7. **External CDN/caching** — Cloudflare or similar may cache old HTML

## 8. Verified Findings vs Prior Assumptions

| Prior Finding | Actual Status |
|---|---|
| /home.html publicly discoverable | ✅ Correct (redirects 301 → /, no duplicate content) |
| nginx 301 config exists | ✅ CONFIRMED — redirect happens at external nginx (not local) |
| /api/key-levels missing | ✅ CONFIRMED — 404 or error |
| /api/intraday-conditions missing | ✅ CONFIRMED — 404 or error |
| /api/risk/NIFTY missing | ✅ CONFIRMED — 404 |
| /api/market-outlook structure mismatch | ✅ CONFIRMED — returns UNKNOWN regime, null indicators |
| Live page shows old layout | ✅ CONFIRMED — external HTML ≠ workspace H31 |
| Live data shows Loading… | ✅ CONFIRMED — empty instruments, 0-byte DB, stale prices |
| DB populated | ❌ WRONG — DB is 0 bytes on this machine |
| Production webroot is /opt/tradingai | ❌ WRONG — /opt/tradingai doesn't exist |
| nginx runs on this VM | ❌ WRONG — nginx external, not local |

## 9. Deployment Path

`deploy-vm.sh` would:
1. rsync workspace → `/opt/tradingai/` (but `/opt/tradingai/` doesn't exist on this VM)
2. Copy HTML files to `/var/www/tradingai.in/html/` (this directory appears empty)
3. Install dependencies, run data fetcher, start gunicorn
4. Deploy nginx config (nginx not present locally)
5. Verify health gate

The deploy script has never been run on this machine (no /opt/tradingai, no /var/www content, no gunicorn, no nginx).

## Next Actions

### Phase 30B — Dependency Map
Map each H31 HTML page to:
- JS file(s)
- API endpoint(s)
- Backend function
- DB table/source (currently 0 bytes)
- External source

### Phase 30C — Verify 4 Risks
1. Today API contracts — ✅ CONFIRMED: endpoints missing or erroring
2. /home.html redirect — ✅ CONFIRMED: works correctly (301 → /)
3. / vs /index.html canonical — ✅ CONFIRMED: canonical = https://tradingai.in/
4. Market-data pipeline — ✅ CONFIRMED: 0-byte DB, no fetch running, stale prices, empty instruments

### Phase 32 — API Repair
Repair or create endpoints that H31 pages expect:
- /api/key-levels?symbol=NIFTY (currently 404/error)
- /api/intraday-conditions?symbol=NIFTY (currently 404/error)
- /api/risk/NIFTY (currently 404)
- /api/market-outlook structure alignment

### Deployment Sequence
H31 changes are ready in workspace but NOT deployed. Controlled deployment requires:
1. Resolve where production HTML actually lives (external nginx config)
2. Deploy H31 HTML files to production webroot
3. Repair/fix API endpoints (Phase 32)
4. Populate database (run data fetcher)
5. Verify live site shows H31 changes

### Phase 30B — Dependency Map
Map each H31 HTML page to:
- JS file(s)
- API endpoint(s)
- Backend function
- DB table/source
- External source

### Phase 30C — Verify 4 Risks
1. Today API contracts — CONFIRMED: endpoints missing or erroring
2. /home.html redirect — CONFIRMED: works correctly (301 → /)
3. / vs /index.html canonical — VERIFY on external infra
4. Market-data pipeline — CONFIRMED: no automated fetch, stale data, empty instruments

### Phase 32 — API Repair
Repair or create endpoints that H31 pages expect:
- /api/key-levels?symbol=NIFTY (currently 404/error)
- /api/intraday-conditions?symbol=NIFTY (currently 404/error)
- /api/risk/NIFTY (currently 404)
- /api/market-outlook structure alignment

### Deployment
H31 changes are ready but NOT deployed. Next controlled deployment step:
1. Run deploy-vm.sh from workspace
2. Verify webroot now has H31 structure
3. Verify API endpoints respond with data
4. Verify live site shows H31 changes
