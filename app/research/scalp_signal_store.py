"""Persistent signal identity for ScanLP (scalp). Phase 4: recovery-friendly."""
import hashlib, sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

_IST = ZoneInfo('Asia/Kolkata')

CREATE_SQL = """CREATE TABLE IF NOT EXISTS scalp_signals (
    signal_id TEXT PRIMARY KEY,
    trade_date TEXT NOT NULL,
    instrument_id TEXT NOT NULL,
    strategy TEXT NOT NULL,
    direction TEXT NOT NULL,
    signal_type TEXT NOT NULL,
    source_candle_ts TEXT NOT NULL,
    reference_price REAL,
    reference_stop REAL,
    reference_target REAL,
    reference_level TEXT,
    status TEXT NOT NULL DEFAULT 'NEW',
    paper_trade_id TEXT,
    last_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (instrument_id, source_candle_ts, direction)
)"""


def init_schema(conn):
    conn.execute(CREATE_SQL)
    # additive columns for older DBs
    for col, typ in (('reference_stop', 'REAL'), ('reference_target', 'REAL'), ('last_error', 'TEXT')):
        try:
            conn.execute(f"ALTER TABLE scalp_signals ADD COLUMN {col} {typ}")
        except Exception:
            pass
    conn.commit()


def make_signal_id(instrument, candle_ts, direction, level):
    raw = f"{instrument}|{candle_ts}|{direction}|{level}"
    return "SS-" + hashlib.sha1(raw.encode()).hexdigest()[:12].upper()


def record_signal(conn, instrument, trade_date, direction, level, candle_ts, ref_price=None, ref_stop=None, ref_target=None):
    init_schema(conn)
    sid = make_signal_id(instrument, candle_ts, direction, level)
    now = datetime.now(_IST).isoformat()
    try:
        conn.execute(
            """INSERT INTO scalp_signals (signal_id, trade_date, instrument_id, strategy, direction,
               signal_type, source_candle_ts, reference_price, reference_stop, reference_target,
               reference_level, status, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (sid, trade_date, instrument, 'Scalp HLC 3-bar', direction, level, candle_ts,
             ref_price, ref_stop, ref_target, level, 'NEW', now, now))
        conn.commit()
    except sqlite3.IntegrityError:
        pass
    return sid


def mark_traded(conn, signal_id, trade_id):
    init_schema(conn)
    now = datetime.now(_IST).isoformat()
    conn.execute(
        "UPDATE scalp_signals SET status='TRADED', paper_trade_id=?, last_error=NULL, updated_at=? WHERE signal_id=?",
        (trade_id, now, signal_id))
    conn.commit()


def mark_failed(conn, signal_id, reason):
    # Do not permanently fail; keep NEW for retry, but record last error.
    init_schema(conn)
    now = datetime.now(_IST).isoformat()
    conn.execute(
        "UPDATE scalp_signals SET status='NEW', last_error=?, updated_at=? WHERE signal_id=? AND status!='TRADED'",
        (str(reason)[:500], now, signal_id))
    conn.commit()


def find_existing_trade(conn, instrument, trade_date):
    row = conn.execute(
        "SELECT trade_id FROM paper_trades WHERE instrument_id=? AND (scenario='SCALP_HLC' OR qualification_evidence LIKE '%SCALP_HLC%') AND substr(entry_time,1,10)=?",
        (instrument, trade_date)).fetchone()
    return row[0] if row else None


def recover_new_signals(conn):
    """Return signal rows that are NEW and may need trade creation."""
    init_schema(conn)
    return conn.execute(
        "SELECT signal_id, instrument_id, trade_date, direction, reference_price, reference_stop, reference_target, source_candle_ts FROM scalp_signals WHERE status='NEW'").fetchall()
