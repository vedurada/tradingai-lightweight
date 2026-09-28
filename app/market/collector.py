"""Production market-data collector for TradingAI.

Collects completed 5-minute candles for NIFTY, BANKNIFTY, INDIA_VIX
from yfinance and stores them in the TradingAI SQLite database.

- Only COMPLETED candles stored (is_complete=1)
- Uniqueness via INSERT OR IGNORE on candle_id (no duplicates)
- PIT invariant: only candles with timestamp <= cutoff are stored
- Asia/Kolkata throughout
- Uses existing MarketDataProvider (yfinance)
- Structured logging
"""
import logging, os, sqlite3, sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import yfinance as yf

from app.core.db import get_conn
from app.core.config import instruments, settings
from app.market.provider import MarketDataProvider

_IST = ZoneInfo('Asia/Kolkata')
log = logging.getLogger('tradingai.collector')

SYMBOL_MAP = {"NIFTY": "^NSEI", "BANKNIFTY": "^NSEBANK", "INDIA_VIX": "^INDIAVIX"}


def get_completed_cutoff(now_ist):
    """Latest completed 5m OPEN. First candle 09:15 completes at 09:20.

    FIX: cutoff was 09:10 at 09:15 (nonexistent candle). Now None until 09:20.
    """
    day_start = now_ist.replace(hour=9, minute=20, second=0, microsecond=0)
    if now_ist < day_start:
        return None
    fc = now_ist.replace(minute=(now_ist.minute // 5) * 5, second=0, microsecond=0)
    return fc - timedelta(minutes=5)


def collect_instrument(instrument_id, provider=None, backfill=False, target_date=None):
    if instrument_id not in SYMBOL_MAP:
        return 0, 'UNKNOWN_INSTRUMENT:' + instrument_id
    symbol = SYMBOL_MAP[instrument_id]
    now_ist = datetime.now(_IST)
    cutoff = get_completed_cutoff(now_ist)
    if cutoff is None:
        log.info('collector instrument=%s no completed candles yet', instrument_id)
        return 0, None
    if provider is None:
        provider = MarketDataProvider()
    # Bounded fetch: reuse provider _fetch_history (12s executor timeout + 1 retry).
    # Never raw yf.Ticker().history without timeout (hangs gunicorn/cron).
    try:
        from app.market.provider import _fetch_history as _bounded_fetch
        hist = _bounded_fetch(symbol, '10d', '5m')
    except Exception as e:
        log.error('collector instrument=%s fetch_error err=%s', instrument_id, str(e)[:160])
        return 0, 'FETCH_ERROR:' + str(e)[:120]
    if hist is None or hist.empty:
        log.warning('collector instrument=%s no data', instrument_id)
        return 0, None

    conn = get_conn()
    stored = 0
    cutoff_str = cutoff.isoformat()
    day = target_date or now_ist.date().isoformat()

    for idx, row in hist.iterrows():
        ts_utc = idx
        if ts_utc.tzinfo is not None:
            ts_ist = ts_utc.astimezone(_IST)
        else:
            ts_ist = ts_utc.replace(tzinfo=_IST)
        ts_str = ts_ist.isoformat()
        if ts_str > cutoff_str:
            continue
        # Backfill: when backfill=True (or target_date set) collect any past
        # session date <= cutoff; default (live cron) collects today only.
        if not backfill and target_date is None:
            if ts_ist.date().isoformat() != day:
                continue
        elif target_date is not None:
            if ts_ist.date().isoformat() != day:
                continue
        else:
            if ts_ist.date().isoformat() > day:
                continue
        try:
            o = float(row['Open'])
            h = float(row['High'])
            l = float(row['Low'])
            c = float(row['Close'])
            v = int(row['Volume'] or 0)
        except (KeyError, TypeError, ValueError):
            continue
        if not (o > 0 and h > 0 and l > 0 and c > 0):
            continue
        if h < l:
            continue
        if not (l <= o <= h and l <= c <= h):
            continue
        candle_id = 'C-' + instrument_id + '-' + ts_ist.strftime('%Y%m%d%H%M%S')
        try:
            conn.execute(
                'INSERT OR IGNORE INTO market_candles_5m '
                '(candle_id, instrument_id, timestamp, open, high, low, close, volume, source, data_state, ingested_at, session_id, is_complete) '
                'VALUES (?,?,?,?,?,?,?,?,?,?,?,?,1)',
                (candle_id, instrument_id, ts_str, o, h, l, c, v, 'yfinance', 'LIVE', now_ist.isoformat(), None))
            stored += 1
        except sqlite3.Error as e:
            log.error('collector instrument=%s insert_error candle=%s err=%s', instrument_id, ts_str, str(e)[:120])

    conn.commit()
    conn.close()
    if stored > 0:
        log.info('collector instrument=%s stored=%d cutoff=%s', instrument_id, stored, cutoff_str)
    return stored, None


def collect_all(backfill=False, target_date=None):
    total = 0
    errors = []
    for inst in instruments:
        if inst.get('active', 1) == 0:
            continue
        inst_id = inst.get('instrument_id', inst.get('symbol', ''))
        if inst_id not in SYMBOL_MAP:
            continue
        stored, err = collect_instrument(inst_id, backfill=backfill, target_date=target_date)
        total += stored
        if err:
            errors.append(inst_id + ':' + err)
    if errors:
        log.error('collector errors: %s', '; '.join(errors))
    return total, errors


if __name__ == '__main__':
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(name)s %(levelname)s %(message)s')
    import argparse as _ap
    _par = _ap.ArgumentParser()
    _par.add_argument('--backfill', action='store_true', help='collect past sessions, not just today')
    _par.add_argument('--date', default=None, help='target YYYY-MM-DD (implies backfill for that day)')
    _a = _par.parse_args()
    total, errors = collect_all(backfill=(_a.backfill or bool(_a.date)), target_date=_a.date)
    print('Collected ' + str(total) + ' candles')
    if errors:
        print('Errors: ' + str(errors))
