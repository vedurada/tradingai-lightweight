#!/usr/bin/env python3
import sys, os, json, sqlite3, time, argparse
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import yfinance as yf
from app.core.db import get_conn, DB_PATH
from app.core.config import instruments, settings

_IST = ZoneInfo('Asia/Kolkata')

SYMBOL_MAP = {
    'NIFTY': '^NSEI',
    'BANKNIFTY': '^NSEBANK',
    'INDIA_VIX': '^INDIAVIX',
}

MAX_5M_DAYS = 60

def fetch_candles_yfinance(instrument_id, days=55):
    symbol = SYMBOL_MAP.get(instrument_id, instrument_id)
    end = datetime.now(_IST)
    start = end - timedelta(days=days)
    try:
        t = yf.Ticker(symbol)
        hist = t.history(start=start, end=end, interval='5m')
        if hist.empty:
            return []
        candles = []
        for idx, row in hist.iterrows():
            candles.append({
                'instrument_id': instrument_id,
                'timestamp': idx.isoformat(),
                'open': float(row['Open']),
                'high': float(row['High']),
                'low': float(row['Low']),
                'close': float(row['Close']),
                'volume': int(row['Volume']) if row['Volume'] > 0 else 0,
                'source': 'yfinance',
                'data_state': 'LIVE',
                'ingested_at': datetime.now(_IST).isoformat(),
            })
        return candles
    except Exception as e:
        print(f"ERROR fetching {instrument_id}: {e}")
        return []

def validate_candle(candle):
    issues = []
    o, h, l, c = candle['open'], candle['high'], candle['low'], candle['close']
    if h < max(o, c):
        issues.append(f'high_below_close_or_open: h={h} max(o,c)={max(o,c)}')
    if l > min(o, c):
        issues.append(f'low_above_open_or_close: l={l} min(o,c)={min(o,c)}')
    if h < l:
        issues.append(f'high_below_low')
    if o <= 0 or h <= 0 or l <= 0 or c <= 0:
        issues.append(f'non_positive_price')
    return issues

def normalize_timestamp(ts_iso):
    try:
        dt = datetime.fromisoformat(ts_iso)
        if dt.tzinfo is not None:
            dt_ist = dt.astimezone(_IST)
        else:
            dt_ist = dt.replace(tzinfo=_IST)
        return dt_ist.strftime('%Y-%m-%dT%H:%M:%S+05:30')
    except:
        return ts_iso

