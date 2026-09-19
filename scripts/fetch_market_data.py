#!/usr/bin/env python3
import sys, os, json, sqlite3, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from zoneinfo import ZoneInfo
from datetime import datetime, timedelta
import yfinance as yf
from app.core.db import get_conn, DB_PATH
from app.core.config import settings, instruments

_IST = ZoneInfo('Asia/Kolkata')

SYMBOL_MAP = {"NIFTY": "^NSEI", "BANKNIFTY": "^NSEBANK", "INDIA_VIX": "^INDIAVIX"}

def fetch_candles(instrument_id, periods=100):
    symbol = SYMBOL_MAP.get(instrument_id, instrument_id)
    try:
        t = yf.Ticker(symbol)
        hist = t.history(period='10d', interval='5m')
        if hist.empty:
            return []
        candles = []
        conn = get_conn()
        now_ist = datetime.now(_IST)
        for idx, row in hist.tail(periods).iterrows():
            candle_id = f"C-{instrument_id}-{idx.strftime('%Y%m%d%H%M%S')}"
            conn.execute('''INSERT OR REPLACE INTO market_candles_5m
                (candle_id, instrument_id, timestamp, open, high, low, close, volume, source, data_state, ingested_at, is_complete)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',
                (candle_id, instrument_id, idx.isoformat(), float(row['Open']), float(row['High']),
                 float(row['Low']), float(row['Close']), int(row['Volume']), 'yfinance', 'LIVE',
                 now_ist.isoformat(), 1))
            candles.append({'timestamp': idx.isoformat(), 'open': float(row['Open']), 'high': float(row['High']),
                          'low': float(row['Low']), 'close': float(row['Close']), 'volume': int(row['Volume'])})
        conn.commit()
        conn.close()
        return candles
    except Exception as e:
        return []

def fetch_snapshot(instrument_id):
    symbol = SYMBOL_MAP.get(instrument_id, instrument_id)
    try:
        t = yf.Ticker(symbol)
        hist = t.history(period='2d', interval='5m')
        if hist.empty:
            return None
        latest = hist.iloc[-1]
        prev = hist.iloc[-2] if len(hist) > 1 else latest
        now_ist = datetime.now(_IST)
        conn = get_conn()
        snapshot_id = f"SN-{instrument_id}-{now_ist.strftime('%Y%m%d%H%M%S')}"
        conn.execute('''INSERT INTO market_snapshots
            (snapshot_id, instrument_id, timestamp, price, change, change_pct, vwap, ema20, ema200, rsi, adx, macd, macd_signal, atr, cpr_pivot, cpr_r1, cpr_r2, cpr_s1, cpr_s2, india_vix, trend, vwap_relation, momentum, volatility, structure, opening_behavior, data_state, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (snapshot_id, instrument_id, now_ist.isoformat(), float(latest['Close']),
             float(latest['Close'] - prev['Close']), 0.0, None, None, None, None, None, None, None, None,
             None, None, None, None, None, None, None, None, None, None, None, None, None, 'LIVE', now_ist.isoformat()))
        conn.commit()
        conn.close()
        return {'price': float(latest['Close']), 'timestamp': now_ist.isoformat(), 'source': 'yfinance', 'state': 'LIVE'}
    except Exception:
        return None

if __name__ == '__main__':
    for inst in instruments:
        sid = inst['instrument_id']
        fetch_candles(sid)
        fetch_snapshot(sid)
        print(f"Fetched data for {sid}")
