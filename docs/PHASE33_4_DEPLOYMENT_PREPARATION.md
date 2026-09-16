# Phase 33.4 — Deployment Preparation

Date: 2026-09-16
Status: COMPLETE ✅

## Executive Summary

Phase 33.4 answers: "How will the validated workspace be moved to production?"

**Key finding**: deploy-vm.sh exists and is well-structured, BUT it CANNOT run on the current VM state because:
- `/opt/tradingai` does not exist (Phase 30 finding)
- No systemd, no nginx, no gunicorn, no cron on VM
- No /opt/tradingai directory

The deployment path is understood. Infrastructure must be provisioned first. This is documented as a blocker/design decision, not silently worked around.

## 1. Current Workspace State

| Item | Value |
|------|-------|
| Branch | html/h31-shell-core-pages |
| Latest commit | 7518d1a (Phase 33.3 audit complete) |
| H31 modified | NO |
| HTML files audited | 52/52 |
| Broken internal links | 0 |
| Unexplained test failures | 0 (4 pre-existing) |
| Tests passing | 165/169 |
| DB state (workspace) | 46 tables, 15MB, 42K+ data rows |
| market_candles populated | 30,684 rows |

## 2. Deployment Script Audit

### deploy-vm.sh
Status: AUDITED — NOT SAFE TO EXECUTE on current VM

