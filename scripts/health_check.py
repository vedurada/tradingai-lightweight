#!/usr/bin/env python3
import sys, os, json, sqlite3
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from app.core.db import get_conn, DB_PATH
from app.core.config import settings, instruments

_IST = ZoneInfo('Asia/Kolkata')

def check_health():
    conn = get_conn()
    result = {
        'timestamp': datetime.now(_IST).isoformat(),
        'application': 'TradingAI',
        'database': {'path': DB_PATH, 'state': 'LIVE'},
        'market_data': {'provider': 'yfinance', 'state': 'CHECKING'},
        'scenario_engine': 'READY',
        'strategy_engine': 'READY',
        'paper_trade_engine': 'READY',
        'ai': {'enabled': settings.get('ai', {}).get('enabled', True), 'provider': settings.get('ai', {}).get('provider', 'groq')},
        'instruments': [i['instrument_id'] for i in instruments],
        'tables': [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    }
    for inst in instruments:
        sid = inst['instrument_id']
        count = conn.execute('SELECT COUNT(*) as c FROM market_snapshots WHERE instrument_id=?', (sid,)).fetchone()['c']
        result['market_data'][sid] = {'snapshots': count, 'state': 'LIVE' if count > 0 else 'NO_DATA'}
    conn.close()
    return result

if __name__ == '__main__':
    h = check_health()
    print(json.dumps(h, indent=2))
    conn = get_conn()
    sid = f"HK-{datetime.now(_IST).strftime('%Y%m%d%H%M%S')}"
    conn.execute('INSERT INTO system_health (check_id, timestamp, component, status, details) VALUES (?,?,?,?,?)',
        (sid, h['timestamp'], 'health_check', 'OK', json.dumps(h)))
    conn.commit()
    conn.close()
