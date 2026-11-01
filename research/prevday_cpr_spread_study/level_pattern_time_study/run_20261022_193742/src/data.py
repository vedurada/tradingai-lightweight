"""Session assembly: bars, previous session, levels, tolerance variants."""
import os
import sqlite3
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config as C  # noqa: E402
import levels as L  # noqa: E402


def connect(db):
    con = sqlite3.connect('file:%s?mode=ro' % db, uri=True)
    con.row_factory = sqlite3.Row
    return con


def load_sessions(db=None):
    """{instrument: {date: session_dict}} with previous-session levels."""
    db = db or C.RESEARCH_DB
    con = connect(db)
    raw = {inst: {} for inst in C.INSTRUMENTS}
    for r in con.execute(
            'select instrument_id, timestamp, open, high, low, close from '
            'market_candles_5m where instrument_id in (?,?) '
            'order by instrument_id, timestamp', C.INSTRUMENTS):
        ts = r['timestamp']
        bars = raw[r['instrument_id']].setdefault(ts[:10], [])
        bars.append({'ts': ts, 't': ts[11:16], 'o': float(r['open']),
                     'h': float(r['high']), 'l': float(r['low']),
                     'c': float(r['close'])})
    con.close()

    sessions = {inst: {} for inst in C.INSTRUMENTS}
    for inst in C.INSTRUMENTS:
        days = sorted(raw[inst])
        for i, day in enumerate(days):
            bars = raw[inst][day]
            sess = {'date': day, 'instrument': inst, 'bars': bars,
                    'prev': None, 'levels': None, 'tol': {}}
            if i > 0:
                pb = raw[inst][days[i - 1]]
                prev = {'date': days[i - 1],
                        'high': max(b['h'] for b in pb),
                        'low': min(b['l'] for b in pb),
                        'close': pb[-1]['c']}
                sess['prev'] = prev
                sess['levels'] = L.levels_from_prev(
                    prev['high'], prev['low'], prev['close'])
                rng = prev['high'] - prev['low']
                mean_range = sum(b['h'] - b['l'] for b in pb) / float(len(pb))
                sess['prev_range'] = rng
                sess['prev_mean_bar_range'] = mean_range
                sess['tol']['fixed'] = C.TOL_FIXED_POINTS[inst]
                vt = C.TOL_VOL_MULT * mean_range
                vt = max(C.TOL_VOL_FLOOR, vt)
                if rng:
                    vt = min(vt, C.TOL_VOL_CAP_PCT * rng)
                sess['tol']['vol'] = round(vt, 4)
            sessions[inst][day] = sess
    return sessions


def prev_close_for(sessions, day):
    days = sorted(sessions)
    i = days.index(day)
    if i == 0:
        return None
    return sessions[days[i - 1]]['bars'][-1]['c']


def bar_time(sess, idx):
    if idx < 0 or idx >= len(sess['bars']):
        return None
    return sess['bars'][idx]['t']


def entry_eligible(t):
    """The production entry window: [09:20, 15:20)."""
    return C.ENTRY_WINDOW_OPEN <= t < C.ENTRY_WINDOW_CLOSE


def bucket_of(t):
    for name, lo, hi in C.TIME_BUCKETS:
        if lo <= t < hi:
            return name
    return None


def session_grid_missing(bars):
    have = set(b['t'] for b in bars)
    grid = []
    t = datetime(2020, 1, 1, 9, 15)
    end = datetime(2020, 1, 1, 15, 25)
    while t <= end:
        grid.append(t.strftime('%H:%M'))
        t += timedelta(minutes=5)
    return [g for g in grid if g not in have]
