import sqlite3, os
# Single source of truth: TRADINGAI_BASE / TRADINGAI_DB_PATH env, else /opt/tradingai.
# No /opt/tradingai_new split (see config.py, monitor.py).
BASE = os.environ.get('TRADINGAI_BASE', '/opt/tradingai')
DB_PATH = os.environ.get('TRADINGAI_DB_PATH', os.path.join(BASE, 'database/tradingai.db'))

def get_conn():
    """Per-request SQLite connection (never shared across threads/workers).

    timeout=10s + WAL + busy_timeout so concurrent gunicorn workers queue
    instead of raising 'database is locked'. Caller must close (try/finally).
    check_same_thread defaults to True (safe: one conn per request/thread).
    """
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute('PRAGMA journal_mode=WAL')
    except Exception:
        pass
    try:
        conn.execute('PRAGMA busy_timeout=10000')
    except Exception:
        pass
    conn.execute('PRAGMA foreign_keys = ON')
    return conn
