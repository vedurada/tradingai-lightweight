#!/usr/bin/env python3
import sys, os, json, sqlite3
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import datetime
from zoneinfo import ZoneInfo
from app.core.db import get_conn
from app.core.config import instruments

_IST = ZoneInfo('Asia/Kolkata')
conn = get_conn()

for inst in instruments:
    try:
        conn.execute('''INSERT OR IGNORE INTO instruments
            (instrument_id, symbol, name, exchange, instrument_type, timezone, active, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?)''',
            (inst['instrument_id'], inst['symbol'], inst['name'], inst['exchange'],
             inst['instrument_type'], inst.get('timezone', 'Asia/Kolkata'), inst.get('active', 1),
             datetime.now(_IST).isoformat(), datetime.now(_IST).isoformat()))
        print(f"Inserted: {inst['instrument_id']}")
    except Exception as e:
        print(f"Error {inst['instrument_id']}: {e}")

conn.commit()
count = conn.execute('SELECT COUNT(*) FROM instruments').fetchone()[0]
print(f"Total instruments: {count}")
for r in conn.execute('SELECT instrument_id, symbol FROM instruments'):
    print(f"  {r[0]}: {r[1]}")
conn.close()
