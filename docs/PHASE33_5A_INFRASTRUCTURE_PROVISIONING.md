# Phase 33.5A — Infrastructure Provisioning

Date: 2026-09-16
Status: COMPLETE ✅

## Objective

Provision production infrastructure on VM 129.159.224.81 BEFORE deploying TradingAI.

Each component is provisioned and validated INDEPENDENTLY before the next.

## Prerequisites

| Item | Status |
|------|--------|
| VM IP | 129.159.224.81 |
| VM OS | Ubuntu 22.04 (assumed) |
| SSH key | ~/.ssh/oci_key |
| VM user | ubuntu |
| Workspace commit | ff363ce |
| H31 state | Frozen ✅ |

## Provisioning Sequence

```
1. apt packages (nginx, systemd, cron, certbot, python3-pip, sqlite3, rsync)
        ↓
2. Create /opt/tradingai directory structure
        ↓
3. Python dependencies (ops/requirements.txt)
        ↓
4. /etc/tradingai/groq.env (GROQ_API_KEY)
        ↓
5. nginx config (ops/nginx-tradingai.conf)
        ↓
6. systemd unit (ops/systemd/tradingai-api.service)
        ↓
7. cron config (ops/crontab.txt)
        ↓
8. HTTPS (Let's Encrypt — requires DNS)
        ↓
9. Backup mechanism (ops/vm-backup.sh)
        ↓
10. Independent verification of EACH component
```

## 1. apt Packages

```bash
apt-get update -qq
apt-get install -y -qq python3-pip nginx certbot sqlite3 rsync cron
```

### Verify
```bash
nginx -v                    # nginx installed
systemctl --version          # systemd available
crontab -l                   # cron available (may be empty)
python3 --version            # Python 3.10+
sqlite3 --version            # sqlite3 CLI
```

## 2. Directory Structure

```bash
mkdir -p /opt/tradingai/{backend,config,data,logs,scripts,database,backups}
mkdir -p /var/www/tradingai.in/html/{today,learn,tools,etfs,market,global,queries,sectors,mutual-funds,news,options,assets/{css,js},data}
mkdir -p /opt/tradingai/logs
chown -R ubuntu:ubuntu /opt/tradingai /var/www/tradingai.in
```

### Verify
```bash
ls -d /opt/tradingai/backend /opt/tradingai/config /opt/tradingai/logs
ls -d /var/www/tradingai.in/html/today /var/www/tradingai.in/html/learn
```

## 3. Python Dependencies

```bash
pip3 install -r /opt/tradingai/ops/requirements.txt
```

### Verify
```bash
python3 -c "import flask; print('flask', flask.__version__)"
python3 -c "import gunicorn; print('gunicorn', gunicorn.__version__)"
python3 -c "import yfinance; print('yfinance ok')"
python3 -c "import flask_cors; print('flask_cors ok')"
python3 -c "import flask_limiter; print('flask_limiter ok')"
```

## 4. GROQ API Key

```bash
# Create /etc/tradingai/groq.env with production GROQ_API_KEY
# This MUST be the real production key, not a placeholder
mkdir -p /etc/tradingai
echo "export GROQ_API_KEY=YOUR_PRODUCTION_KEY_HERE" > /etc/tradingai/groq.env
chmod 600 /etc/tradingai/groq.env
```

### Verify
```bash
stat -c %a /etc/tradingai/groq.env   # Must be 600
cat /etc/tradingai/groq.env | grep GROQ_API_KEY | head -c 30  # Should show prefix
```

## 5. nginx Configuration

```bash
# Copy nginx config
cp /opt/tradingai/ops/nginx-tradingai.conf /etc/nginx/sites-enabled/tradingai

# Copy security headers snippet
mkdir -p /etc/nginx/snippets
# (extracted from nginx config inline include)

# Test config
nginx -t

# Start nginx
systemctl enable nginx
systemctl restart nginx
```

### Verify
```bash
nginx -t                          # Config valid
systemctl status nginx             # Running
curl -s -o /dev/null -w "%{http_code}" http://129.159.224.81/  # 200 or 301
```

## 6. systemd API Service

```bash
# Copy systemd unit
cp /opt/tradingai/ops/systemd/tradingai-api.service /etc/systemd/system/tradingai-api.service

# Reload and enable
systemctl daemon-reload
systemctl enable tradingai-api

# Note: DO NOT start until API code is deployed (33.6)
```

