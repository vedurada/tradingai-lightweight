"""Tiny SQLite read-through cache for provider responses (Phase 11).

Why: 2 gunicorn workers x N browsers poll every 30s/120s; without a shared
cache every request hits yfinance (slow, rate-limit prone). An in-process
dict would NOT share across workers, so the cache lives in SQLite
(same Python/SQLite stack, no new infra).

Contract:
- Key: (instrument_symbol, kind) where kind in ('quote', 'candles').
- Stored: payload JSON, data_ts (ORIGINAL market-data timestamp, preserved
  byte-identical), fetch_ts (when upstream was hit), state.
- A cache hit returns the stored payload UNCHANGED: the original data_ts
  travels with it, so cached data can never masquerade as fresh — freshness
  is always recomputed downstream from data_ts.
- TTLs: quote 45s, candles 90s (candles only change on 5m boundaries).
  Expired rows are ignored (treated as miss) and overwritten on refetch.
"""
import json
import sqlite3
import time
from app.core.db import DB_PATH

_TTL = {'quote': 45, 'candles': 90}


# PERF (no logic change): table created ONCE at import. Previously every
# get()/put() ran CREATE TABLE + commit — a write transaction on the read
# path that forced fsync/lock contention under parallel requests.
def _conn():
    return sqlite3.connect(DB_PATH, timeout=10)


def _ensure():
    try:
        c = sqlite3.connect(DB_PATH, timeout=10)
        c.execute('CREATE TABLE IF NOT EXISTS provider_cache ('
                  'cache_key TEXT PRIMARY KEY, payload TEXT NOT NULL, '
                  'data_ts TEXT, fetch_ts REAL NOT NULL, state TEXT NOT NULL)')
        c.commit()
        c.close()
    except Exception:
        pass


_ensure()


def cache_key(symbol, kind):
    return f'{symbol}|{kind}'


def get(symbol, kind):
    """Return (payload_dict, fetch_ts) on fresh hit, else (None, None)."""
    try:
        c = _conn()
        row = c.execute('SELECT payload, data_ts, fetch_ts, state FROM provider_cache '
                        'WHERE cache_key=?', (cache_key(symbol, kind),)).fetchone()
        c.close()
    except Exception:
        return None, None
    if not row:
        return None, None
    payload_s, data_ts, fetch_ts, state = row
    if (time.time() - fetch_ts) > _TTL.get(kind, 60):
        return None, None
    try:
        payload = json.loads(payload_s)
    except (TypeError, ValueError):
        return None, None
    payload['_cache_hit'] = True
    payload['_cache_fetch_ts'] = fetch_ts
    return payload, fetch_ts


def put(symbol, kind, payload, data_ts, state):
    try:
        c = _conn()
        c.execute('INSERT OR REPLACE INTO provider_cache '
                  '(cache_key, payload, data_ts, fetch_ts, state) VALUES (?,?,?,?,?)',
                  (cache_key(symbol, kind), json.dumps(payload), data_ts,
                   time.time(), state))
        c.commit()
        c.close()
    except Exception:
        pass


def invalidate(symbol=None, kind=None):
    try:
        c = _conn()
        if symbol and kind:
            c.execute('DELETE FROM provider_cache WHERE cache_key=?',
                      (cache_key(symbol, kind),))
        elif symbol:
            c.execute('DELETE FROM provider_cache WHERE cache_key LIKE ?', (f'{symbol}|%',))
        else:
            c.execute('DELETE FROM provider_cache')
        c.commit()
        c.close()
    except Exception:
        pass
