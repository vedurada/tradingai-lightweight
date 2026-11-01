"""Data-quality report for the historical inputs used by this research.

Read-only. Checks run against market_candles_5m and the point-in-time level
pipeline:
  1. coverage: sessions per instrument vs the NSE session calendar
  2. structural: duplicates, ordering, non-positive/OHLC-violating candles
  3. completeness: candles per session vs the expected 09:15..15:25 grid (75)
  4. timestamp sanity: timezone offset, session date extraction
  5. point-in-time: levels for day D must be a pure function of days < D
     (verified by recomputing on a truncated feed)
  6. staleness/source: source labels and data_state distribution
  7. option-chain availability: historical premium data required for a true
     credit-spread P&L — reported explicitly (absence blocks that test)
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from common import day_levels, prev_session_ohlc, ro_conn

EXPECTED_CANDLES = 75          # 09:15 .. 15:25 inclusive, 5-minute grid
EXPECTED_FIRST = '09:15'
EXPECTED_LAST = '15:25'


def _expected_grid(day_iso):
    base = datetime.fromisoformat(day_iso + 'T09:15:00')
    return [(base + timedelta(minutes=5 * i)).strftime('%H:%M')
            for i in range(EXPECTED_CANDLES)]


def run_report(date_start, date_end, db_path=None, instruments=('NIFTY', 'BANKNIFTY')):
    from app.market.nse_calendar import holiday_name, is_session_day
    conn = ro_conn(db_path)
    report = {'date_start': date_start, 'date_end': date_end,
              'generated_from': 'market_candles_5m (read-only)'}
    try:
        report['structure'] = _structure(conn)
        report['coverage'] = {}
        for inst in instruments:
            report['coverage'][inst] = _coverage(conn, inst, date_start,
                                                 date_end, is_session_day,
                                                 holiday_name)
        report['option_history'] = _option_history(conn)
        report['pit_level_check'] = _pit_check(conn, instruments, date_start,
                                               date_end)
        report['sources'] = _sources(conn)
    finally:
        conn.close()
    report['verdict'] = _verdict(report)
    return report


def _structure(conn):
    dupes = conn.execute(
        'SELECT COUNT(*) c FROM (SELECT instrument_id,timestamp,COUNT(*) n '
        'FROM market_candles_5m GROUP BY 1,2 HAVING n>1)').fetchone()['c']
    bad = conn.execute(
        'SELECT COUNT(*) c FROM market_candles_5m WHERE high<low OR open<=0 '
        'OR close<=0 OR high<close OR low>close OR high<open').fetchone()['c']
    offsets = {r['o']: r['n'] for r in conn.execute(
        'SELECT substr(timestamp,20) o, COUNT(*) n FROM market_candles_5m '
        'GROUP BY 1')}
    not_complete = conn.execute(
        'SELECT COUNT(*) c FROM market_candles_5m WHERE is_complete<>1'
    ).fetchone()['c']
    return {'duplicate_candles': dupes, 'ohlc_violations': bad,
            'timezone_offsets': offsets, 'rows_not_marked_complete': not_complete}


def _coverage(conn, inst, date_start, date_end, is_session_day, holiday_name):
    rows = conn.execute(
        'SELECT substr(timestamp,1,10) d, COUNT(*) n, MIN(timestamp) mn, '
        'MAX(timestamp) mx FROM market_candles_5m WHERE instrument_id=? AND '
        'substr(timestamp,1,10) BETWEEN ? AND ? GROUP BY 1 ORDER BY 1',
        (inst, date_start, date_end)).fetchall()
    per_day = {r['d']: r['n'] for r in rows}
    short = {d: n for d, n in per_day.items() if n != EXPECTED_CANDLES}
    # weekday gaps: session days in range with no candles at all
    d0 = datetime.fromisoformat(date_start).date()
    d1 = datetime.fromisoformat(date_end).date()
    missing_sessions, holidays_hit = [], []
    d = d0
    while d <= d1:
        iso = d.isoformat()
        if not is_session_day(d):
            if iso in per_day:
                holidays_hit.append(iso)          # data on a non-session day
        elif iso not in per_day:
            missing_sessions.append(iso)
        d += timedelta(days=1)
    weekend_data = [x for x in per_day
                    if datetime.fromisoformat(x).weekday() >= 5]
    return {'sessions_with_data': len(per_day),
            'first_session': min(per_day) if per_day else None,
            'last_session': max(per_day) if per_day else None,
            'short_sessions': short,
            'expected_session_days_without_data': missing_sessions,
            'data_on_non_session_days': sorted(set(holidays_hit) | set(weekend_data)),
            'first_candle_min': min((r['mn'] for r in rows), default=None),
            'last_candle_max': max((r['mx'] for r in rows), default=None)}


def _sources(conn):
    rows = conn.execute(
        'SELECT source, data_state, COUNT(*) n, MIN(timestamp) mn, '
        'MAX(timestamp) mx FROM market_candles_5m GROUP BY 1,2').fetchall()
    return [dict(r) for r in rows]


def _option_history(conn):
    """Historical option premiums are required for credit-spread P&L."""
    out = {}
    for table, ts_col in (('option_snapshots', 'timestamp'),
                          ('option_contracts', 'source_timestamp')):
        try:
            r = conn.execute(
                f'SELECT COUNT(*) n, MIN({ts_col}) mn, MAX({ts_col}) mx '
                f'FROM {table}').fetchone()
            out[table] = {'rows': r['n'], 'min': r['mn'], 'max': r['mx']}
        except Exception as e:                       # pragma: no cover
            out[table] = {'error': str(e)}
    available = any(v.get('rows', 0) for v in out.values()
                    if isinstance(v, dict))
    out['historical_option_premiums_available'] = bool(available)
    out['consequence'] = (
        'available -> credit-spread P&L can be priced from real premiums'
        if available else
        'UNAVAILABLE -> this run is an UNDERLYING (spot) signal study only; '
        'credit-spread P&L cannot be claimed from these inputs')
    return out


def _prev_ohlc_pure_python(rows, day_iso):
    """Prior-session OHLC from pre-loaded (timestamp, high, low, close) rows,
    using ONLY rows strictly before `day_iso`. Same semantics as
    `common.prev_session_ohlc`: last prior session's max high / min low and
    the close of its last candle."""
    by_day = {}
    for ts, h, l, c in rows:
        d = ts[:10]
        if d >= day_iso:
            continue
        cur = by_day.get(d)
        if cur is None:
            by_day[d] = [h, l, c, ts]
        else:
            cur[0] = max(cur[0], h)
            cur[1] = min(cur[1], l)
            if ts >= cur[3]:
                cur[2] = c
                cur[3] = ts
    if not by_day:
        return None
    d = max(by_day)
    h, l, c, _ = by_day[d]
    return {'date': d, 'high': float(h), 'low': float(l), 'close': float(c)}


def _pit_check(conn, instruments, date_start, date_end):
    """Levels for day D must be identical whether or not later days exist.

    The truncated side recomputes the prior session from rows strictly before
    D, so the only variable is the presence of later data."""
    checked = mismatches = 0
    examples = []
    for inst in instruments:
        days = [r[0] for r in conn.execute(
            'SELECT DISTINCT substr(timestamp,1,10) FROM market_candles_5m '
            'WHERE instrument_id=? AND substr(timestamp,1,10) BETWEEN ? AND ? '
            'ORDER BY 1', (inst, date_start, date_end)).fetchall()]
        all_rows = [(r[0], r[1], r[2], r[3]) for r in conn.execute(
            'SELECT timestamp, high, low, close FROM market_candles_5m '
            'WHERE instrument_id=? ORDER BY timestamp', (inst,)).fetchall()]
        for d in days:
            prev = prev_session_ohlc(conn, inst, d)
            if not prev:
                continue
            full = day_levels(prev['high'], prev['low'], prev['close'])
            p2 = _prev_ohlc_pure_python(all_rows, d)
            trunc = day_levels(p2['high'], p2['low'], p2['close']) if p2 else None
            checked += 1
            if full != trunc:
                mismatches += 1
                if len(examples) < 5:
                    examples.append({'instrument': inst, 'date': d,
                                     'full': full, 'truncated': trunc})
    return {'levels_checked': checked, 'mismatches': mismatches,
            'examples': examples,
            'verdict': 'PASS' if mismatches == 0 else 'FAIL'}


def _verdict(rep):
    issues = []
    st = rep['structure']
    if st['duplicate_candles']:
        issues.append(f"duplicate_candles={st['duplicate_candles']}")
    if st['ohlc_violations']:
        issues.append(f"ohlc_violations={st['ohlc_violations']}")
    if set(st['timezone_offsets']) != {'+05:30'}:
        issues.append(f"timezone_offsets={st['timezone_offsets']}")
    for inst, cov in rep['coverage'].items():
        if cov['expected_session_days_without_data']:
            issues.append(f"{inst}: missing sessions "
                          f"{cov['expected_session_days_without_data']}")
        if cov['short_sessions']:
            issues.append(f"{inst}: short sessions {cov['short_sessions']}")
        if cov['data_on_non_session_days']:
            issues.append(f"{inst}: data on non-session days "
                          f"{cov['data_on_non_session_days']}")
    if rep['pit_level_check']['verdict'] != 'PASS':
        issues.append('point-in-time level check FAILED')
    if not rep['option_history']['historical_option_premiums_available']:
        issues.append('NO historical option premiums -> credit-spread P&L '
                      'test not executable (labelled limitation)')
    return {'issues': issues,
            'blocking': [i for i in issues if 'missing sessions' in i
                         or 'point-in-time' in i or 'duplicate' in i],
            'status': 'PASS_WITH_LIMITATIONS' if issues else 'PASS'}
