#!/usr/bin/env bash
set -euo pipefail

VM_USER="ubuntu"
VM_HOST="129.159.224.81"
SSH_KEY="$HOME/.ssh/oci_key"
PROJECT_DIR="/opt/tradingai"

echo "=== Deploying TradingAI Lightweight ==="

ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no "$VM_USER@$VM_HOST" "mkdir -p $PROJECT_DIR"

rsync -avz --delete \
  --exclude='node_modules' \
  --exclude='.next' \
  --exclude='__pycache__' \
  --exclude='.pytest_cache' \
  --exclude='.git' \
  --exclude='logs' \
  --exclude='deploy-vm.sh' \
  --exclude='deploy-to-vm.sh' \
  --exclude='docker-compose.yml' \
  --exclude='docker-compose.vm.yml' \
  --exclude='docker' \
  --exclude='database' \
  --exclude='data' \
  --exclude='frontend' \
  -e "ssh -i $SSH_KEY -o StrictHostKeyChecking=no" \
  /Users/satya/remove_workspace/tradingai-lightweight/ \
  "$VM_USER@$VM_HOST:$PROJECT_DIR/"

echo "Files copied successfully"

ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no "$VM_USER@$VM_HOST" "cd $PROJECT_DIR && pip3 install yfinance flask flask-cors 2>&1 | tail -3"

# Sync served web root (nginx serves /var/www, repo lives in /opt/tradingai)
ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no "$VM_USER@$VM_HOST" "cp $PROJECT_DIR/index.html $PROJECT_DIR/market.html $PROJECT_DIR/scanner.html $PROJECT_DIR/strategies.html $PROJECT_DIR/history.html /var/www/tradingai.in/html/ && cp -r $PROJECT_DIR/indices/* /var/www/tradingai.in/html/indices/ 2>/dev/null; cp -r $PROJECT_DIR/stocks/* /var/www/tradingai.in/html/stocks/ 2>/dev/null; cp -r $PROJECT_DIR/static/* /var/www/tradingai.in/html/static/ 2>/dev/null; cp -r $PROJECT_DIR/assets/* /var/www/tradingai.in/html/assets/ 2>/dev/null; true"

ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no "$VM_USER@$VM_HOST" "pkill -f '[p]ython3 api_server' 2>/dev/null; sleep 1; cd $PROJECT_DIR/backend && /usr/bin/python3 db_schema.py && (SKIP_LLM=1 /usr/bin/python3 data_fetcher_db.py >> /opt/tradingai/logs/data.log 2>&1 &) ; cd $PROJECT_DIR/backend && setsid /usr/bin/python3 api_server.py >>/opt/tradingai/logs/api_server.log 2>&1 0</dev/null & sleep 5; curl -s http://127.0.0.1:8000/api/health || true"

# Every-minute market-hours fetch (tiered inside fetcher: indices+large every run, mid 5m, small+fundamentals 15m)
ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no "$VM_USER@$VM_HOST" "(crontab -l 2>/dev/null | grep -v 'data_fetcher_db.py\|generate_data.py\|generate_json.py\|api_server.py\|pnl_tracker.py'; echo '# TradingAI Market Hours Cron (9:30 AM - 3:30 PM IST, Mon-Fri)'; echo '* 9-15 * * 1-5 cd /opt/tradingai/backend && SKIP_LLM=1 /usr/bin/python3 data_fetcher_db.py >> /opt/tradingai/logs/data.log 2>&1'; echo '*/5 9-15 * * 1-5 cd /opt/tradingai/backend && /usr/bin/python3 monitor.py >> /opt/tradingai/logs/monitor.log 2>&1'; echo '0 */2 9-15 * * 1-5 cd /opt/tradingai/backend && /usr/bin/python3 alert.py >> /opt/tradingai/logs/alerts.log 2>&1'; echo '30 9 * * 1-5 cd /opt/tradingai/backend && /usr/bin/python3 pnl_tracker.py lock >> /opt/tradingai/logs/pnl.log 2>&1'; echo '20 15 * * 1-5 cd /opt/tradingai/backend && /usr/bin/python3 pnl_tracker.py close >> /opt/tradingai/logs/pnl.log 2>&1'; echo '0 2 1 * * cd /opt/tradingai/backend && /usr/bin/python3 pnl_tracker.py archive 365 >> /opt/tradingai/logs/pnl.log 2>&1'; echo '*/5 * * * * pgrep -f [p]ython3\\ api_server > /dev/null || (cd /opt/tradingai/backend && setsid /usr/bin/python3 api_server.py >>/opt/tradingai/logs/api_server.log 2>&1 0</dev/null &)'; echo '@reboot cd /opt/tradingai/backend && setsid /usr/bin/python3 api_server.py >>/opt/tradingai/logs/api_server.log 2>&1 0</dev/null &') | crontab - && crontab -l"

ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no "$VM_USER@$VM_HOST" "sudo systemctl reload nginx"

echo "=== Deployment complete ==="