"""Shared data access, level math and trade normalisation for the research run.

READ-ONLY against the market database: every connection is opened with the
SQLite URI read-only mode, so this module can never write to production.
Level math is imported from the production module (calculate_cpr /
pivot_levels / day_levels) so the candidate uses byte-identical CPR, pivot,
PDH and PDL definitions to the live engine.
"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime

from app.core.db import DB_PATH
from app.research.cpr_strategy_engine import calculate_cpr, pivot_levels

OPEN_MIN = '09:20'
OPEN_EOD = '15:20'
LAST_SCAN_CANDLE = '15:25'      # baseline scans candles with [11:16] < '15:25'
MIN_SESSION_CANDLES = 10        # production MIN_CANDLES
STOP_PCT = 0.005                # production OPEN_STOP_PCT
TARGET_PCT = 0.02               # production OPEN_TARGET_PCT
LOT_SIZES = {'NIFTY': 65, 'BANKNIFTY': 30}   # NSE lots from 30-Dec-2025


def ro_conn(db_path: str | None = None) -> sqlite3.Connection:
    """Read-only connection (query only). Never writes."""
    path = db_path or DB_PATH
    conn = sqlite3.connect(f'file:{path}?mode=ro', uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def load_sessions(conn, instrument: str, date_start: str, date_end: str):
    """Session dates present in market_candles_5m for the range (sorted)."""
    rows = conn.execute(
        'SELECT DISTINCT substr(timestamp,1,10) AS d FROM market_candles_5m '
        'WHERE instrument_id=? AND substr(timestamp,1,10) BETWEEN ? AND ? '
        'ORDER BY 1', (instrument, date_start, date_end)).fetchall()
    return [r['d'] for r in rows]


def load_candles(conn, instrument: str, day_iso: str):
    """All candles of one session, ascending, matching the production loader.

    Production session_candles() returns timestamp/open/high/low/close with no
    time-of-day filter; the scan filter (timestamp[11:16] < '15:25') and the
    MIN_SESSION_CANDLES gate are applied by the callers, exactly like
    run_opens_range does.
    """
    rows = conn.execute(
        'SELECT timestamp,open,high,low,close FROM market_candles_5m '
        'WHERE instrument_id=? AND substr(timestamp,1,10)=? ORDER BY timestamp',
        (instrument, day_iso)).fetchall()
    return [dict(r) for r in rows]


def prev_session_ohlc(conn, instrument: str, day_iso: str):
    """Max high / min low / last close strictly BEFORE day_iso (PIT).

    Mirrors app.research.cpr_trigger_engine.prev_session_ohlc exactly; the
    SQL is duplicated rather than imported so this module stays free of the
    production engine's signal flags. Verified for equality in the unit tests.
    """
    row = conn.execute(
        'SELECT substr(timestamp,1,10) AS d, MAX(high) AS h, MIN(low) AS l '
        'FROM market_candles_5m WHERE instrument_id=? AND substr(timestamp,1,10)< ? '
        'GROUP BY d ORDER BY d DESC LIMIT 1', (instrument, day_iso)).fetchone()
    if not row or row['h'] is None:
        return None
    last = conn.execute(
        'SELECT close FROM market_candles_5m WHERE instrument_id=? '
        'AND substr(timestamp,1,10)=? ORDER BY timestamp DESC LIMIT 1',
        (instrument, row['d'])).fetchone()
    if not last or last['close'] is None:
        return None
    return {'date': row['d'], 'high': float(row['h']), 'low': float(row['l']),
            'close': float(last['close'])}


def day_levels(prev_high, prev_low, prev_close):
    """CPR + pivot + PDH/PDL bundle from previous-session OHLC (production math)."""
    try:
        ph, pl, pc = float(prev_high), float(prev_low), float(prev_close)
    except (TypeError, ValueError):
        return None
    if not (ph > 0 and pl > 0 and pc > 0 and ph >= pl):
        return None
    cpr = calculate_cpr(ph, pl, pc)
    piv = pivot_levels(ph, pl, cpr['pp'])
    return {'pp': cpr['pp'], 'tc': cpr['tc'], 'bc': cpr['bc'],
            'r1': piv['r1'], 's1': piv['s1'], 'r2': piv['r2'], 's2': piv['s2'],
            'pdh': ph, 'pdl': pl, 'prev_close': pc}


def scan_candles(candles):
    """Baseline scan set: timestamp[11:16] < '15:25' (production filter)."""
    return [c for c in candles if str(c['timestamp'])[11:16] < LAST_SCAN_CANDLE]


def lot(instrument: str) -> int:
    return LOT_SIZES.get((instrument or '').upper(), 65)


def period_of(day_iso: str, cfg: dict) -> str:
    for name in ('in_sample', 'validation', 'out_of_sample'):
        a, b = cfg['periods'][name]
        if a <= day_iso <= b:
            return {'in_sample': 'IS', 'validation': 'VAL',
                    'out_of_sample': 'OOS'}[name]
    return 'OUT_OF_RANGE'


def exits_opens_abs(direction: str, entry: float, stop_px: float, tgt_px: float,
                    opens):
    """Absolute-price twin of production exits_opens (identical semantics).

    Walks subsequent candle OPENS; stop checked first; an open exactly on the
    stop counts STOP, exactly on the target counts TARGET. Returns
    (R, exit_price, reason, exit_ts) or None when no open resolves the trade
    (caller then applies the 15:20 EOD exit).
    """
    risk = abs(entry - stop_px)
    if not risk:
        return 0.0, entry, 'NO_RISK', None
    for ts, o in opens:
        try:
            o = float(o)
        except (TypeError, ValueError):
            continue
        if direction == 'BULL':
            s, t = o <= stop_px, o >= tgt_px
        else:
            s, t = o >= stop_px, o <= tgt_px
        if s:
            return -1.0, round(o, 2), 'STOP', ts
        if t:
            return round((abs(tgt_px - entry) / risk), 3), round(o, 2), 'TARGET', ts
    return None


def now_ist() -> str:
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo('Asia/Kolkata')).isoformat()
