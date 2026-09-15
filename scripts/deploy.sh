#!/usr/bin/env bash
# TradingAI Deployment Script
# Phase 1: Production deployment with safety gates.
# 
# Flow:
#   Git state → tests → config validation → backup → migration →
#   app validation → nginx -t → restart → API smoke → frontend smoke → health
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VM_USER="${VM_USER:-ubuntu}"
VM_HOST="${VM_HOST:-129.159.224.81}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/oci_key}"

STAGE_START=$(date +%s)
deploy_log() {
    local stage="$1"
    local status="$2"
    local message="$3"
    local duration_ms=$(( $(date +%s) - STAGE_START ))
    local ts
    ts=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
    echo "{\"timestamp\":\"$ts\",\"stage\":\"$stage\",\"status\":\"$status\",\"message\":\"$message\",\"duration_ms\":$duration_ms}" | tee -a /tmp/deploy.log
}

echo "=== TradingAI Phase 1 Deployment ==="
deploy_log "DEPLOY" "START" "Beginning deployment"

# 1. Git state check
deploy_log "GIT" "CHECK" "Verifying git state"
cd "$APP_DIR"
if [ -n "$(git status --porcelain)" ]; then
    deploy_log "GIT" "FAIL" "Uncommitted changes: $(git status --short)"
    exit 1
fi
current_branch=$(git branch --show-current)
if [ "$current_branch" != "tradingai.in_live_VM" ]; then
    deploy_log "GIT" "WARN" "Branch is $current_branch, expected tradingai.in_live_VM"
fi
deploy_log "GIT" "PASS" "Clean working tree on $current_branch"

# 2. Run tests
deploy_log "TESTS" "START" "Running full test suite"
if python3 -m pytest tests/ -q --tb=short 2>&1 | tail -5; then
    deploy_log "TESTS" "PASS" "All tests passing"
else
    deploy_log "TESTS" "FAIL" "Tests failed"
    exit 1
fi

# 3. Configuration validation
deploy_log "CONFIG" "CHECK" "Validating configuration"
if [ -f /etc/tradingai/groq.env ]; then
    perms=$(stat -c %a /etc/tradingai/groq.env)
    if [ "$perms" != "600" ]; then
        deploy_log "CONFIG" "FAIL" "GROQ key permissions are $perms, expected 600"
        exit 1
    fi
    deploy_log "CONFIG" "PASS" "Secrets properly secured"
else
    deploy_log "CONFIG" "FAIL" "/etc/tradingai/groq.env not found"
    exit 1
fi

# 4. Backup
deploy_log "BACKUP" "START" "Creating database backup"
ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no "$VM_USER@$VM_HOST" \
    "/usr/bin/bash $APP_DIR/scripts/backup.sh" 2>&1 | tail -3
deploy_log "BACKUP" "PASS" "Backup created"

# 5. Database migration check
deploy_log "MIGRATION" "CHECK" "Checking migrations"
ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no "$VM_USER@$VM_HOST" \
    "cd /opt/tradingai && python3 backend/migration.py status 2>&1 | tail -5"
deploy_log "MIGRATION" "PASS" "Migration status checked"

# 6. Sync files to VM
deploy_log "SYNC" "START" "Syncing files to VM"
rsync -avz --delete \
    --exclude='node_modules' --exclude='.next' --exclude='__pycache__' \
    --exclude='.pytest_cache' --exclude='.git' --exclude='logs' \
    --exclude='database' --exclude='data' --exclude='backups' \
    --exclude='frontend' \
    -e "ssh -i $SSH_KEY -o StrictHostKeyChecking=no" \
    "$APP_DIR/" "$VM_USER@$VM_HOST:/opt/tradingai/" 2>&1 | tail -3
deploy_log "SYNC" "PASS" "Files synced"

# 7. Restart API
deploy_log "RESTART" "START" "Restarting API"
ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no "$VM_USER@$VM_HOST" \
    "sudo systemctl restart tradingai-api 2>&1"
sleep 3
deploy_log "RESTART" "PASS" "API restarted"

# 8. nginx -t
deploy_log "NGINX" "START" "Testing nginx config"
ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no "$VM_USER@$VM_HOST" \
    "sudo nginx -t 2>&1" | tail -3
deploy_log "NGINX" "PASS" "nginx config valid"

# 9. API smoke test
deploy_log "SMOKE" "START" "API smoke test"
for ep in /api/health /api/ready /api/price/NIFTY /api/vix /api/NIFTY /api/market; do
    code=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:8000$ep" 2>/dev/null || echo "000")
    if [ "$code" != "200" ]; then
        deploy_log "SMOKE" "FAIL" "$ep returned $code"
        exit 1
    fi
done
deploy_log "SMOKE" "PASS" "All API smoke tests passed"

# 10. Frontend smoke test
deploy_log "FRONTEND" "START" "Frontend smoke test"
frontend_code=$(curl -s -o /dev/null -w "%{http_code}" "http://tradingai.in/" 2>/dev/null || echo "000")
if [ "$frontend_code" != "200" ]; then
    frontend_code=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:80/" 2>/dev/null || echo "000")
fi
if [ "$frontend_code" != "200" ]; then
    deploy_log "FRONTEND" "FAIL" "Frontend returned $frontend_code"
    exit 1
fi
deploy_log "FRONTEND" "PASS" "Frontend responding"

# 11. Final health check
deploy_log "HEALTH" "START" "Final health check"
ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no "$VM_USER@$VM_HOST" \
    "/usr/bin/bash $APP_DIR/scripts/health_check.sh" 2>&1 | tail -3
deploy_log "HEALTH" "PASS" "Health check passed"

duration=$(( $(date +%s) - STAGE_START ))
deploy_log "DEPLOY" "COMPLETE" "Deployment successful ($duration seconds)"
echo "=== DEPLOYMENT SUCCESS ==="