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

ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no "$VM_USER@$VM_HOST" "cd $PROJECT_DIR && pip3 install yfinance 2>&1 | tail -3"

ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no "$VM_USER@$VM_HOST" "cd $PROJECT_DIR/backend && SKIP_LLM=1 /usr/bin/python3 generate_data.py && SKIP_LLM=1 /usr/bin/python3 generate_json.py && mkdir -p /var/www/tradingai.in/html/data && cp $PROJECT_DIR/data/*.json /var/www/tradingai.in/html/data/ 2>/dev/null; true"

ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no "$VM_USER@$VM_HOST" "cd $PROJECT_DIR/backend && /usr/bin/python3 db_schema.py && SKIP_LLM=1 /usr/bin/python3 data_fetcher_db.py && mkdir -p /var/www/tradingai.in/html/data && cp $PROJECT_DIR/data/*.json /var/www/tradingai.in/html/data/ 2>/dev/null; true"

ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no "$VM_USER@$VM_HOST" "cd $PROJECT_DIR/backend && nohup /usr/bin/python3 api_server.py > /opt/tradingai/logs/api_server.log 2>&1 &"

echo "=== Deployment complete ==="