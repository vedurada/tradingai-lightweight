#!/bin/bash
# Phase 33.5A — Infrastructure Provisioning Script
# PROCEED WITH CAUTION — this provisions infrastructure, NOT TradingAI code
# Do NOT run if /opt/tradingai already contains TradingAI application code

set -euo pipefail

VM_HOST="129.159.224.81"
VM_USER="ubuntu"
SSH_KEY="$HOME/.ssh/oci_key"
SSH_OPTS="-i ${SSH_KEY} -o StrictHostKeyChecking=no"

echo "=== 33.5A: Infrastructure Provisioning ==="
echo "Target: ${VM_USER}@${VM_HOST}"
echo ""

# Safety check: do not proceed if TradingAI already deployed
echo "--- Safety check: VM current state ---"
ssh ${SSH_OPTS} ${VM_USER}@${VM_HOST} "
  if [ -d /opt/tradingai/backend ] && [ -f /opt/tradingai/backend/api_server.py ]; then
    echo 'ERROR: TradingAI code already present on VM. Aborting infrastructure provisioning.'
    exit 1
  fi
  echo 'OK: No TradingAI code on VM — safe to provision infrastructure.'
" || { echo "Safety check failed. Aborting."; exit 1; }
echo ""

echo "--- Step 1: apt packages ---"
ssh ${SSH_OPTS} ${VM_USER}@${VM_HOST} "
  sudo apt-get update -qq
  sudo apt-get install -y -qq python3-pip nginx certbot sqlite3 rsync cron
"
echo "OK: apt packages installed"
echo ""

echo "--- Step 2: directory structure ---"
ssh ${SSH_OPTS} ${VM_USER}@${VM_HOST} "
  sudo mkdir -p /opt/tradingai/{backend,config,data,logs,scripts,database,backups}
  sudo mkdir -p /var/www/tradingai.in/html/{today,learn,tools,etfs,market,global,queries,sectors,mutual-funds,news,options,assets/{css,js},data}
  sudo chown -R ${VM_USER}:${VM_USER} /opt/tradingai /var/www/tradingai.in
"
echo "OK: directories created"
echo ""

echo "--- Step 3: Python dependencies ---"
# Copy requirements.txt to VM first
rsync -avz -e "ssh ${SSH_OPTS}" ops/requirements.txt ${VM_USER}@${VM_HOST}:/opt/tradingai/ops/requirements.txt
ssh ${SSH_OPTS} ${VM_USER}@${VM_HOST} "
  pip3 install -r /opt/tradingai/ops/requirements.txt
"
echo "OK: Python deps installed"
echo ""

echo "--- Step 4: /etc/tradingai/groq.env ---"
# PROMPT for key — never hardcode
read -p "Enter production GROQ_API_KEY: " GROQ_KEY
ssh ${SSH_OPTS} ${VM_USER}@${VM_HOST} "
  sudo mkdir -p /etc/tradingai
  echo 'export GROQ_API_KEY=${GROQ_KEY}' | sudo tee /etc/tradingai/groq.env > /dev/null
  sudo chmod 600 /etc/tradingai/groq.env
"
echo "OK: GROQ API key configured"
echo ""

echo "--- Step 5: nginx configuration ---"
rsync -avz -e "ssh ${SSH_OPTS}" ops/nginx-tradingai.conf ${VM_USER}@${VM_HOST}:/opt/tradingai/ops/nginx-tradingai.conf
ssh ${SSH_OPTS} ${VM_USER}@${VM_HOST} "
  sudo cp /opt/tradingai/ops/nginx-tradingai.conf /etc/nginx/sites-enabled/tradingai
  sudo nginx -t
  sudo systemctl enable nginx
  sudo systemctl restart nginx
"
echo "OK: nginx configured and running"
echo ""

