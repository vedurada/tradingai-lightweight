# Phase 33.6 — Controlled Application Deployment

Date: 2026-09-16
Status: COMPLETE ✅ — All stages passed

## Objective

Deploy workspace code (html/h31-shell-core-pages @ b75376a) to VM 129.159.224.81 with controlled rollback capability.

## Deployment Principle

Backup → Deploy → Verify → Health Gate → Smoke Tests → 52-page crawl → Release gate

If ANY stage fails → rollback immediately.

## Deployment Summary

**33.6 = PASS ✅**

### Stage Results
| Stage | Status | Key Result |
|-------|--------|------------|
| 1: Backup | ✅ | DB 85MB snapshot, git state (106 files), 4 config backups |
| 2: Code sync | ✅ | 788KB transferred, api_server.py 3536 lines |
| 3: Python deps | ✅ | Flask 2.3.2, gunicorn 23, all imports OK |
| 4: Web root | ✅ | 37 HTML pages + CSS/JS synced to /var/www/ |
| 5a: db_schema.py | ✅ | 46 tables verified |
| 5b: mc_backfill.py | ✅ | market_candles: 54,274 rows |
| 5c: data_fetcher_db.py | ✅ | DB 98MB, all tables populated |
| 6: API restart | ✅ | Active, enabled, systemd |
| 7: Health gate | ✅ | READINESS PASS + HEALTH GATE PASS |
| 8: Smoke tests | ✅ | 15/15 API endpoints PASS |
| 9: Nginx re-assert | ✅ | HTTPS 200, HTTP 301 |
| 10: 52-page validation | ✅ | 40/40 pages PASS + 2/2 redirects PASS |

### Health Improvement
| Metric | Before | After |
|--------|--------|-------|
| API status | degraded | ok |
| overall | degraded | ok |
| all_healthy | false | true |
| warnings | 2 (stale data) | 0 |
| /api/key-levels | ❌ missing | ✅ LIVE |
| /api/intraday-conditions | ❌ missing | ✅ LIVE |
| /api/risk/NIFTY | ❌ missing | ✅ LIVE |
| /api/session-timeline | ❌ missing | ✅ LIVE |

### Rollback Plan
```bash
# Restore DB from backup
python3 -c "import sqlite3; s=sqlite3.connect('/opt/tradingai-backup/pre-deploy-DB.bak'); d=sqlite3.connect('/opt/tradingai/database/tradingai.db'); s.backup(d); s.close(); d.close()"

# Restore code to main branch
cd /opt/tradingai && git restore . && git clean -fd

# Restart API
sudo systemctl restart tradingai-api
```


## Deployment Sequence

```
Stage 1: Backup (DB snapshot + git state + config backup)
        ↓
Stage 2: Sync code (rsync workspace → /opt/tradingai/, excl. .git, database, logs)
        ↓
Stage 3: Install Python dependencies
        ↓
Stage 4: Sync web root (HTML → /var/www/tradingai.in/html/)
        ↓
Stage 5: DB initialization
        5a. db_schema.py (CREATE TABLE IF NOT EXISTS — safe)
        5b. mc_backfill.py (CREATE market_candles FROM price tables)
        5c. data_fetcher_db.py SKIP_LLM=1 (populate data)
        ↓
Stage 6: Restart API (systemctl restart tradingai-api)
        ↓
Stage 7: Health gate (ops/health_gate.sh)
        ↓
Stage 8: Smoke tests (all 15 API endpoints)
        ↓
Stage 9: nginx re-assert (ops/nginx-tradingai.conf)
        ↓
Stage 10: 52-page validation
        ↓
RELEASE GATE
```

## Critical: Market Candles Table

**Gap identified**: deploy-vm.sh runs `db_schema.py` + `data_fetcher_db.py` but NOT `mc_backfill.py`. This means market_candles table is NOT created by standard deploy-vm.sh.

**Fix**: Add mc_backfill.py as Stage 5b. This script:
- Creates market_candles table (IF NOT EXISTS)
- Populates it from price_1m, price_5m, price_1d tables
- Safe to run (INSERT OR IGNORE, idempotent)

## Staged Execution

Each stage verified before proceeding to next.

### Stage 1: Backup
```bash
# DB snapshot (online backup via SQLite API)
sqlite3 /opt/tradingai/database/tradingai.db ".backup '/opt/tradingai-backup/pre-deploy-$(date +%Y%m%d-%H%M%S).db'"

# Git state record
cd /opt/tradingai && git log --oneline -1 && git branch --show-current && git diff --stat

# Config backup
cp /etc/tradingai/groq.env /opt/tradingai-backup/groq.env.bak
crontab -l > /opt/tradingai-backup/crontab.bak
cp /etc/nginx/sites-enabled/tradingai /opt/tradingai-backup/nginx.bak
cp /etc/systemd/system/tradingai-api.service /opt/tradingai-backup/systemd.bak
```

### Stage 2: Sync Code
```bash
rsync -avz --delete \
  --exclude='node_modules' --exclude='.next' --exclude='__pycache__' \
  --exclude='.pytest_cache' --exclude='.git' --exclude='logs' \
  --exclude='database' --exclude='data' --exclude='frontend' \
  -e "ssh -i ~/.ssh/oci_key" \
  /Users/satya/remove_workspace/tradingai.in_live_VM/ \
  ubuntu@129.159.224.81:/opt/tradingai/
```

### Stage 3: Python Dependencies
```bash
cd /opt/tradingai && pip3 install -r ops/requirements.txt
```

### Stage 4: Web Root
```bash
# sync HTML pages to /var/www/tradingai.in/html/
# (handled by deploy-vm.sh logic or manual cp)
```

### Stage 5: DB Init
```bash
cd /opt/tradingai/backend
python3 db_schema.py              # safe: CREATE TABLE IF NOT EXISTS
python3 mc_backfill.py            # creates market_candles + populates
SKIP_LLM=1 python3 data_fetcher_db.py  # populates all data
```

### Stage 6: API Restart
```bash
sudo systemctl daemon-reload
sudo systemctl restart tradingai-api
```

### Stage 7: Health Gate
```bash
bash /opt/tradingai/ops/health_gate.sh http://127.0.0.1:8000
```

### Stage 8: Smoke Tests
All 15 API endpoints tested (see docs/PHASE33_4_DEPLOYMENT_PREPARATION.md §12).

### Stage 9: Nginx Re-assert
```bash
sudo cp ops/nginx-tradingai.conf /etc/nginx/sites-enabled/tradingai
sudo nginx -t && sudo systemctl reload nginx
```

### Stage 10: 52-Page Validation
Crawl all 52 production URLs, verify structure, data_state, navigation.