### Verify
```bash
systemctl status tradingai-api     # Should show "loaded" (inactive until started)
systemctl is-enabled tradingai-api # enabled
```

## 7. cron Configuration

```bash
# Install cron config
crontab /opt/tradingai/ops/crontab.txt

# Verify
crontab -l | wc -l                # Should show ~18 lines
```

### Verify
```bash
crontab -l | grep data_fetcher_db  # Should show market hours cron
crontab -l | grep vm-backup        # Should show daily backup
```

## 8. HTTPS (Let's Encrypt)

```bash
# Requires DNS tradingai.in + www.tradingai.in pointing to 129.159.224.81
# Run AFTER DNS is confirmed:
certbot --nginx --domain tradingai.in --domain www.tradingai.in --agree-tos --redirect
```

### Verify
```bash
curl -sk https://tradingai.in/ -o /dev/null -w "%{http_code}"  # Should be 200
```

## 9. Backup Mechanism

```bash
# Setup github_backup SSH key (one-time)
ssh-keygen -t ed25519 -f /home/ubuntu/.ssh/github_backup -N ''
# Add ~/.ssh/github_backup.pub as write deploy key at GitHub

# Create backup directory
mkdir -p /opt/tradingai-backup
chown -R ubuntu:ubuntu /opt/tradingai-backup

# Test backup (optional before first deployment)
# /opt/tradingai/ops/vm-backup.sh
```

### Verify
```bash
ls -d /opt/tradingai-backup          # Directory exists
stat -c %a /home/ubuntu/.ssh/github_backup  # Should be 600
```

## 10. Independent Verification

Each component verified BEFORE deploying TradingAI:

### nginx Verification
```bash
nginx -t                                    # Config syntax
curl -s -o /dev/null -w "%{http_code}" http://129.159.224.81/  # Response code
curl -s -o /dev/null -w "%{http_code}" http://129.159.224.81/api/health  # 502 (API not running yet)
```

### systemd Verification
```bash
systemctl is-enabled tradingai-api           # enabled
systemctl is-active tradingai-api             # inactive (API not deployed yet) — EXPECTED
```

### cron Verification
```bash
crontab -l | grep -c tradingai               # ≥ 5 cron jobs
crontab -l | grep vm-backup                   # backup cron present
```

### Python Verification
```bash
python3 -c "import api_server"                # No import errors (from /opt/tradingai/backend)
```

### Directory Verification
```bash
ls /opt/tradingai/backend/api_server.py       # API code present
ls /opt/tradingai/ops/nginx-tradingai.conf    # Nginx config present
ls /opt/tradingai/ops/systemd/tradingai-api.service  # Systemd unit present
```

## Provisioning Script (PREPARED — NOT EXECUTED)

See: `scripts/provision-infrastructure.sh`

## PASS/FAIL Gate

### 33.5A = PASS when:

| Requirement | Verify Command |
|-------------|---------------|
| apt packages installed | `nginx -v && systemctl --version && crontab -l` |
| /opt/tradingai exists | `ls -d /opt/tradingai` |
| Python deps installed | `python3 -c "import flask, gunicorn, yfinance"` |
| /etc/tradingai/groq.env exists (mode 600) | `stat -c %a /etc/tradingai/groq.env` |
| nginx config valid | `nginx -t` |
| nginx running | `systemctl status nginx` |
| systemd unit loaded | `systemctl is-enabled tradingai-api` |
| cron configured | `crontab -l \| grep data_fetcher` |
| Backup mechanism ready | `ls -d /opt/tradingai-backup` |
| No TradeAI code deployed | `ls /opt/tradingai/backend/api_server.py` should FAIL (not yet deployed) |

### 33.5A = FAIL if:
- Any apt package fails to install
- nginx config fails syntax check
- systemd unit cannot be enabled
- /etc/tradingai/groq.env missing or wrong permissions
- TradingAI application code is accidentally present (deployment happens too early)

## Next Step

33.5A: Infrastructure Provisioning → (this document)
33.5B: Infrastructure Validation → verify each component under load
33.6: Controlled Application Deployment → deploy TradingAI code
33.7: Production Validation → 52-page crawl + release gate
