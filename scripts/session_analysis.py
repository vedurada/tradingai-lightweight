#!/usr/bin/env python3
import sys, os, json, sqlite3
sys.path.insert(0, '/opt/tradingai_new')
from datetime import datetime
from zoneinfo import ZoneInfo
from app.core.db import get_conn

_IST = ZoneInfo('Asia/Kolkata')
conn = get_conn()

for inst in ['NIFTY', 'BANKNIFTY']:
    print(f"\n{'='*50}")
    print(f"SESSION ANALYSIS: {inst}")
    print(f"{'='*50}")

    rows = conn.execute('''
        SELECT SUBSTR(timestamp, 1, 10) as session_date,
               COUNT(*) as candle_count,
               MIN(timestamp) as first_ts,
               MAX(timestamp) as last_ts
        FROM market_candles_5m
        WHERE instrument_id=?
        GROUP BY session_date
        ORDER BY session_date
    ''', (inst,)).fetchall()

    total = len(rows)
    complete = 0
    partial = 0
    expected = 75
    total_candles = 0

    for r in rows:
        count = r['candle_count']
        total_candles += count
        if count >= expected - 5:
            complete += 1
        else:
            partial += 1

    coverage = round(complete / total * 100, 1) if total > 0 else 0

    print(f"Sessions: {total}")
    print(f"Complete: {complete}")
    print(f"Partial: {partial}")
    print(f"Candles: {total_candles}")
    print(f"Coverage: {coverage}%")
    if rows:
        print(f"Date range: {rows[0]['session_date']} to {rows[-1]['session_date']}")

    report = {
        'instrument': inst,
        'trading_sessions': total,
        'complete_sessions': complete,
        'partial_sessions': partial,
        'total_candles': total_candles,
        'expected_candles_per_session': expected,
        'coverage_percent': coverage,
        'date_range': {
            'start': rows[0]['session_date'] if rows else None,
            'end': rows[-1]['session_date'] if rows else None,
        },
        'provider': 'yfinance',
    }

    os.makedirs('/opt/tradingai_new/data/generated', exist_ok=True)
    path = f'/opt/tradingai_new/data/generated/{inst.lower()}_session_quality.json'
    with open(path, 'w') as f:
        json.dump(report, f, indent=2)
    print(f"Report: {path}")

conn.close()
