#!/usr/bin/env bash
# B.4 DB cleanup job — runs daily via cron or manually.
# Enforces retention policies from config/instruments.json.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="$(dirname "$SCRIPT_DIR")"
DB_PATH="${TRADINGAI_DB_PATH:-$APP_DIR/database/tradingai.db}"
RETENTION_CONFIG="$APP_DIR/config/instruments.json"

python3 -c "
import sqlite3, json, os, sys
from datetime import datetime, timezone

db_path = '$DB_PATH'
retention = {'minute_data_hours': 24, 'five_minute_data_days': 90, 'daily_data_years': 5}
if os.path.exists('$RETENTION_CONFIG'):
    try:
        with open('$RETENTION_CONFIG') as f:
            config = json.load(f)
            for k in retention:
                if k in config:
                    retention[k] = config[k]
    except Exception:
        pass

conn = sqlite3.connect(db_path, timeout=30)
conn.execute('PRAGMA journal_mode=WAL')
conn.execute('PRAGMA busy_timeout=10000')

minute_ago = datetime.now(timezone.utc).timestamp() - retention.get('minute_data_hours', 24) * 3600
five_min_ago = datetime.now(timezone.utc).timestamp() - retention.get('five_minute_data_days', 90) * 86400
daily_ago = datetime.now(timezone.utc).timestamp() - retention.get('daily_data_years', 5) * 86400

deleted = 0
for table, cutoff in [('prices', minute_ago), ('indicators', five_min_ago), ('market_structure', five_min_ago)]:
    try:
        c = conn.execute(f'DELETE FROM {table} WHERE strftime(\"%s\", timestamp) < ?', (cutoff,))
        deleted += c.rowcount
    except Exception as e:
        print(f'Cleanup skip {table}: {e}', file=sys.stderr)

conn.commit()
conn.close()
print(f'Cleaned up {deleted} rows')
"
