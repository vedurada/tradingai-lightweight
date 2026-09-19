#!/usr/bin/env python3
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import datetime
from zoneinfo import ZoneInfo
from app.core.db import get_conn
from app.core.config import instruments, settings
from app.market.provider import MarketDataProvider

_IST = ZoneInfo('Asia/Kolkata')

def generate_nifty_summary():
    conn = get_conn()
    provider = MarketDataProvider()
    quote = provider.get_quote('NIFTY')
    latest_candle = conn.execute('SELECT * FROM market_candles_5m WHERE instrument_id="NIFTY" ORDER BY timestamp DESC LIMIT 1').fetchone()
    latest_snapshot = conn.execute('SELECT * FROM market_snapshots WHERE instrument_id="NIFTY" ORDER BY timestamp DESC LIMIT 1').fetchone()
    paper_count = conn.execute('SELECT COUNT(*) as c FROM paper_trades WHERE instrument_id="NIFTY" AND status IN ("ACTIVE","OPEN")').fetchone()['c']
    daily_lock = conn.execute('SELECT * FROM daily_trade_locks WHERE instrument_id="NIFTY" AND date=? AND status="CONSUMED"',
        (datetime.now(_IST).strftime('%Y-%m-%d'),)).fetchone()
    result = {
        'instrument': 'NIFTY', 'price': quote.get('price'), 'change': quote.get('change'),
        'change_pct': quote.get('change_pct'), 'state': quote.get('state'),
        'timestamp': quote.get('timestamp', datetime.now(_IST).isoformat()),
        'source': quote.get('source'), 'vix': None,
        'market_status': 'OPEN' if 9.25 <= datetime.now(_IST).hour < 15.5 else 'CLOSED',
        'active_paper_trades': paper_count,
        'daily_trade_locked': daily_lock is not None,
        'latest_candle': dict(latest_candle) if latest_candle else None,
        'latest_snapshot': dict(latest_snapshot) if latest_snapshot else None,
    }
    conn.close()
    return result

def generate_nifty_decision():
    conn = get_conn()
    daily_lock = conn.execute('SELECT * FROM daily_trade_locks WHERE instrument_id="NIFTY" AND date=? AND status="CONSUMED"',
        (datetime.now(_IST).strftime('%Y-%m-%d'),)).fetchone()
    paper = conn.execute('SELECT * FROM paper_trades WHERE instrument_id="NIFTY" AND status IN ("ACTIVE","OPEN") ORDER BY created_at DESC LIMIT 1').fetchone()
    result = {'instrument': 'NIFTY', 'timestamp': datetime.now(_IST).isoformat()}
    if daily_lock:
        result['decision'] = 'NO_TRADE'
        result['reasons'] = ['daily_trade_limit_consumed']
    elif paper:
        result['decision'] = 'ACTIVE_PAPER_TRADE'
        result['trade'] = dict(paper)
    else:
        result['decision'] = 'WAITING'
        result['reasons'] = ['awaiting_scenario']
    conn.close()
    return result

def generate_all():
    data = {}
    for inst in instruments:
        sid = inst['instrument_id']
        if sid == 'NIFTY':
            data['nifty_summary'] = generate_nifty_summary()
            data['nifty_decision'] = generate_nifty_decision()
    with open('/opt/tradingai_new/data/generated/nifty_summary.json', 'w') as f:
        json.dump(data, f, indent=2, default=str)
    print('Generated frontend JSON')

if __name__ == '__main__':
    generate_all()
