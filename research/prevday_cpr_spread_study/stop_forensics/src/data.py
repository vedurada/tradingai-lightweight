"""Read-only data access and data-quality checks against the study snapshot.

Every connection is opened through a read-only SQLite URI. Nothing here writes to
the snapshot or to the source database.
"""
from __future__ import annotations

import datetime
import sqlite3
import statistics

SCAN_CUTOFF = '15:25'          # production scan filter: timestamp[11:16] < '15:25'
OPEN_MIN = '09:20'
OPEN_EOD = '15:20'
SESSION_OPEN = '09:15'
SESSION_LAST = '15:25'         # last expected 5-minute bar of a complete session
BARS_PER_SESSION = 75          # 09:15 .. 15:25 inclusive

# production level token -> key in the day_levels bundle
LEVEL_KEY = {
    'R1': 'r1', 'R2': 'r2', 'PDH': 'pdh', 'BELOW_CPR': 'bc',
    'S1': 's1', 'S2': 's2', 'PDL': 'pdl', 'ABOVE_CPR': 'tc',
    'BRK_R1': 'r1', 'BRK_R2': 'r2', 'BRK_PDH': 'pdh', 'BRK_TC': 'tc',
    'BRK_S1': 's1', 'BRK_S2': 's2', 'BRK_PDL': 'pdl', 'BRK_BC': 'bc',
}

LOT_SIZES = {'NIFTY': 65, 'BANKNIFTY': 30}


def ro_conn(db_path: str) -> sqlite3.Connection:
    """Read-only connection (query only)."""
    conn = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def sessions(conn, instrument: str, date_start: str, date_end: str) -> list:
    rows = conn.execute(
        'SELECT DISTINCT substr(timestamp,1,10) AS d FROM market_candles_5m '
        'WHERE instrument_id=? AND substr(timestamp,1,10) BETWEEN ? AND ? '
        'ORDER BY 1', (instrument, date_start, date_end)).fetchall()
    return [r['d'] for r in rows]


def candles(conn, instrument: str, day_iso: str) -> list:
    rows = conn.execute(
        'SELECT timestamp,open,high,low,close,volume FROM market_candles_5m '
        'WHERE instrument_id=? AND substr(timestamp,1,10)=? ORDER BY timestamp',
        (instrument, day_iso)).fetchall()
    return [dict(r) for r in rows]


def scan_candles(candles_list: list) -> list:
    """Production scan set: timestamp[11:16] < '15:25'."""
    return [c for c in candles_list if str(c['timestamp'])[11:16] < SCAN_CUTOFF]


