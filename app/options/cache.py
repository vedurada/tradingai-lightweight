"""Phase 14: options cache — shared SQLite across Gunicorn workers.

Reuses Phase 11 provider_cache pattern with instrument-specific keys.
Cached age is recomputed at serve time; cached data can never masquerade as fresh.
"""
import json
import sqlite3
import time
from app.core.db import DB_PATH
from app.options.contract import CACHE_TTL_S, OptionsFreshness


def _conn():
    c = sqlite3.connect(DB_PATH, timeout=10)
    c.execute("""CREATE TABLE IF NOT EXISTS options_provider_cache (
        cache_key TEXT PRIMARY KEY,
        payload TEXT NOT NULL,
        data_ts TEXT,
        fetch_ts REAL NOT NULL,
        state TEXT NOT NULL
    )""")
    c.commit()
    return c


def cache_key(instrument, kind):
    return f"{instrument}|options|{kind}"


def get(instrument, kind):
    """Return (payload_dict, fetch_ts) on fresh hit, else (None, None)."""
    try:
        c = _conn()
        row = c.execute("SELECT payload, data_ts, fetch_ts, state FROM options_provider_cache WHERE cache_key=?",
                         (cache_key(instrument, kind),)).fetchone()
        c.close()
    except Exception:
        return None, None
    if not row:
        return None, None
    payload_s, data_ts, fetch_ts, state = row
    if (time.time() - fetch_ts) > CACHE_TTL_S:
        return None, None
    try:
        payload = json.loads(payload_s)
    except (TypeError, ValueError):
        return None, None
    payload["_cache_hit"] = True
    payload["_cache_fetch_ts"] = fetch_ts
    return payload, fetch_ts


def put(instrument, kind, payload, data_ts, state):
    try:
        c = _conn()
        c.execute("INSERT OR REPLACE INTO options_provider_cache "
                  "(cache_key, payload, data_ts, fetch_ts, state) VALUES (?,?,?,?,?)",
                  (cache_key(instrument, kind), json.dumps(payload), data_ts,
                   time.time(), state))
        c.commit()
        c.close()
    except Exception:
        pass


def invalidate(instrument=None):
    try:
        c = _conn()
        if instrument:
            c.execute("DELETE FROM options_provider_cache WHERE cache_key LIKE ?",
                      (f"{instrument}|options|%",))
        else:
            c.execute("DELETE FROM options_provider_cache")
        c.commit()
        c.close()
    except Exception:
        pass


def recompute_age(payload):
    """Recompute age at serve time so cached data can never look fresh."""
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo
    data_ts = payload.get("timestamp") or payload.get("data_ts")
    if not data_ts:
        return None, OptionsFreshness.OPTIONS_NO_DATA
    try:
        dt = datetime.fromisoformat(data_ts)
        data_ts_s = dt.timestamp()
    except (ValueError, TypeError):
        return None, OptionsFreshness.OPTIONS_MALFORMED
    now_s = datetime.now(ZoneInfo("Asia/Kolkata")).timestamp()
    age = now_s - data_ts_s
    if age < 0:
        return round(abs(age), 1), OptionsFreshness.OPTIONS_MALFORMED
    if age < 300:
        return round(age, 1), OptionsFreshness.OPTIONS_FRESH
    return round(age, 1), OptionsFreshness.OPTIONS_STALE
