"""Phase 1: discover the source, audit the data, validate the levels."""
import hashlib
import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config as C  # noqa: E402
import levels as L  # noqa: E402

CANDIDATE_SOURCES = (
    '/opt/tradingai/.tmp/cpr_research/outputs/tradingai_snapshot.db',
    '/opt/tradingai/database/tradingai.db',
    '/opt/tradingai/research/cpr_reversal_breakout/outputs/tradingai_snapshot.db',
    '/opt/tradingai/research/prevday_cpr_spread_study/stop_forensics/'
    'live_loss_forensics/shadow_return_20261022_190249/snapshots/'
    'tradingai_snapshot.db',
    '/opt/tradingai/research/prevday_cpr_spread_study/stop_forensics/'
    'setup_first/run_20261022_151310/snapshots/tradingai_snapshot.db',
    '/opt/tradingai/backups/tradingai-20261018-1412-pre-remediation.db',
)


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def connect(path):
    con = sqlite3.connect('file:%s?mode=ro' % path, uri=True)
    con.row_factory = sqlite3.Row
    return con


def discover():
    out = []
    for p in CANDIDATE_SOURCES:
        rec = {'path': p, 'exists': os.path.exists(p)}
        if rec['exists']:
            rec['bytes'] = os.path.getsize(p)
            try:
                con = connect(p)
                tabs = [r[0] for r in con.execute(
                    "select name from sqlite_master where type='table'")]
                rec['table_count'] = len(tabs)
                if 'market_candles_5m' in tabs:
                    rec['candle_rows'] = con.execute(
                        'select count(*) from market_candles_5m').fetchone()[0]
                    rec['per_instrument'] = {
                        r['instrument_id']: {
                            'rows': r['n'], 'first': r['mn'], 'last': r['mx']}
                        for r in con.execute(
                            'select instrument_id, count(*) n, min(timestamp) mn,'
                            ' max(timestamp) mx from market_candles_5m'
                            ' group by instrument_id')}
                con.close()
            except Exception as exc:
                rec['error'] = str(exc)
        out.append(rec)
    return out


