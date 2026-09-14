#!/usr/bin/env bash
set -euo pipefail

VM_USER="ubuntu"
VM_HOST="129.159.224.81"
SSH_KEY="$HOME/.ssh/oci_key"
PROJECT_DIR="/opt/tradingai"

echo "=== Deploying TradingAI Lightweight ==="
START_TIME=$(date +%s)

deploy_log() {
    local stage="$1"
    local status="$2"  
    local message="$3"
    local duration_ms="${4:-0}"
    local timestamp
    timestamp=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
    echo "{\"timestamp\":\"$timestamp\",\"stage\":\"$stage\",\"status\":\"$status\",\"message\":\"$message\",\"duration_ms\":$duration_ms}" | tee -a /tmp/deploy.log
}

ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no "$VM_USER@$VM_HOST" "mkdir -p $PROJECT_DIR"

deploy_log "DEPLOY" "START" "File copy" $(($(date +%s) - START_TIME))
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
deploy_log "DEPLOY" "COMPLETE" "Files copied" $(($(date +%s) - START_TIME))

# LLM env file: create once if missing (never overwrite an existing key).
# Cron sources it so GROQ_API_KEY stays out of this script and the crontab.
ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no "$VM_USER@$VM_HOST" "if [ ! -f /etc/tradingai/groq.env ]; then sudo mkdir -p /etc/tradingai && sudo chown $VM_USER:$VM_USER /etc/tradingai && echo 'export GROQ_API_KEY=PLACEHOLDER_REPLACE_ON_VM' > /etc/tradingai/groq.env && chmod 600 /etc/tradingai/groq.env; fi"

ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no "$VM_USER@$VM_HOST" "cd $PROJECT_DIR && pip3 install yfinance flask flask-cors flask-limiter && sudo pip3 install gunicorn==23.0.0 2>&1 | tail -3"

# Sync served web root (nginx serves /var/www, repo lives in /opt/tradingai).
# NOTE: pages reference assets/css/main.css + assets/css/chat.css, whose source is static/
ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no "$VM_USER@$VM_HOST" "cp $PROJECT_DIR/*.html /var/www/tradingai.in/html/ 2>/dev/null; cp $PROJECT_DIR/robots.txt $PROJECT_DIR/sitemap.xml $PROJECT_DIR/indexnow/*.txt /var/www/tradingai.in/html/ 2>/dev/null && cp $PROJECT_DIR/favicon.svg $PROJECT_DIR/favicon.ico $PROJECT_DIR/apple-touch-icon.svg /var/www/tradingai.in/html/ && cp -r $PROJECT_DIR/indices/* /var/www/tradingai.in/html/indices/ 2>/dev/null; cp -r $PROJECT_DIR/stocks/* /var/www/tradingai.in/html/stocks/ 2>/dev/null; mkdir -p /var/www/tradingai.in/html/today /var/www/tradingai.in/html/learn /var/www/tradingai.in/html/tools /var/www/tradingai.in/html/etfs /var/www/tradingai.in/html/market /var/www/tradingai.in/html/global /var/www/tradingai.in/html/queries /var/www/tradingai.in/html/sectors /var/www/tradingai.in/html/static /var/www/tradingai.in/html/mutual-funds /var/www/tradingai.in/html/news /var/www/tradingai.in/html/options /var/www/tradingai.in/html/assets/css /var/www/tradingai.in/html/assets/js; cp $PROJECT_DIR/today/index.html /var/www/tradingai.in/html/today/ 2>/dev/null; cp -r $PROJECT_DIR/learn/* /var/www/tradingai.in/html/learn/ 2>/dev/null; cp -r $PROJECT_DIR/tools/* /var/www/tradingai.in/html/tools/ 2>/dev/null; cp -r $PROJECT_DIR/etfs/* /var/www/tradingai.in/html/etfs/ 2>/dev/null; cp -r $PROJECT_DIR/global/* /var/www/tradingai.in/html/global/ 2>/dev/null; cp -r $PROJECT_DIR/queries/* /var/www/tradingai.in/html/queries/ 2>/dev/null; cp -r $PROJECT_DIR/sectors/* /var/www/tradingai.in/html/sectors/ 2>/dev/null; cp -r $PROJECT_DIR/mutual-funds/* /var/www/tradingai.in/html/mutual-funds/ 2>/dev/null; cp -r $PROJECT_DIR/news/* /var/www/tradingai.in/html/news/ 2>/dev/null; cp -r $PROJECT_DIR/options/* /var/www/tradingai.in/html/options/ 2>/dev/null; cp -r $PROJECT_DIR/static/* /var/www/tradingai.in/html/static/ 2>/dev/null; cp $PROJECT_DIR/static/css/*.css /var/www/tradingai.in/html/assets/css/ 2>/dev/null; cp $PROJECT_DIR/static/js/*.js /var/www/tradingai.in/html/assets/js/ 2>/dev/null; true"