| Aspect | Finding |
|--------|---------|
| VM target | ubuntu@129.159.224.81 |
| SSH key | ~/.ssh/oci_key |
| Target dir | /opt/tradingai |
| Python deps | pip3 install (Flask, gunicorn, yfinance, etc.) |
| DB deploy | EXCLUDED (--exclude='database') — VM runs data_fetcher_db.py fresh |
| CSS deploy | static/css/*.css → /var/www/tradingai.in/html/assets/css/ |
| API start | systemd (tradingai-api.service) |
| Health gate | ops/health_gate.sh |
| Cron | ops/crontab.txt |
| Nginx | ops/nginx-tradingai.conf |
| Rollback | ops/rollback.sh |
| Requires | systemd, nginx, gunicorn, cron, /opt/tradingai — NONE exist on VM |

### deploy-vm.sh exclusions
```
--exclude='node_modules' --exclude='.next' --exclude='__pycache__' \
--exclude='.pytest_cache' --exclude='.git' --exclude='logs' \
--exclude='database' --exclude='data' --exclude='frontend'
```

**IMPORTANT**: `database` is excluded. The workspace DB (with our validated market_candles) will NOT be deployed. VM runs data_fetcher_db.py to create fresh DB. This is by design — prevents workspace DB conflicts.

### Other scripts audited
| Script | Purpose | Status |
|--------|---------|--------|
| scripts/deploy.sh | Phase 1 deploy with gates | AUDITED — requires deploy-vm.sh first |
| scripts/rollback.sh | Git checkout prev + DB restore + API restart | AUDITED — ready |
| scripts/health_check.sh | Component health checks | AUDITED — ready |
| scripts/backup.sh | DB backup with integrity check | AUDITED — ready |
| ops/vm-backup.sh | Daily off-site backup → vm-backup branch | AUDITED — requires github_backup key |
| ops/rollback.sh | Fast rollback (< 2 min) | AUDITED — ready |
| ops/health_gate.sh | API readiness + health gate | AUDITED — ready |
| ops/setup-new-vm.sh | Fresh VM setup | AUDITED — for new VM only |

## 3. Production Infrastructure

### VM Specification
| Item | Value | Source |
|------|-------|--------|
| IP | 129.159.224.81 | deploy-vm.sh, setup-new-vm.sh |
| OS | Ubuntu 22.04 | setup-new-vm.sh |
| User | ubuntu | deploy-vm.sh |
| SSH key | ~/.ssh/oci_key | deploy-vm.sh |
| Project dir | /opt/tradingai | deploy-vm.sh |
| Web root | /var/www/tradingai.in/html | deploy-vm.sh |

### Required Infrastructure Components
| Component | Status on VM | Required By |
|-----------|-------------|-------------|
| nginx | ❌ MISSING | serve static HTML, proxy /api/ |
| systemd | ❌ MISSING | manage API service |
| gunicorn | ❌ MISSING | API process manager |
| cron | ❌ MISSING | market data, backups |
| /opt/tradingai | ❌ MISSING | project directory |
| /etc/tradingai/groq.env | ❌ MISSING | GROQ API key |
| Let's Encrypt certs | ❌ MISSING | HTTPS |
| github_backup SSH key | ❌ MISSING | VM backups |

### Python Requirements
Source: ops/requirements.txt
```
yfinance==0.2.66
Flask==2.3.2
Flask-Cors==3.0.10
Flask-Limiter==3.11.0
pandas==2.3.3
numpy==2.2.6
requests==2.32.5
curl_cffi
gunicorn==23.0.0
```

### API Configuration
| Item | Value | Source |
|------|-------|--------|
| Entrypoint | api_server.py | backend/ |
| Bind | 127.0.0.1:8000 | systemd/tradingai-api.service |
| Workers | 3 (sync) | systemd |
| Timeout | 90s | systemd |
| CORS origins | https://tradingai.in, https://www.tradingai.in | systemd env |
| Logs | /opt/tradingai/logs/ | systemd |
| Health endpoint | /api/health | scripts/health_check.sh |
| Ready endpoint | /api/ready | ops/health_gate.sh |

### External nginx Configuration
Source: ops/nginx-tradingai.conf
| Route | Behavior |
|-------|----------|
| / | Static files, try_files → index.html |
| /api/ | Proxy to 127.0.0.1:8000, 10s cache |
| /home.html | 301 → / (confirmed by nginx config) |
| /indices/market.html | 301 → /market.html |
| Legacy pages | 301 redirects (stocks, fixed-loss, etc.) |
| Static assets | CSS/JS/SVG cached 1h |
| /api/metrics | Deny all (internal only) |

## 4. Production Data Flow

```
External market data (yfinance, NSE APIs, FO bhavcopy)
        ↓
data_fetcher_db.py (cron: every minute during market hours)
        ↓
/opt/tradingai/database/tradingai.db (SQLite, WAL mode)
        ↓
market_candles, indicators, regimes, strategies, options, etc.
        ↓
api_server.py (gunicorn:3 workers on 127.0.0.1:8000)
        ↓
external nginx (129.159.224.81:80/443) → /api/ proxy → /static/ serve
        ↓
HTML/JS pages (/var/www/tradingai.in/html/)
        ↓
user browser
```

### Required Processes for Operational Flow
| Process | Start mechanism | Purpose |
|---------|----------------|---------|
| gunicorn (API) | systemd tradingai-api.service | Flask API |
| data_fetcher_db.py | cron (every minute 9-15 IST) | Market data |
| monitor.py | cron (every 5 min 9-15 IST) | Market monitoring |
| alert.py | cron (every 2 hours 9-15 IST) | Alerts |
| pnl_tracker.py | cron (specific times) | P&L tracking |
| daily_page.py | cron (9:35, 15:35 IST) | Daily pages |
| sitemap_gen.py | cron (15:35 IST) | SEO sitemap |
| vm-backup.sh | cron (18:30 daily) | Off-site backup |
| bhavcopy.py | cron (18:35, 08:30 IST) | FO data |
| self-heal.sh | cron (every 2 hours) | Process recovery |
| nginx | systemd | Web server |

## 5. Database Deployment Plan

### Strategy
The workspace DB is NOT deployed directly. deploy-vm.sh excludes `database/`. Instead:

1. **VM DB is created fresh** by running `db_schema.py` on deploy
2. **Data is populated** by running `data_fetcher_db.py` (with SKIP_LLM=1)
3. **Optional backfills** run if key tables have < 500 rows

### Safe Procedure
```
BACKUP existing production DB (if any)
  → VERIFY backup integrity
  → DEPLOY: rsync workspace (excl. database) → /opt/tradingai/
  → INITIALIZE: cd /opt/tradingai/backend && python3 db_schema.py
  → POPULATE: SKIP_LLM=1 python3 data_fetcher_db.py
  → VALIDATE: Check tables have data, endpoints return data
  → ROLLBACK: Restore previous DB backup if validation fails
```

### DB Locations
| Environment | Path |
|-------------|------|
| Workspace | /Users/satya/.../database/tradingai.db |
| Production VM (target) | /opt/tradingai/database/tradingai.db |

### DB Schema
- Created by: backend/db_schema.py (init_database)
- Tables: 46 (workspace), should match on VM
- Mode: WAL (workspace), should be WAL on VM

## 6. API Deployment Plan

### Process Manager
systemd (tradingai-api.service) — requires systemd on VM

### Deploy Sequence
1. rsync workspace → /opt/tradingai/ (excl. database, .git, logs)
2. pip3 install requirements (yfinance, flask, gunicorn, etc.)
3. Copy systemd unit → /etc/systemd/system/tradingai-api.service
4. systemctl daemon-reload
5. systemctl enable tradingai-api
6. systemctl restart tradingai-api
7. Run ops/health_gate.sh (polls /api/ready, /api/health)

### Health Verification
| Check | Endpoint | Expected |
|-------|----------|----------|
| API health | /api/health | {"status": "ok"} |
| API ready | /api/ready | {"ready": true} |
| Price | /api/price/NIFTY | 200, data present |
| Market | /api/market | 200, data present |

### Logging
- gunicorn: /opt/tradingai/logs/gunicorn-*.log
- API: /opt/tradingai/logs/api.log (via logging module)
- Data fetcher: /opt/tradingai/logs/data.log
- Health: /opt/tradingai/logs/health.log

## 7. Market-Data Process Plan

### Data Sources
| Source | Method | Frequency |
|--------|--------|-----------|
| yfinance (price data) | price_1m/5m/1d tables | Every minute (market hours) |
| NSE option chain | fo_fetcher.py | EOD (18:35 IST) + bhavcopy |
| VIX | vix_data table | Every minute (market hours) |
| Indicators | computed from price data | Every minute (market hours) |
| Regimes | computed from indicators | Every minute (market hours) |
| Strategies | computed from market state | Every minute (market hours) |
| AI outlook | LLM (Groq) | Daily (market close) |

### Fetcher Suitability
data_fetcher_db.py is designed for production use:
- Has circuit breakers (yfinance, nse_live)
- Has retry logic with backoff
- Has monitoring (RequestMonitor)
- Writes to SQLite with WAL mode
- Updates price_1m, price_5m, price_1d, indicators, regimes, strategies, etc.

**Gap**: market_candles table is populated by our Phase 33.1 manual fill. The production fetcher should also populate it. This is a gap to document for future phases.

## 8. External nginx / Proxy

### Required Routing
| Path | Destination | Notes |
|------|-------------|-------|
| https://tradingai.in/ | /var/www/tradingai.in/html/ | Static HTML |
| https://tradingai.in/index.html | Same as / | Same content |
| https://tradingai.in/api/ | 127.0.0.1:8000 | API proxy |
| https://tradingai.in/static/ | /var/www/tradingai.in/html/static/ | CSS/JS |
| https://tradingai.in/assets/ | /var/www/tradingai.in/html/assets/ | CSS/JS (mapped from static/) |
| http://tradingai.in → https | 301 redirect | Port 80 → 443 |
| /home.html → / | 301 redirect | Confirmed |
| /indices/market.html → /market.html | 301 redirect | Confirmed in nginx config |

### CORS
Production CORS origins: https://tradingai.in, https://www.tradingai.in
Configured via systemd env: TRADINGAI_CORS_ORIGINS

### Timeout/Cache
- API proxy: 10s cache, rate limited (60/min per IP)
- Static assets: 1h cache
- Data endpoints: no-store

## 9. Deployment Manifest

### DEPLOY
| Item | Source | Destination | Reason |
|------|--------|-------------|--------|
| HTML pages | workspace .html files | /opt/tradingai/ → /var/www/tradingai.in/html/ | Public content |
| CSS | static/css/*.css | /var/www/tradingai.in/html/assets/css/ | Styling |
| JS | static/js/*.js | /var/www/tradingai.in/html/assets/js/ | Interactivity |
| Backend Python | backend/*.py | /opt/tradingai/backend/ | API |
| API entrypoint | backend/api_server.py | /opt/tradingai/backend/ | API |
| DB schema | backend/db_schema.py | /opt/tradingai/backend/ | DB init |
| requirements | ops/requirements.txt | /opt/tradingai/ | Python deps |
| systemd unit | ops/systemd/tradingai-api.service | /etc/systemd/system/ | Process mgmt |
| nginx config | ops/nginx-tradingai.conf | /etc/nginx/sites-enabled/ | Web server |
| cron config | ops/crontab.txt | crontab - | Scheduled tasks |
| Config files | config/*.json | /opt/tradingai/ | App config |

### DO NOT DEPLOY
| Item | Reason |
|------|--------|
| tests/ | Development only |
| .git/ | Version control |
| logs/ | Ephemeral |
| database/ | VM creates fresh DB via data_fetcher_db.py |
| data/ | Data config (non-deployable) |
| docs/ | Documentation |
| .pytest_cache | Development artifact |
| __pycache__ | Python cache |
| node_modules | Not used (vanilla JS) |

## 10. Backup Plan

### Pre-Deployment Backup
1. Backup production HTML: rsync /var/www/tradingai.in/html/ → backup dir
2. Backup production backend: rsync /opt/tradingai/backend/ → backup dir (if exists)
3. Backup production DB: scripts/backup.sh → backups/tradingai_*.db
4. Record current commit: git rev-parse HEAD
5. Record process state: systemctl status, crontab -l, nginx -t

### Backup Scripts
| Script | Location | Purpose |
|--------|----------|---------|
| scripts/backup.sh | workspace | DB backup with integrity check |
| ops/vm-backup.sh | workspace | Daily off-site → vm-backup branch |
| ops/rollback.sh | workspace | Fast rollback (< 2 min) |
| scripts/rollback.sh | workspace | VM rollback with DB restore |

### Backup Retention
- scripts/backup.sh: 30 days (configurable via TRADINGAI_BACKUP_RETENTION_DAYS)
- ops/vm-backup.sh: Indefinite (git history)

## 11. Rollback Plan

### Rollback Triggers
- API health check fails after deploy
- Any critical endpoint returns 500
- Data_state = UNAVAILABLE on core endpoints (when previously LIVE)
- Broken navigation or H31 regression detected

### Rollback Procedure
1. **Restore DB**: cp backups/tradingai_*.db → /opt/tradingai/database/tradingai.db
2. **Restore code**: git checkout previous commit on VM
3. **Sync files**: rsync previous version → /opt/tradingai/
4. **Restart API**: systemctl restart tradingai-api
5. **Verify**: Run scripts/health_check.sh
6. **If rollback fails**: Restore forward: git checkout main && scripts/deploy.sh

### Rollback Scripts
| Script | Scope | Time |
|--------|-------|------|
| ops/rollback.sh | Code + API restart | < 2 min |
| scripts/rollback.sh | Code + DB + API | 5-10 min |

## 12. Prepared Deployment Commands

**PREPARED — NOT EXECUTED**

### A. Pre-deployment Inspection
```bash
# Check VM connectivity
ssh -i ~/.ssh/oci_key -o StrictHostKeyChecking=no ubuntu@129.159.224.81 "echo OK"

# Check current infrastructure
ssh -i ~/.ssh/oci_key ubuntu@129.159.224.81 "systemctl status nginx; systemctl status systemd; which gunicorn; crontab -l; ls /opt/tradingai 2>/dev/null"
```

### B. Backup
```bash
# If VM has existing deployment:
ssh -i ~/.ssh/oci_key ubuntu@129.159.224.81 "/usr/bin/bash /opt/tradingai/scripts/backup.sh"
```

### C. Transfer
```bash
# Deploy workspace to VM (excludes DB, .git, logs)
rsync -avz --delete \
  --exclude='node_modules' --exclude='.next' --exclude='__pycache__' \
  --exclude='.pytest_cache' --exclude='.git' --exclude='logs' \
  --exclude='database' --exclude='data' --exclude='frontend' \
  -e "ssh -i ~/.ssh/oci_key -o StrictHostKeyChecking=no" \
  /Users/satya/remove_workspace/tradingai.in_live_VM/ \
  ubuntu@129.159.224.81:/opt/tradingai/
```

### D. Install/Update
```bash
ssh -i ~/.ssh/oci_key -o StrictHostKeyChecking=no ubuntu@129.159.224.81 \
  "cd /opt/tradingai && pip3 install yfinance 'flask>=3.0' flask-cors flask-limiter && sudo pip3 install gunicorn==23.0.0"
```

### E. Database Initialization
```bash
ssh -i ~/.ssh/oci_key -o StrictHostKeyChecking=no ubuntu@129.159.224.81 \
  "cd /opt/tradingai/backend && /usr/bin/python3 db_schema.py"
```

### F. API Startup (requires systemd)
```bash
ssh -i ~/.ssh/oci_key -o StrictHostKeyChecking=no ubuntu@129.159.224.81 \
  "sudo cp /opt/tradingai/ops/systemd/tradingai-api.service /etc/systemd/system/tradingai-api.service && sudo systemctl daemon-reload && sudo systemctl enable tradingai-api && sudo systemctl restart tradingai-api"
```

### G. Market-Data Startup (requires cron)
```bash
ssh -i ~/.ssh/oci_key -o StrictHostKeyChecking=no ubuntu@129.159.224.81 \
  "crontab /opt/tradingai/ops/crontab.txt"
```

### H. Health Checks
```bash
ssh -i ~/.ssh/oci_key -o StrictHostKeyChecking=no ubuntu@129.159.224.81 \
  "cd /opt/tradingai && bash ops/health_gate.sh http://127.0.0.1:8000"
```

### I. Public Smoke Tests
```bash
# All URLs tested from local VM:
curl -s http://127.0.0.1:8000/api/health | python3 -m json.tool
curl -s http://127.0.0.1:8000/api/ready | python3 -m json.tool
curl -s "http://127.0.0.1:8000/api/key-levels?symbol=NIFTY" | python3 -m json.tool
curl -s "http://127.0.0.1:8000/api/intraday-conditions?symbol=NIFTY" | python3 -m json.tool
curl -s "http://127.0.0.1:8000/api/risk/NIFTY" | python3 -m json.tool
curl -s "http://127.0.0.1:8000/api/session-timeline" | python3 -m json.tool
curl -s "http://127.0.0.1:8000/api/market-outlook?symbol=NIFTY" | python3 -m json.tool
curl -s "http://127.0.0.1:8000/api/strategy/NIFTY" | python3 -m json.tool
```

### J. Rollback
```bash
ssh -i ~/.ssh/oci_key -o StrictHostKeyChecking=no ubuntu@129.159.224.81 \
  "cd /opt/tradingai && git checkout HEAD~1 && sudo systemctl restart tradingai-api"
```

## 13. Production Smoke Test Plan

### URL Verification
| URL | Expected | Checks |
|-----|----------|--------|
| https://tradingai.in/ | 200 | H1, canonical, title, nav, data_state |
| https://tradingai.in/index.html | 200 | Same as / |
| https://tradingai.in/today/index.html | 200 | H31 structure, all sections |
| https://tradingai.in/indices/nifty.html | 200 | NIFTY data, outlook, levels |
| https://tradingai.in/indices/banknifty.html | 200 | BANKNIFTY data |
| https://tradingai.in/indices/finnifty.html | 200 | FINNIFTY data |
| https://tradingai.in/indices/sensex.html | 200 | SENSEX data |
| https://tradingai.in/strategies.html | 200 | Strategy content |
| https://tradingai.in/strategy-builder.html | 200 | Builder UI |
| /home.html | 301 → / | Redirect |
| /indices/market.html | 301 → /market.html | Redirect |

### API Verification
| Endpoint | Status | Schema Check |
|----------|--------|-------------|
| /api/health | 200 | {status: ok} |
| /api/ready | 200 | {ready: true} |
| /api/market | 200 | data_state, instruments, timestamp |
| /api/market-outlook?symbol=NIFTY | 200 | bias, decision, outlook, timestamp |
| /api/key-levels?symbol=NIFTY | 200 | supports, resistances, data_state |
| /api/intraday-conditions?symbol=NIFTY | 200 | bullish, bearish, no_trade, data_state |
| /api/risk/NIFTY | 200 | max_risk, warnings, timestamp |
| /api/risk/BANKNIFTY | 200 | Same |
| /api/strategy/NIFTY | 200 | strategies[], strategy fields |
| /api/session-timeline | 200 | state, pre_market, open_market, close |
| /api/price/NIFTY | 200 | price, change, timestamp, data_quality |
| /api/oi-top?symbol=NIFTY | 200 | Array with open_interest |
| /api/breadth | 200 | advances, declines, unchanged |
| /api/options/state/NIFTY | 200 | pcr, oi, max_pain |
| /api/replay/NIFTY/2026-09-15 | 200/404 | Replay data or appropriate 404 |

### For Every API Test
- HTTP status
- Valid JSON
- Schema match
- Correct symbol
- Valid timestamp
- data_state present (LIVE/UPDATED/STALE/UNAVAILABLE/ERROR)
- No NaN
- No undefined
- No fabricated/default market values
- Correct UNAVAILABLE/ERROR where data unavailable

## 14. Risks

| Risk | Severity | Mitigation |
|------|----------|-----------|
| deploy-vm.sh requires systemd/nginx/cron not on VM | HIGH | Must provision infrastructure first (setup-new-vm.sh) |
| /opt/tradingai doesn't exist | HIGH | create before deploy |
| DB will be empty after deploy | HIGH | data_fetcher_db.py must run before verification |
| Workspace DB excluded from deploy | MEDIUM | By design — VM creates fresh DB |
| GROQ_API_KEY required for AI outlook | HIGH | Must create /etc/tradingai/groq.env on VM |
| External nginx config not on VM | HIGH | Must install ops/nginx-tradingai.conf |
| github_backup key for VM backups | MEDIUM | One-time setup required |
| market_candles not auto-populated by fetcher | MEDIUM | Documented gap for future phase |
| 4 pre-existing test failures | LOW | All classified (pre-existing, DB-dependent, legacy) |
| SSL certs (Let's Encrypt) | MEDIUM | Requires DNS + certbot |
| Deploy script not tested (deploy-vm.sh never run) | HIGH | Must verify each step manually |

## 15. Blockers

| # | Blocker | Severity | Resolution |
|---|---------|----------|-----------|
| 1 | No nginx on VM | HIGH | Install via apt (setup-new-vm.sh handles this) |
| 2 | No systemd on VM | HIGH | Install via apt (setup-new-vm.sh handles this) |
| 3 | No cron on VM | HIGH | Install via apt (setup-new-vm.sh handles this) |
| 4 | /opt/tradingai doesn't exist | HIGH | Create directory (deploy-vm.sh handles first step) |
| 5 | deploy-vm.sh never tested | HIGH | Must verify each SSH/rsync step manually |
| 6 | GROQ_API_KEY not on VM | HIGH | Create /etc/tradingai/groq.env with valid key |
| 7 | SSL certs not present | MEDIUM | certbot + DNS setup |
| 8 | github_backup deploy key | MEDIUM | One-time GitHub deploy key setup |

## 16. PASS/FAIL Gate

### DEPLOYMENT PREPARATION = PASS ✅

| Requirement | Result |
|-------------|--------|
| Production target identified | ✅ VM 129.159.224.81, /opt/tradingai |
| deploy-vm.sh audited | ✅ Fully inspected, not safe to run on current VM |
| Production infrastructure understood | ✅ Needs: nginx, systemd, cron, /opt/tradingai |
| Database deployment plan | ✅ READY — VM creates fresh DB via data_fetcher_db.py |
| API deployment plan | ✅ READY — systemd + gunicorn, full plan documented |
| Market-data plan | ✅ READY — cron + data_fetcher_db.py, documented gap for market_candles |
| Backup plan | ✅ READY — scripts/backup.sh + ops/vm-backup.sh + ops/rollback.sh |
| Rollback plan | ✅ READY — ops/rollback.sh (< 2 min) + scripts/rollback.sh |
| Deployment manifest | ✅ CREATED — docs/PHASE33_4_DEPLOYMENT_PREPARATION.md |
| Smoke-test plan | ✅ CREATED — 10 URLs + 15 API endpoints documented |
| Critical blockers | 8 — all infrastructure-dependent, not code issues |
| Deployment commands prepared | ✅ PREPARED — NOT EXECUTED |
| H31 modified | NO |
| Tests passing | 165/169 (4 pre-existing) |

### Blocker Resolution Path
All 8 blockers are infrastructure provisioning issues. Resolution:
1. Run ops/setup-new-vm.sh on VM (handles apt, nginx, systemd, cron)
2. Or manually install: apt-get install nginx cron, systemctl enable
3. Create /opt/tradingai directory
4. Deploy via deploy-vm.sh or manual rsync
5. Create /etc/tradingai/groq.env with GROQ_API_KEY
6. Run data_fetcher_db.py to populate DB
7. Verify all endpoints
8. THEN proceed to controlled deployment

## 17. Next Steps

1. **Authorize infrastructure provisioning** on VM (or run setup-new-vm.sh)
2. **Create GROQ_API_KEY** on VM at /etc/tradingai/groq.env
3. **Run deploy-vm.sh** (after infrastructure is provisioned)
4. **Run health gate** (ops/health_gate.sh)
5. **Crawl all 52 production URLs**
6. **Proceed to Phase 33.5+** or release gate

---

**Phase 33.4 = PASS**
**Deployment executed = NO**
**H31 modified = NO**
**deploy-vm.sh audited = YES**
**Production infrastructure understood = YES**
**Database deployment plan = READY**
**API deployment plan = READY**
**Market-data plan = READY**
**Backup plan = READY**
**Rollback plan = READY**
**Deployment manifest = CREATED**
**Smoke-test plan = CREATED**
**Critical blockers = 8 (all infrastructure)**
**Deployment commands executed = NO**