def prev_session(conn, instrument: str, day_iso: str):
    """Max high / min low / last close strictly BEFORE `day_iso` (point-in-time)."""
    row = conn.execute(
        'SELECT substr(timestamp,1,10) AS d, MAX(high) AS h, MIN(low) AS l '
        'FROM market_candles_5m WHERE instrument_id=? AND substr(timestamp,1,10)<? '
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


def level_bundle(prev) -> dict:
    """Production CPR/pivot/PDH/PDL bundle for a previous session."""
    from . import prod
    p = prod()
    cpr = p['calculate_cpr'](prev['high'], prev['low'], prev['close'])
    piv = p['pivot_levels'](prev['high'], prev['low'], cpr['pp'])
    return {
        'pp': cpr['pp'], 'tc': cpr['tc'], 'bc': cpr['bc'],
        'cpr_width_pct': cpr['width_pct'],
        'r1': piv['r1'], 's1': piv['s1'], 'r2': piv['r2'], 's2': piv['s2'],
        'pdh': prev['high'], 'pdl': prev['low'], 'prev_close': prev['close'],
        'prev_date': prev['date'],
    }


def level_price(bundle: dict, token: str):
    key = LEVEL_KEY.get(token)
    if not key:
        return None
    val = bundle.get(key)
    return float(val) if val is not None else None


def expected_grid() -> list:
    """Expected 5-minute bar timestamps for a complete session (09:15..15:25)."""
    out = []
    t = datetime.datetime(2000, 1, 1, 9, 15)
    end = datetime.datetime(2000, 1, 1, 15, 25)
    while t <= end:
        out.append(t.strftime('%H:%M'))
        t += datetime.timedelta(minutes=5)
    return out


def data_quality(conn, instruments, date_start: str, date_end: str) -> dict:
    """Candle-level quality report. Detects problems; never repairs them."""
    from app.market import nse_calendar
    grid = expected_grid()
    report = {'range': [date_start, date_end], 'instruments': {}}
    tz_offsets = set()
    for inst in instruments:
        days = sessions(conn, inst, date_start, date_end)
        per_day = {}
        for d in days:
            rows = conn.execute(
                'SELECT timestamp,open,high,low,close,volume FROM market_candles_5m '
                'WHERE instrument_id=? AND substr(timestamp,1,10)=? ORDER BY timestamp',
                (inst, d)).fetchall()
            times = [r['timestamp'][11:16] for r in rows]
            bad_ohlc = 0
            for r in rows:
                o, h, l, c = (float(r['open']), float(r['high']),
                              float(r['low']), float(r['close']))
                if h < l or h < max(o, c) or l > min(o, c) or o > h or c > h:
                    bad_ohlc += 1
            per_day[d] = {
                'bars': len(rows),
                'times': times,
                'bad_ohlc': bad_ohlc,
                'missing_slots': [t for t in grid if t not in set(times)],
                'first': times[0] if times else None,
                'last': times[-1] if times else None,
            }
        dup = conn.execute(
            'SELECT COUNT(*) FROM (SELECT instrument_id,timestamp,COUNT(*) n '
            'FROM market_candles_5m WHERE instrument_id=? AND '
            'substr(timestamp,1,10) BETWEEN ? AND ? GROUP BY 1,2 HAVING n>1)',
            (inst, date_start, date_end)).fetchone()[0]
        offsets = [r[0] for r in conn.execute(
            'SELECT DISTINCT substr(timestamp,20) FROM market_candles_5m '
            'WHERE instrument_id=? AND substr(timestamp,1,10) BETWEEN ? AND ?',
            (inst, date_start, date_end)).fetchall()]
        tz_offsets.update(str(o) for o in offsets)
        short = {d: v['bars'] for d, v in per_day.items() if v['bars'] != BARS_PER_SESSION}
        bad = {d: v['bad_ohlc'] for d, v in per_day.items() if v['bad_ohlc']}
        missing = {d: v['missing_slots'] for d, v in per_day.items() if v['missing_slots']}
        weekend = [d for d in days if nse_calendar.is_weekend(datetime.date.fromisoformat(d))]
        non_session = [d for d in days
                       if not nse_calendar.is_session_day(datetime.date.fromisoformat(d))]
        report['instruments'][inst] = {
            'sessions': len(days),
            'first_session': days[0] if days else None,
            'last_session': days[-1] if days else None,
            'bars_total': sum(v['bars'] for v in per_day.values()),
            'duplicate_timestamps': dup,
            'timezone_offsets': sorted(offsets),
            'short_sessions': short,
            'sessions_with_missing_bars': missing,
            'ohlc_violations': bad,
            'data_on_weekend_days': weekend,
            'data_on_non_session_days': non_session,
            'complete_sessions': sum(1 for v in per_day.values()
                                     if v['bars'] == BARS_PER_SESSION
                                     and not v['missing_slots']),
        }
    report['timezone_offsets_all'] = sorted(tz_offsets)
    report['expected_bars_per_session'] = BARS_PER_SESSION
    problems = []
    for inst, blob in report['instruments'].items():
        if blob['duplicate_timestamps']:
            problems.append(f'{inst}: duplicate timestamps')
        if blob['ohlc_violations']:
            problems.append(f'{inst}: OHLC violations')
        if blob['data_on_weekend_days'] or blob['data_on_non_session_days']:
            problems.append(f'{inst}: data on non-session days')
        if len(set(blob['timezone_offsets'])) > 1:
            problems.append(f'{inst}: mixed timezone offsets')
    report['problems'] = problems
    report['status'] = 'PASS' if not problems else 'PASS_WITH_LIMITATIONS'
    return report


def period_of(day_iso: str, splits: dict) -> str:
    for name in ('in_sample', 'validation', 'out_of_sample'):
        a, b = splits[name]
        if a <= day_iso <= b:
            return {'in_sample': 'IS', 'validation': 'VAL',
                    'out_of_sample': 'OOS'}[name]
    return 'OUT_OF_RANGE'


def median_range(candles_list: list, upto_ts: str) -> float:
    """Median intrabar range over candles up to and including `upto_ts` (PIT)."""
    vals = []
    for c in candles_list:
        if str(c['timestamp'])[:16] <= upto_ts:
            vals.append(float(c['high']) - float(c['low']))
    if not vals:
        return 0.0
    return float(statistics.median(vals))
