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
  --exclude='frontend' \
  --exclude='backend' \
  -e "ssh -i $SSH_KEY -o StrictHostKeyChecking=no" \
  /Users/satya/remove_workspace/tradingai-lightweight/ \
  "$VM_USER@$VM_HOST:$PROJECT_DIR/"

echo "Files copied successfully"

ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no "$VM_USER@$VM_HOST" "cd $PROJECT_DIR && pip3 install yfinance 2>&1 | tail -3"

echo "=== Deployment complete ==="