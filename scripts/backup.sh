#!/usr/bin/env bash
# TradingAI Database Backup
# Backs up SQLite database with timestamp, retention, verification.
# Never overwrites the live DB. Never stores backups in Git.
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DB_PATH="${TRADINGAI_DB_PATH:-$APP_DIR/database/tradingai.db}"
BACKUP_DIR="${TRADINGAI_BACKUP_DIR:-$APP_DIR/backups}"
RETENTION_DAYS="${TRADINGAI_BACKUP_RETENTION_DAYS:-30}"
LOG_FILE="${TRADINGAI_BACKUP_LOG:-$APP_DIR/logs/backup.log}"

mkdir -p "$BACKUP_DIR"
mkdir -p "$(dirname "$LOG_FILE")"

timestamp=$(date -u +"%Y%m%d_%H%M%S")
backup_file="$BACKUP_DIR/tradingai_${timestamp}.db"

log() {
    local msg="$1"
    local ts
    ts=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
    echo "$ts $msg" >> "$LOG_FILE"
    echo "$ts $msg"
}

log "BACKUP START: $backup_file"

if [ ! -f "$DB_PATH" ]; then
    log "BACKUP FAILED: DB not found at $DB_PATH"
    exit 1
fi

cp "$DB_PATH" "$backup_file"

if [ ! -s "$backup_file" ]; then
    log "BACKUP FAILED: backup file is empty"
    rm -f "$backup_file"
    exit 1
fi

log "BACKUP VERIFY: checking integrity"

python3 -c "
import sqlite3, sys, os
db_path = '$backup_file'
try:
    conn = sqlite3.connect(db_path)
    count = conn.execute('SELECT COUNT(*) FROM sqlite_master WHERE type=\"table\"').fetchone()[0]
    conn.close()
    if count == 0:
        print('FAIL: no tables')
        sys.exit(1)
    print('OK: ' + str(count) + ' tables')
except Exception as e:
    print('FAIL: ' + str(e))
    sys.exit(1)
" >> "$LOG_FILE" 2>&1

if [ $? -ne 0 ]; then
    log "BACKUP VERIFY FAILED"
    rm -f "$backup_file"
    exit 1
fi

log "BACKUP OK: $backup_file ($(stat -c%s "$backup_file" 2>/dev/null || stat -f%z "$backup_file" 2>/dev/null) bytes)"

log "BACKUP RETENTION: removing backups older than $RETENTION_DAYS days"
find "$BACKUP_DIR" -name "tradingai_*.db" -type f -mtime +$RETENTION_DAYS -delete -print >> "$LOG_FILE" 2>&1

remaining=$(find "$BACKUP_DIR" -name "tradingai_*.db" -type f | wc -l)
log "BACKUP RETENTION: $remaining backups retained"
log "BACKUP COMPLETE"