# API runs as a systemd service (self-healing: Restart=always). Deploy refreshes the unit and restarts.
deploy_log "VERIFY" "START" "Health check"
ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no "$VM_USER@$VM_HOST" "pkill -f '[p]ython3 api_server' 2>/dev/null; pkill -f '[g]unicorn' 2>/dev/null; sleep 1; mkdir -p /opt/tradingai/logs && cd $PROJECT_DIR/backend && /usr/bin/python3 db_schema.py && (SKIP_LLM=1 /usr/bin/python3 data_fetcher_db.py >> /opt/tradingai/logs/data.log 2>&1 &); (sleep 10 && CNT=\$(/usr/bin/python3 -c 'import sqlite3; print(sqlite3.connect(\"/opt/tradingai/database/tradingai.db\").execute(\"SELECT COUNT(*) FROM price_1d\").fetchone()[0])' 2>/dev/null || echo 0); if [ \"\$CNT\" -lt 500 ]; then /usr/bin/python3 backfill_indices_10y.py --period 10y >> /opt/tradingai/logs/data.log 2>&1 & fi &); (sleep 20 && CNT=\$(/usr/bin/python3 -c 'import sqlite3; print(sqlite3.connect(\"/opt/tradingai/database/tradingai.db\").execute(\"SELECT COUNT(*) FROM market_outlooks\").fetchone()[0])' 2>/dev/null || echo 0); if [ \"\$CNT\" -lt 500 ]; then /usr/bin/python3 backfill_outlooks.py --days 3650 --overwrite >> /opt/tradingai/logs/outlook.log 2>&1 & fi &); sudo cp $PROJECT_DIR/ops/systemd/tradingai-api.service /etc/systemd/system/tradingai-api.service && sudo systemctl daemon-reload && sudo systemctl enable tradingai-api && sudo systemctl restart tradingai-api && DEPLOY_HEALTH=""; for _attempt in \$(seq 1 12); do sleep 5; DEPLOY_HEALTH=\$(curl -sf --max-time 10 http://127.0.0.1:8000/api/health 2>/dev/null || echo ""); if echo "\$DEPLOY_HEALTH" | grep -q '"status": "ok"'; then break; fi; done; if echo "\$DEPLOY_HEALTH" | grep -q '"status": "ok"'; then echo "DEPLOY SUCCESS: API healthy"; deploy_log "VERIFY" "PASS" "API healthy"; else echo "DEPLOY FAILED: API health check failed"; echo "\$DEPLOY_HEALTH"; exit 1; fi"