def candle_audit(db):
    con = connect(db)
    cur = con.cursor()
    out = {}
    out['schema'] = [
        {'name': r['name'], 'type': r['type'], 'notnull': r['notnull'],
         'pk': r['pk']}
        for r in cur.execute('pragma table_info(market_candles_5m)')]
    out['indexes'] = [r[0] for r in cur.execute(
        "select name from sqlite_master where type='index' and tbl_name="
        "'market_candles_5m'")]
    out['total_rows'] = cur.execute(
        'select count(*) from market_candles_5m').fetchone()[0]

    instruments = {}
    for inst in C.INSTRUMENTS:
        rows = cur.execute(
            'select timestamp, open, high, low, close, volume, source, '
            'data_state, is_complete, session_id from market_candles_5m '
            'where instrument_id=? order by timestamp', (inst,)).fetchall()
        sessions = {}
        dups = []
        seen = set()
        bad_ohlc = []
        nonpositive = 0
        tz = set()
        for r in rows:
            ts = r['timestamp']
            if ts in seen:
                dups.append(ts)
            seen.add(ts)
            tz.add(ts[-6:] if len(ts) > 19 else ts)
            d = sessions.setdefault(ts[:10], [])
            d.append(r)
            o, h, l, c = r['open'], r['high'], r['low'], r['close']
            if not (h >= max(o, c) and l <= min(o, c) and h >= l):
                bad_ohlc.append(ts)
            if min(o, h, l, c) <= 0:
                nonpositive += 1
        sess_detail = {}
        for day, bars in sorted(sessions.items()):
            times = [b['timestamp'][11:16] for b in bars]
            sess_detail[day] = {
                'bars': len(bars),
                'first': times[0],
                'last': times[-1],
                'open': bars[0]['open'],
                'high': max(b['high'] for b in bars),
                'low': min(b['low'] for b in bars),
                'close': bars[-1]['close'],
                'sources': sorted(set(b['source'] for b in bars)),
                'data_states': sorted(set(b['data_state'] for b in bars)),
                'is_complete_all': all(b['is_complete'] == 1 for b in bars),
                'session_id_null': all(b['session_id'] is None
                                       for b in bars),
                'volume_all_zero': all((b['volume'] or 0) == 0 for b in bars),
            }
        counts = sorted(set(v['bars'] for v in sess_detail.values()))
        sess_times = {d: [b['timestamp'][11:16] for b in bars]
                      for d, bars in sessions.items()}

        def missing_bars(day, _times=sess_times):
            have = set(_times.get(day, []))
            grid = []
            t = datetime(2020, 1, 1, 9, 15)
            end = datetime(2020, 1, 1, 15, 25)
            while t <= end:
                grid.append(t.strftime('%H:%M'))
                t += timedelta(minutes=5)
            return [g for g in grid if g not in have]
        instruments[inst] = {
            'rows': len(rows),
            'sessions': len(sess_detail),
            'first_session': min(sess_detail) if sess_detail else None,
            'last_session': max(sess_detail) if sess_detail else None,
            'duplicate_timestamps': len(dups),
            'duplicate_examples': dups[:5],
            'ohlc_inconsistent_bars': len(bad_ohlc),
            'nonpositive_price_bars': nonpositive,
            'utc_offsets': sorted(tz),
            'bars_per_session_min': min(counts),
            'bars_per_session_max': max(counts),
            'sessions_with_full_75': sum(1 for v in sess_detail.values()
                                         if v['bars'] == 75),
            'incomplete_sessions': {d: {'bars': v['bars'],
                                        'first': v['first'],
                                        'last': v['last'],
                                        'missing_bars': missing_bars(d)}
                                    for d, v in sess_detail.items()
                                    if v['bars'] != 75},
            'session_detail': sess_detail,
        }
    out['instruments'] = instruments

    # calendar gaps between sessions (candidate holidays)
    all_days = set()
    for inst in C.INSTRUMENTS:
        all_days |= set(instruments[inst]['session_detail'])
    days = sorted(all_days)
    gaps = []
    for a, b in zip(days, days[1:]):
        da = datetime.strptime(a, '%Y-%m-%d')
        db = datetime.strptime(b, '%Y-%m-%d')
        missing = []
        dcur = da + timedelta(days=1)
        while dcur < db:
            if dcur.weekday() < 5:
                missing.append(dcur.strftime('%Y-%m-%d'))
            dcur += timedelta(days=1)
        gaps.append({'from': a, 'to': b, 'weekdays_without_data': missing})
    out['calendar_gaps'] = [g for g in gaps if g['weekdays_without_data']]

    # instruments present that are out of scope
    out['other_instruments'] = [
        dict(r) for r in cur.execute(
            'select instrument_id, count(*) n from market_candles_5m '
            'where instrument_id not in (?,?) group by instrument_id',
            C.INSTRUMENTS)]
    con.close()
    return out