def ingest(instrument_id, days=55, force=False):
    print(f"\n{'='*60}")
    print(f"INGESTING: {instrument_id}")
    print(f"{'='*60}")

    conn = get_conn()

    existing_count = conn.execute(
        'SELECT COUNT(*) FROM market_candles_5m WHERE instrument_id=?', (instrument_id,)
    ).fetchone()[0]
    print(f"Existing candles: {existing_count}")

    if existing_count > 0 and not force:
        print("Data already present. Use --force to re-ingest.")
        conn.close()
        return {'status': 'SKIPPED', 'reason': 'data_exists', 'existing': existing_count}

    if force:
        conn.execute('DELETE FROM market_candles_5m WHERE instrument_id=?', (instrument_id,))
        conn.commit()
        print("Cleared existing data for forced re-ingestion")

    print(f"Fetching {days} days of 5m data from yfinance...")
    candles = fetch_candles_yfinance(instrument_id, days)
    print(f"Fetched: {len(candles)} raw candles")

    if not candles:
        conn.close()
        return {'status': 'NO_DATA', 'reason': 'yfinance_empty'}

    validated = []
    invalid_count = 0
    dup_count = 0
    seen_timestamps = set()

    for c in candles:
        ts = normalize_timestamp(c['timestamp'])
        c['timestamp'] = ts
        issues = validate_candle(c)
        if issues:
            invalid_count += 1
            continue
        if ts in seen_timestamps:
            dup_count += 1
            continue
        seen_timestamps.add(ts)
        validated.append(c)

    print(f"Validated: {len(validated)} candles")
    print(f"Invalid: {invalid_count}")
    print(f"Duplicates removed: {dup_count}")

    if not validated:
        conn.close()
        return {'status': 'NO_VALID_DATA', 'reason': 'all_candles_invalid'}

    conn.executemany('''INSERT OR IGNORE INTO market_candles_5m
        (candle_id, instrument_id, timestamp, open, high, low, close, volume, source, data_state, ingested_at, is_complete)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',
        [(f"C-{instrument_id}-{c['timestamp']}", c['instrument_id'], c['timestamp'], c['open'], c['high'],
          c['low'], c['close'], c['volume'], c['source'], c['data_state'], c['ingested_at'], 1)
         for c in validated])
    conn.commit()

    db_count = conn.execute(
        'SELECT COUNT(*) FROM market_candles_5m WHERE instrument_id=?', (instrument_id,)
    ).fetchone()[0]
    print(f"Database candles: {db_count}")

    timestamps = [c['timestamp'] for c in validated]
    quality = {
        'instrument': instrument_id,
        'provider': 'yfinance',
        'date_range': {
            'start': timestamps[0],
            'end': timestamps[-1],
        },
        'raw_fetched': len(candles),
        'validated': len(validated),
        'invalid_rejected': invalid_count,
        'duplicates_removed': dup_count,
        'database_count': db_count,
        'ingested_at': datetime.now(_IST).isoformat(),
    }

    conn.close()

    report_path = f"/opt/tradingai/data/generated/{instrument_id.lower()}_ingestion_quality.json"
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, 'w') as f:
        json.dump(quality, f, indent=2)
    print(f"Quality report: {report_path}")

    return quality

def session_analysis(instrument_id):
    print(f"\n{'='*60}")
    print(f"SESSION ANALYSIS: {instrument_id}")
    print(f"{'='*60}")

    conn = get_conn()
    rows = conn.execute('''
        SELECT SUBSTR(timestamp, 1, 10) as session_date,
               COUNT(*) as candle_count,
               MIN(timestamp) as first_ts,
               MAX(timestamp) as last_ts
        FROM market_candles_5m
        WHERE instrument_id=?
        GROUP BY session_date
        ORDER BY session_date
    ''', (instrument_id,)).fetchall()

    total_sessions = len(rows)
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
            print(f"  Partial session {r['session_date']}: {count}/{expected} candles")

    print(f"Total sessions: {total_sessions}")
    print(f"Complete: {complete}")
    print(f"Partial: {partial}")
    print(f"Total candles: {total_candles}")

    if total_sessions > 0:
        coverage = round(complete / total_sessions * 100, 1)
        print(f"Coverage: {coverage}%")

    report = {
        'instrument': instrument_id,
        'trading_sessions': total_sessions,
        'complete_sessions': complete,
        'partial_sessions': partial,
        'total_candles': total_candles,
        'expected_candles_per_session': expected,
        'coverage_percent': coverage if total_sessions > 0 else 0,
        'data_source': 'yfinance',
    }

    conn.close()

    report_path = f"/opt/tradingai/data/generated/{instrument_id.lower()}_session_quality.json"
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, 'w') as f:
        json.dump(report, f, indent=2)
    print(f"Session report: {report_path}")

    return report

def main():
    parser = argparse.ArgumentParser(description='Ingest historical 5m data')
    parser.add_argument('--instrument', required=True, choices=['NIFTY', 'BANKNIFTY', 'INDIA_VIX'])
    parser.add_argument('--days', type=int, default=55, help='Days to fetch (max 60 for 5m)')
    parser.add_argument('--force', action='store_true', help='Re-ingest existing data')
    args = parser.parse_args()

    if args.days > MAX_5M_DAYS:
        print(f"WARNING: 5m data limited to {MAX_5M_DAYS} days. Using {MAX_5M_DAYS}.")
        args.days = MAX_5M_DAYS

    result = ingest(args.instrument, args.days, args.force)
    if result.get('status') in ('COMPLETED', 'SKIPPED'):
        session_analysis(args.instrument)
    print(f"\nResult: {result}")

if __name__ == '__main__':
    main()