# Every-minute market-hours fetch (tiered inside fetcher: indices+large every run, mid 5m, small+fundamentals 15m)
ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no "$VM_USER@$VM_HOST" "(crontab -l 2>/dev/null | grep -v 'data_fetcher_db.py\|generate_data.py\|generate_json.py\|api_server.py\|pnl_tracker.py\|vm-backup.sh\|self-heal.sh\|aggregate.py\|nse_live_chain.py\|etf_fetcher.py\|mf_fetcher.py\|outlook.py\|sitemap_gen.py\|bhavcopy.py\|backfill_yearly.py\|fo_fetcher.py\|daily_page.py\|monitor.py\|alert.py'; echo '# TradingAI Market Hours Cron (9:30 AM - 3:30 PM IST, Mon-Fri)'; echo '* 9-15 * * 1-5 cd /opt/tradingai/backend && SKIP_LLM=1 /usr/bin/python3 data_fetcher_db.py >> /opt/tradingai/logs/data.log 2>&1'; echo '*/5 9-15 * * 1-5 cd /opt/tradingai/backend && /usr/bin/python3 monitor.py >> /opt/tradingai/logs/monitor.log 2>&1'; echo '0 */2 9-15 * * 1-5 cd /opt/tradingai/backend && /usr/bin/python3 alert.py >> /opt/tradingai/logs/alerts.log 2>&1'; echo '*/5 9-15 * * 1-5 cd /opt/tradingai/backend && /usr/bin/python3 pnl_tracker.py evaluate >> /opt/tradingai/logs/pnl.log 2>&1'; echo '20 15 * * 1-5 cd /opt/tradingai/backend && /usr/bin/python3 pnl_tracker.py close >> /opt/tradingai/logs/pnl.log 2>&1'; echo '35 9 * * 1-5 cd /opt/tradingai/backend && /usr/bin/python3 daily_page.py morning --webroot /var/www/tradingai.in/html >> /opt/tradingai/logs/daily.log 2>&1'; echo '35 15 * * 1-5 cd /opt/tradingai/backend && /usr/bin/python3 daily_page.py close --webroot /var/www/tradingai.in/html && /usr/bin/python3 sitemap_gen.py --webroot /var/www/tradingai.in/html >> /opt/tradingai/logs/daily.log 2>&1'; echo '30 18 * * * /opt/tradingai/ops/vm-backup.sh >> /opt/tradingai/logs/backup.log 2>&1'; echo '0 2 1 * * cd /opt/tradingai/backend && /usr/bin/python3 pnl_tracker.py archive 365 >> /opt/tradingai/logs/pnl.log 2>&1'; echo '35 18 * * 1-5 cd /opt/tradingai/backend && /usr/bin/python3 bhavcopy.py daily >> /opt/tradingai/logs/bhav.log 2>&1'; echo '30 8 * * 1 cd /opt/tradingai/backend && /usr/bin/python3 bhavcopy.py holidays >> /opt/tradingai/logs/bhav.log 2>&1'; echo '30 6 * * 0 cd /opt/tradingai/backend && /usr/bin/python3 backfill_yearly.py >> /opt/tradingai/logs/data.log 2>&1'; echo '40 18 * * 1-5 cd /opt/tradingai/backend && /usr/bin/python3 fo_fetcher.py daily >> /opt/tradingai/logs/fo.log 2>&1'; echo '30 9 * * 1-5 cd /opt/tradingai/backend && . /etc/tradingai/groq.env && { /usr/bin/python3 outlook.py --symbol NIFTY --webroot /var/www/tradingai.in/html && /usr/bin/python3 outlook.py --symbol BANKNIFTY --webroot /var/www/tradingai.in/html && /usr/bin/python3 outlook.py --symbol FINNIFTY --webroot /var/www/tradingai.in/html && /usr/bin/python3 outlook.py --symbol SENSEX --webroot /var/www/tradingai.in/html; } >> /opt/tradingai/logs/outlook.log 2>&1'; echo '0 19 * * 1-5 cd /opt/tradingai/backend && . /etc/tradingai/groq.env && { /usr/bin/python3 outlook.py --symbol NIFTY --webroot /var/www/tradingai.in/html && /usr/bin/python3 outlook.py --symbol BANKNIFTY --webroot /var/www/tradingai.in/html && /usr/bin/python3 outlook.py --symbol FINNIFTY --webroot /var/www/tradingai.in/html && /usr/bin/python3 outlook.py --symbol SENSEX --webroot /var/www/tradingai.in/html && /usr/bin/python3 sitemap_gen.py --webroot /var/www/tradingai.in/html; } >> /opt/tradingai/logs/outlook.log 2>&1'; echo '35 19 * * * cd /opt/tradingai/backend && /usr/bin/python3 mf_fetcher.py >> /opt/tradingai/logs/mf.log 2>&1'; echo '30 7 * * 0 cd /opt/tradingai/backend && /usr/bin/python3 mf_fetcher.py --returns >> /opt/tradingai/logs/mf.log 2>&1'; echo '*/2 * * * * /opt/tradingai/ops/self-heal.sh >> /opt/tradingai/logs/self-heal.log 2>&1' echo '*/15 9-15 * * 1-5 cd /opt/tradingai/backend && /usr/bin/python3 aggregate.py sweep >> /opt/tradingai/logs/aggregate.log 2>&1'; echo '*/15 9-15 * * 1-5 cd /opt/tradingai/backend && /usr/bin/python3 nse_live_chain.py poll >> /opt/tradingai/logs/livechain.log 2>&1'; echo '0 7 * * 0 cd /opt/tradingai/backend && /usr/bin/python3 etf_fetcher.py >> /opt/tradingai/logs/etf.log 2>&1') | crontab - && crontab -l"

# nginx guard: every deploy re-asserts the canonical site config, which contains
# the /indices/market.html -> /market.html 301. A rebuild/provision that starts
# from a stale copy silently drops the redirect (leaked URL 200s as SPA
# text/html -> blank page), so we re-sync + nginx -t + reload on EVERY deploy.
# Durable: idempotent, and source-of-truth is ops/nginx-tradingai.conf (git).
scp -i "$SSH_KEY" -o StrictHostKeyChecking=no \
  "/Users/satya/remove_workspace/tradingai-lightweight/ops/nginx-tradingai.conf" \
  "$VM_USER@$VM_HOST:/tmp/tradingai-nginx.conf"
ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no "$VM_USER@$VM_HOST" \
  "sudo cp /tmp/tradingai-nginx.conf /etc/nginx/sites-enabled/tradingai && sudo rm -f /tmp/tradingai-nginx.conf && sudo nginx -t 2>/dev/null && sudo systemctl reload nginx && echo NGINX-GUARD-REASSERTED"

deploy_log "DEPLOY" "COMPLETE" "All stages done" $(($(date +%s) - START_TIME))