def level_validation(db):
    """Recompute the levels for every session and compare with production."""
    con = connect(db)
    cur = con.cursor()
    ns = L.production_levels()
    rows = cur.execute(
        'select instrument_id, substr(timestamp,1,10) d, max(high) h, '
        'min(low) l from market_candles_5m where instrument_id in (?,?) '
        'group by instrument_id, d order by instrument_id, d', C.INSTRUMENTS
    ).fetchall()
    closes = {}
    for r in cur.execute(
            'select instrument_id, substr(timestamp,1,10) d, close, timestamp '
            'from market_candles_5m where instrument_id in (?,?) '
            'order by instrument_id, d, timestamp', C.INSTRUMENTS):
        closes.setdefault((r['instrument_id'], r['d']), []).append(r['close'])
    sessions = {}
    for r in rows:
        sessions.setdefault(r['instrument_id'], []).append(r['d'])

    out = {'sessions_checked': 0, 'levels_compared': 0,
           'material_mismatches': [], 'within_production_rounding': 0,
           'max_abs_diff': 0.0,
           'rounding_note': 'production calculate_cpr rounds pp/tc/bc to 4 '
                            'decimals and derives r1/s1/r2/s2 from the ROUNDED '
                            'pp; the study recomputes the exact values, so the '
                            'difference is a pure rounding artefact',
           'first_session_has_no_previous': [], 'production_definition': {
               'day_levels': 'app/research/cpr_trigger_engine.py:236',
               'calculate_cpr': 'app/research/cpr_strategy_engine.py:33',
               'pivot_levels': 'app/research/cpr_strategy_engine.py:41',
               'prev_session_ohlc': 'app/research/cpr_trigger_engine.py:383',
               'r3_s3_available': False}}
    for inst, days in sessions.items():
        for i, day in enumerate(days):
            if i == 0:
                out['first_session_has_no_previous'].append(
                    {'instrument': inst, 'date': day})
                continue
            prev = days[i - 1]
            cl = closes.get((inst, prev))
            if not cl:
                continue
            out['sessions_checked'] += 1
            # production day_levels(prev_high, prev_low, prev_close)
            ph = cur.execute(
                'select max(high) from market_candles_5m where '
                'instrument_id=? and substr(timestamp,1,10)=?',
                (inst, prev)).fetchone()[0]
            pl = cur.execute(
                'select min(low) from market_candles_5m where '
                'instrument_id=? and substr(timestamp,1,10)=?',
                (inst, prev)).fetchone()[0]
            pc = cl[-1]
            prod = ns['day_levels'](float(ph), float(pl), float(pc))
            mine = L.levels_from_prev(float(ph), float(pl), float(pc))
            for k in L.LEVEL_NAMES:
                pk = 'prev_close' if k == 'pdc' else k
                out['levels_compared'] += 1
                diff = abs(float(prod[pk]) - mine[k])
                out['max_abs_diff'] = max(out.get('max_abs_diff', 0.0), diff)
                if diff > 1e-6:
                    if diff <= 1e-2:
                        out['within_production_rounding'] = out.get(
                            'within_production_rounding', 0) + 1
                    else:
                        out['material_mismatches'].append({
                            'instrument': inst, 'date': day,
                            'prev_session': prev, 'level': k,
                            'study': mine[k], 'production': prod[pk],
                            'abs_diff': diff})
    con.close()
    return out


def main():
    audit = {
        'generated_at': datetime.now().astimezone().isoformat(),
        'run_dir': C.RUN_DIR,
        'source_discovery': discover(),
        'authoritative_source': {
            'path': C.SOURCE_DB,
            'reason': 'the live production database; it holds the complete '
                      'market_candles_5m history for NIFTY and BANKNIFTY '
                      '(2026-07-06 .. 2026-10-22). The path named in the task '
                      '(.tmp/cpr_research/outputs/tradingai_snapshot.db) does '
                      'not exist on this host; the surviving research '
                      'snapshots are older copies of the same database.',
            'sha256_db': sha256(C.SOURCE_DB),
            'sha256_wal': sha256(C.SOURCE_WAL) if os.path.exists(C.SOURCE_WAL)
            else None,
            'read_only': True,
        },
        'research_copy': {
            'path': C.RESEARCH_DB,
            'sha256': sha256(C.RESEARCH_DB),
            'created_with': 'sqlite3 backup API from a mode=ro connection',
            'bytes': os.path.getsize(C.RESEARCH_DB),
        },
        'candles': candle_audit(C.RESEARCH_DB),
        'level_validation': level_validation(C.RESEARCH_DB),
    }
    out = os.path.join(C.RUN_DIR, 'outputs', 'data_audit.json')
    with open(out, 'w') as fh:
        json.dump(audit, fh, indent=1, sort_keys=True)
    print('audit -> %s' % out)
    for inst, d in audit['candles']['instruments'].items():
        print('  %-11s rows=%d sessions=%d %s..%s bars=%d-%d dups=%d '
              'bad_ohlc=%d' % (inst, d['rows'], d['sessions'],
                               d['first_session'], d['last_session'],
                               d['bars_per_session_min'],
                               d['bars_per_session_max'],
                               d['duplicate_timestamps'],
                               d['ohlc_inconsistent_bars']))
    lv = audit['level_validation']
    print('  levels: %d sessions checked, %d comparisons, material mismatches '
          '%d, max abs diff %.6g pts'
          % (lv['sessions_checked'], lv['levels_compared'],
             len(lv['material_mismatches']), lv['max_abs_diff']))
    print('  calendar gaps: %d' % len(audit['candles']['calendar_gaps']))
    return 0


if __name__ == '__main__':
    sys.exit(main())