echo "--- Step 6: systemd API service ---"
rsync -avz -e "ssh ${SSH_OPTS}" ops/systemd/tradingai-api.service ${VM_USER}@${VM_HOST}:/opt/tradingai/ops/systemd/tradingai-api.service
ssh ${SSH_OPTS} ${VM_USER}@${VM_HOST} "
  sudo cp /opt/tradingai/ops/systemd/tradingai-api.service /etc/systemd/system/tradingai-api.service
  sudo systemctl daemon-reload
  sudo systemctl enable tradingai-api
"
echo "OK: systemd unit loaded (NOT started — waiting for app deploy)"
echo ""

echo "--- Step 7: cron configuration ---"
rsync -avz -e "ssh ${SSH_OPTS}" ops/crontab.txt ${VM_USER}@${VM_HOST}:/opt/tradingai/ops/crontab.txt
ssh ${SSH_OPTS} ${VM_USER}@${VM_HOST} "
  crontab /opt/tradingai/ops/crontab.txt
"
echo "OK: cron configured"
echo ""

echo "--- Step 8: HTTPS (Let's Encrypt) ---"
echo "WARNING: Requires DNS tradingai.in and www.tradingai.in pointing to 129.159.224.81"
read -p "Have DNS been configured? (y/n): " DNS_READY
if [ "$DNS_READY" = "y" ]; then
  ssh ${SSH_OPTS} ${VM_USER}@${VM_HOST} "
    sudo certbot --nginx --domain tradingai.in --domain www.tradingai.in --agree-tos --redirect --noninteractive
  "
  echo "OK: HTTPS configured"
else
  echo "SKIP: HTTPS deferred — DNS not yet ready"
fi
echo ""

echo "--- Step 9: Backup mechanism ---"
ssh ${SSH_OPTS} ${VM_USER}@${VM_HOST} "
  mkdir -p /opt/tradingai-backup
  chown -R ${VM_USER}:${VM_USER} /opt/tradingai-backup
  mkdir -p /home/${VM_USER}/.ssh
  chmod 700 /home/${VM_USER}/.ssh
"
echo "OK: Backup directory ready"
echo "  ACTION NEEDED: Add github_backup SSH key as deploy key at GitHub"
echo "    ssh-keygen -t ed25519 -f /home/${VM_USER}/.ssh/github_backup -N ''"
echo "    Then register ~/.ssh/github_backup.pub at GitHub repo settings"
echo ""

echo "--- Step 10: Independent verification ---"
ssh ${SSH_OPTS} ${VM_USER}@${VM_HOST} "
  echo '=== nginx ==='
  nginx -t 2>&1
  systemctl status nginx --no-pager 2>&1 | head -5
  echo '=== systemd ==='
  systemctl is-enabled tradingai-api
  systemctl is-active tradingai-api || true
  echo '=== cron ==='
  crontab -l | grep -c tradingai 2>/dev/null || echo '0'
  echo '=== Python ==='
  python3 -c 'import flask; print(\"flask\", flask.__version__)'
  python3 -c 'import gunicorn; print(\"gunicorn\", gunicorn.__version__)'
  python3 -c 'import yfinance; print(\"yfinance ok\")'
  echo '=== Groq env ==='
  stat -c '%a' /etc/tradingai/groq.env
  echo '=== TradingAI NOT deployed (expected) ==='
  if [ -f /opt/tradingai/backend/api_server.py ]; then
    echo 'WARNING: TradingAI code already present!'
    exit 1
  else
    echo 'OK: No TradingAI code on VM'
  fi
  echo '=== Directories ==='
  ls -d /opt/tradingai/backend /opt/tradingai/config /opt/tradingai/logs
  ls -d /var/www/tradingai.in/html/today /var/www/tradingai.in/html/learn
"
echo ""

echo "=== 33.5A COMPLETE ==="
echo ""
echo "Next: 33.5B — Infrastructure Validation (load test each component)"
echo "Then: 33.6 — Controlled Application Deployment"
