#!/usr/bin/env python3
import sys, os, json, sqlite3, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from zoneinfo import ZoneInfo
from datetime import datetime
from app.core.db import get_conn, DB_PATH
from app.core.config import settings, instruments
from app.market.zerodha_provider import ZerodhaDataProvider

_IST = ZoneInfo('Asia/Kolkata')

SYMBOL_MAP = {"NIFTY": "NSE:NIFTY 50", "BANKNIFTY": "NSE:NIFTY BANK", "INDIA_VIX": "NSE:INDIA VIX"}


def fetch_candles(instrument_id, periods=100):
    zsymbol = SYMBOL_MAP.get(instrument_id, instrument_id)
    try:
        provider = ZerodhaDataProvider()
        res = provider.get_5m_candles(zsymbol, periods=periods)
        if not res or res.get('state') not in ('LIVE',) or not res.get('candles'):
            return []
        candles = []
        conn = get_conn()
        now_ist = datetime.now(_IST)
        for c in res['candles']:
            ts = c.get('timestamp', '')
            candle_id = f"C-{instrument_id}-{ts.replace(':', '').replace('-', '').replace('T', '')}"
            conn.execute('''INSERT OR REPLACE INTO market_candles_5m
                (candle_id, instrument_id, timestamp, open, high, low, close, volume, source, data_state, ingested_at, is_complete)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,1)''',
                (candle_id, instrument_id, ts, float(c['open']), float(c['high']),
                 float(c['low']), float(c['close']), int(c.get('volume') or 0), 'zerodha', 'LIVE',
                 now_ist.isoformat()))
            candles.append({'timestamp': ts, 'open': float(c['open']), 'high': float(c['high']),
                            'low': float(c['low']), 'close': float(c['close']), 'volume': int(c.get('volume') or 0)})
        conn.commit()
        conn.close()
        return candles
    except Exception as e:
        print(f"fetch_candles failed for {instrument_id}: {e}")
        return []


def fetch_snapshot(instrument_id):
    zsymbol = SYMBOL_MAP.get(instrument_id, instrument_id)
    try:
        provider = ZerodhaDataProvider()
        q = provider.get_quote(zsymbol)
        if not q or q.get('state') not in ('LIVE',):
            return None
        now_ist = datetime.now(_IST)
        conn = get_conn()
        snapshot_id = f"SN-{instrument_id}-{now_ist.strftime('%Y%m%d%H%M%S')}"
        conn.execute('''INSERT INTO market_snapshots
            (snapshot_id, instrument_id, timestamp, price, change, change_pct, vwap, ema20, ema200, rsi, adx, macd, macd_signal, atr, cpr_pivot, cpr_r1, cpr_r2, cpr_s1, cpr_s2, india_vix, trend, vwap_relation, momentum, volatility, structure, opening_behavior, data_state, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (snapshot_id, instrument_id, now_ist.isoformat(), float(q['price']),
             float(q.get('change') or 0.0), float(q.get('change_pct') or 0.0),
             None, None, None, None, None, None, None, None,
             None, None, None, None, None,
             None, None, None, None, None, None, None, 'LIVE', now_ist.isoformat()))
        conn.commit()
        conn.close()
        return {'price': float(q['price']), 'timestamp': now_ist.isoformat(), 'source': 'zerodha', 'state': 'LIVE'}
    except Exception as e:
        print(f"fetch_snapshot failed for {instrument_id}: {e}")
        return None


if __name__ == '__main__':
    for inst in instruments:
        sid = inst['instrument_id']
        fetch_candles(sid)
        fetch_snapshot(sid)
        print(f"Fetched data for {sid}")
