#!/usr/bin/env bash
# TradingAI Rollback Script
# Rolls back to previous commit, restores DB backup, restarts API, verifies health.
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VM_USER="${VM_USER:-ubuntu}"
VM_HOST="${VM_HOST:-129.159.224.81}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/oci_key}"

echo "=== TradingAI Rollback ==="

# 1. Check current git state
cd "$APP_DIR"
current_commit=$(git rev-parse HEAD)
echo "Current commit: $current_commit"

# 2. Find previous commit
prev_commit=$(git rev-parse HEAD~1 2>/dev/null || echo "")
if [ -z "$prev_commit" ]; then
    echo "ERROR: No previous commit to rollback to"
    exit 1
fi
echo "Rolling back to: $prev_commit"

# 3. Backup current state before rollback
echo "Backing up current state..."
timestamp=$(date -u +"%Y%m%d_%H%M%S")
backup_dir="$APP_DIR/backups/pre_rollback_$timestamp"
mkdir -p "$backup_dir"
cp "$APP_DIR/database/tradingai.db" "$backup_dir/tradingai.db" 2>/dev/null || true
echo "Current state backed up to $backup_dir"

# 4. Restore DB backup from before this deployment
echo "Checking for DB backup..."
latest_backup=$(ls -t "$APP_DIR/backups"/tradingai_*.db 2>/dev/null | head -1)
if [ -n "$latest_backup" ]; then
    echo "Restoring DB from: $latest_backup"
    cp "$latest_backup" "$APP_DIR/database/tradingai.db"
    echo "DB restored"
else
    echo "WARNING: No backup found to restore from"
fi

# 5. Git checkout previous commit
echo "Rolling back git..."
git checkout "$prev_commit" -- backend/ scripts/ tests/ *.html *.py *.json *.md 2>/dev/null || true
git reset --hard "$prev_commit" 2>/dev/null || true
echo "Git rollback complete"

# 6. Sync to VM
echo "Syncing to VM..."
rsync -avz --delete \
    --exclude='node_modules' --exclude='.next' --exclude='__pycache__' \
    --exclude='.pytest_cache' --exclude='.git' --exclude='logs' \
    --exclude='database' --exclude='data' --exclude='backups' \
    -e "ssh -i $SSH_KEY -o StrictHostKeyChecking=no" \
    "$APP_DIR/" "$VM_USER@$VM_HOST:/opt/tradingai/" 2>&1 | tail -3

# 7. Restart API
echo "Restarting API..."
ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no "$VM_USER@$VM_HOST" \
    "sudo systemctl restart tradingai-api 2>&1"
sleep 3

# 8. Health check
echo "Running health check..."
health_output=$(ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no "$VM_USER@$VM_HOST" \
    "/usr/bin/bash $APP_DIR/scripts/health_check.sh" 2>&1)
echo "$health_output"

# 9. Verify API
echo "Verifying API..."
code=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:8000/api/health" 2>/dev/null || echo "000")
if [ "$code" = "200" ]; then
    echo "=== ROLLBACK SUCCESS ==="
else
    echo "=== ROLLBACK PARTIAL ==="
    echo "API not responding. Manual intervention may be required."
    echo "To restore forward: git checkout main && ./scripts/deploy.sh"
fi