#!/usr/bin/env bash
# TradingAI self-healing watchdog — covers ALL known failure modes.
# Runs every 2 min via cron (see ops/crontab.txt). Logs to logs/self-heal.log.
# Each check is best-effort and never aborts the others.
set -u
LOG="/opt/tradingai/logs/self-heal.log"
DB="/opt/tradingai/database/tradingai.db"
API="http://127.0.0.1:8000/api/health"
NOW=$(date '+%F %T %Z')
log() { echo "[$NOW] $*" | tee -a "$LOG" > /dev/null; echo "[$NOW] $*"; }

# 1. Disk — alert and rotate logs if >85%
DISK_PCT=$(df / | awk 'NR==2{print $5}' | tr -d '%')
if [ "${DISK_PCT:-0}" -gt 90 ]; then
  log "DISK CRITICAL ${DISK_PCT}% — truncating old logs"
  sudo journalctl --vacuum-size=100M 2>/dev/null || true
  find /opt/tradingai/logs -name "*.log" -size +50M -exec truncate -s 20M {} \; 2>/dev/null || true
elif [ "${DISK_PCT:-0}" -gt 85 ]; then
  log "DISK WARNING ${DISK_PCT}%"
fi

# 2. Nginx — must be active and serving
if ! systemctl is-active --quiet nginx 2>/dev/null; then
  log "NGINX DOWN — restarting"
  sudo systemctl restart nginx 2>&1 | head -3 | while read l; do log "nginx: $l"; done
  sudo nginx -t 2>&1 | head -2 | while read l; do log "nginx -t: $l"; done
fi

# 3. API — health check (covers hang, not just dead process)
if ! curl -sf --max-time 10 "$API" > /dev/null 2>&1; then
  log "API UNHEALTHY — resetting and restarting tradingai-api"
  sudo systemctl reset-failed tradingai-api 2>/dev/null || true
  sudo systemctl restart tradingai-api 2>&1 | head -3 | while read l; do log "api restart: $l"; done
  sleep 5
  if curl -sf --max-time 10 "$API" > /dev/null 2>&1; then
    log "API recovered after restart"
  else
    log "API STILL DOWN after restart — will retry next cycle"
    # Last resort: kill any stale python and let systemd recreate
    pkill -f '[p]ython3 api_server' 2>/dev/null || true
    sleep 2
    sudo systemctl reset-failed tradingai-api 2>/dev/null || true
    sudo systemctl start tradingai-api 2>&1 | head -2 | while read l; do log "api start: $l"; done
  fi
fi

# 4. DB — file exists, readable, integrity ok (sample, not full scan every 2 min)
if [ ! -f "$DB" ]; then
  log "DB MISSING at $DB"
else
  if ! python3 -c "import sqlite3; c=sqlite3.connect('$DB'); c.execute('SELECT 1 FROM symbols LIMIT 1').fetchone()" 2>/dev/null; then
    log "DB UNREADABLE — attempting to restore from latest backup branch"
    # Try to restore the snapshot that vm-backup.sh maintains
    if [ -f /opt/tradingai-backup/database/tradingai.db ]; then
      cp /opt/tradingai-backup/database/tradingai.db "$DB.tmp" 2>/dev/null && mv "$DB.tmp" "$DB" && log "DB restored from backup snapshot" || log "DB restore failed"
      sudo systemctl restart tradingai-api 2>/dev/null || true
    fi
  fi
fi

# 5. Data freshness — during market hours, price_1m should be <15 min old
HOUR=$(TZ=Asia/Kolkata date +%H)
WDAY=$(TZ=Asia/Kolkata date +%u)
if [ "$WDAY" -le 5 ] && [ "$HOUR" -ge 9 ] && [ "$HOUR" -le 15 ]; then
  FRESH=$(python3 -c "
import sqlite3
try:
    c=sqlite3.connect('$DB')
    r=c.execute(\"SELECT timestamp FROM price_1m ORDER BY timestamp DESC LIMIT 1\").fetchone()
    if r:
        from datetime import datetime, timezone
        ts=str(r[0]).replace('Z','+00:00')
        try: age=(datetime.now(timezone.utc)-datetime.fromisoformat(ts).replace(tzinfo=timezone.utc) if 'T' in ts else datetime.now(timezone.utc)-datetime.strptime(str(r[0]),'%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)).total_seconds()/60
        except Exception: age=999
        print(int(age))
    else: print(999)
except Exception as e: print(999)
" 2>/dev/null || echo 999)
  if [ "${FRESH:-999}" -gt 15 ]; then
    log "DATA STALE: freshest price_1m is ${FRESH}m old — triggering fetcher"
    (cd /opt/tradingai/backend && SKIP_LLM=1 /usr/bin/python3 data_fetcher_db.py >> /opt/tradingai/logs/data.log 2>&1 &)
  fi
fi

# 6. Cron itself — ensure crond is running (rare, but VM can lose it)
if ! pgrep -x cron > /dev/null 2>&1 && ! pgrep -x crond > /dev/null 2>&1; then
  log "CRON DAEMON DOWN — restarting"
  sudo service cron restart 2>&1 | head -2 | while read l; do log "cron: $l"; done
fi

log "self-heal cycle done (disk ${DISK_PCT}%, api $(curl -sf --max-time 5 $API > /dev/null 2>&1 && echo ok || echo fail))"
