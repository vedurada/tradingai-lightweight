#!/usr/bin/env bash
# TradingAI full setup for a FRESH Ubuntu 22.04 VM (disaster recovery / new machine).
# Run from your Mac:  NEW_VM_IP=129.159.224.82 bash ops/setup-new-vm.sh
#   (defaults to the current production IP if NEW_VM_IP is unset)
# What it does:
#   1. apt: python3-pip, nginx, certbot, sqlite3
#   2. pip: ops/requirements.txt
#   3. dirs + full repo sync to /opt/tradingai
#   4. restores database/tradingai.db from the vm-backup branch (no data loss)
#   5. installs nginx site from ops/nginx-tradingai.conf (HTTP immediately, HTTPS after DNS+certbot)
#   6. installs cron from ops/crontab.txt
#   7. initial data fetch + API start + verification
# See ops/RESTORE.md for the complete disaster-recovery runbook.
set -euo pipefail

VM_USER="${VM_USER:-ubuntu}"
VM_HOST="${NEW_VM_IP:-129.159.224.81}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/oci_key}"
PROJECT_DIR="/opt/tradingai"
WEB_ROOT="/var/www/tradingai.in/html"
REPO_URL="https://github.com/vedurada/tradingai-lightweight.git"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

ssh_vm() { ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no "$VM_USER@$VM_HOST" "$@"; }

echo "=== 1/8 apt packages ==="
ssh_vm "sudo apt-get update -qq && sudo apt-get install -y -qq python3-pip nginx certbot sqlite3 rsync"

echo "=== 2/8 python deps ==="
ssh_vm "pip3 install -q -r <(echo) 2>/dev/null; true"
scp -i "$SSH_KEY" -o StrictHostKeyChecking=no "$REPO_ROOT/ops/requirements.txt" "$VM_USER@$VM_HOST:/tmp/tradingai-requirements.txt"
ssh_vm "pip3 install -q -r /tmp/tradingai-requirements.txt && rm /tmp/tradingai-requirements.txt"

echo "=== 3/8 directories + repo sync ==="
ssh_vm "sudo mkdir -p $PROJECT_DIR $WEB_ROOT/html/data $WEB_ROOT/html/indices $WEB_ROOT/html/stocks $WEB_ROOT/html/static $WEB_ROOT/html/assets/css $WEB_ROOT/html/assets/js $PROJECT_DIR/logs $PROJECT_DIR/database && sudo chown -R ubuntu:ubuntu /opt/tradingai /var/www/tradingai.in"
rsync -avz --delete \
  --exclude='node_modules' --exclude='__pycache__' --exclude='.pytest_cache' \
  --exclude='.git' --exclude='logs' --exclude='database' --exclude='data' \
  --exclude='deploy-vm.sh' --exclude='docker-compose.yml' --exclude='docker' \
  -e "ssh -i $SSH_KEY -o StrictHostKeyChecking=no" \
  "$REPO_ROOT/" "$VM_USER@$VM_HOST:$PROJECT_DIR/"

echo "=== 4/8 restore database from vm-backup branch (no data loss) ==="
ssh_vm "if [ ! -f $PROJECT_DIR/database/tradingai.db ]; then rm -rf /tmp/tradingai-restore && git clone -q --branch vm-backup --depth 1 https://github.com/vedurada/tradingai-lightweight.git /tmp/tradingai-restore 2>/dev/null && cp /tmp/tradingai-restore/database/tradingai.db $PROJECT_DIR/database/tradingai.db && echo RESTORED-DATABASE-OK || echo 'NO-BACKUP-BRANCH-YET (fresh database will be created by fetcher)'; else echo 'database already present, kept as-is'; fi"

echo "=== 5/8 web root content ==="
ssh_vm "cp $PROJECT_DIR/index.html $PROJECT_DIR/market.html $PROJECT_DIR/scanner.html $PROJECT_DIR/strategies.html $PROJECT_DIR/history.html $PROJECT_DIR/strategy-builder.html $PROJECT_DIR/strategies-guide.html $WEB_ROOT/html/ 2>/dev/null; cp -r $PROJECT_DIR/indices/* $WEB_ROOT/html/indices/ 2>/dev/null; cp -r $PROJECT_DIR/stocks/* $WEB_ROOT/html/stocks/ 2>/dev/null; cp $PROJECT_DIR/static/css/main.css $WEB_ROOT/html/assets/css/main.css; cp $PROJECT_DIR/static/js/*.js $WEB_ROOT/html/assets/js/ 2>/dev/null; mkdir -p $WEB_ROOT/html/data; echo WEBROOT-OK"

echo "=== 6/8 nginx site ==="
scp -i "$SSH_KEY" -o StrictHostKeyChecking=no "$REPO_ROOT/ops/nginx-tradingai.conf" "$VM_USER@$VM_HOST:/tmp/tradingai-nginx.conf"
ssh_vm "sudo cp /tmp/tradingai-nginx.conf /etc/nginx/sites-enabled/tradingai && rm /tmp/tradingai-nginx.conf && (sudo nginx -t 2>/dev/null && sudo systemctl reload nginx && echo NGINX-OK || echo 'NGINX-NEEDS-CERT (run certbot step below, then: sudo systemctl reload nginx)')"

echo "=== 7/8 HTTPS certificate (needs DNS pointing here first) ==="
ssh_vm "sudo certbot certonly --webroot -w $WEB_ROOT/html -d tradingai.in -d www.tradingai.in --non-interactive --agree-tos --register-unsafely-without-email 2>&1 | tail -3; sudo systemctl reload nginx 2>/dev/null || true"

echo "=== 8/8 cron + initial fetch + API ==="
scp -i "$SSH_KEY" -o StrictHostKeyChecking=no "$REPO_ROOT/ops/crontab.txt" "$VM_USER@$VM_HOST:/tmp/tradingai-crontab.txt"
ssh_vm "grep -v '^#' /tmp/tradingai-crontab.txt | grep -v '^\$' | crontab - && rm /tmp/tradingai-crontab.txt && crontab -l | wc -l"
ssh_vm "cd $PROJECT_DIR/backend && /usr/bin/python3 db_schema.py && (SKIP_LLM=1 /usr/bin/python3 data_fetcher_db.py >> /opt/tradingai/logs/data.log 2>&1 &)"
ssh_vm "cd $PROJECT_DIR/backend && setsid /usr/bin/python3 api_server.py >>/opt/tradingai/logs/api_server.log 2>&1 0</dev/null & sleep 4; curl -s http://127.0.0.1:8000/api/health || true"

echo ""
echo "=== VERIFY (do these now) ==="
echo "1. https://tradingai.in/ loads with a trusted cert"
echo "2. https://tradingai.in/api/health returns ok"
echo "3. crontab -l on VM shows all jobs"
echo "4. Generate a NEW ssh deploy key for daily backups:"
echo "   ssh ubuntu@$VM_HOST \"ssh-keygen -t ed25519 -f ~/.ssh/github_backup -N '' && cat ~/.ssh/github_backup.pub\""
echo "   then add it as a WRITE deploy key at github.com/vedurada/tradingai-lightweight/settings/keys"
echo "=== DONE ==="
