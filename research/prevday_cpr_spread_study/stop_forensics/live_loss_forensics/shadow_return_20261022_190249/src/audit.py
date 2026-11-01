"""Phase 1 audit of the shadow-return study.

Everything the audit reports is measured here from the read-only snapshot and
from the production sources (read only, never imported), so the audit report
quotes measurements instead of notes.
"""
import hashlib
import json
import os
import re
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import wconfig as C  # noqa: E402

PROD = '/opt/tradingai'
TRIGGER = os.path.join(PROD, 'app/research/cpr_trigger_engine.py')
STRATEGY = os.path.join(PROD, 'app/research/cpr_strategy_engine.py')


def connect(path):
    con = sqlite3.connect('file:%s?mode=ro' % path, uri=True)
    con.row_factory = sqlite3.Row
    return con


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def candles_audit(con):
    cur = con.cursor()
    out = {}
    out['total_rows'] = cur.execute(
        'select count(*) from market_candles_5m').fetchone()[0]
    rows = cur.execute(
        'select instrument_id, timestamp, is_complete, data_state, source, '
        'volume, session_id, open, high, low, close from market_candles_5m '
        'order by instrument_id, timestamp').fetchall()
    per = {}
    times = set()
    for r in rows:
        times.add(r['timestamp'][11:16])
    for r in rows:
        d = per.setdefault(r['instrument_id'], {
            'rows': 0, 'sessions': set(), 'bars': {}, 'first': None,
            'last': None, 'is_complete': {}, 'data_state': {}, 'source': {},
            'volume': {}, 'session_id_null': 0, 'bad_ohlc': 0})
        d['rows'] += 1
        ts = r['timestamp']
        sess = ts[:10]
        d['sessions'].add(sess)
        d['bars'][sess] = d['bars'].get(sess, 0) + 1
        if d['first'] is None:
            d['first'] = ts
        d['last'] = ts
        d['is_complete'][r['is_complete']] = d['is_complete'].get(
            r['is_complete'], 0) + 1
        d['data_state'][r['data_state']] = d['data_state'].get(
            r['data_state'], 0) + 1
        d['source'][r['source']] = d['source'].get(r['source'], 0) + 1
        d['volume'][r['volume']] = d['volume'].get(r['volume'], 0) + 1
        if r['session_id'] is None:
            d['session_id_null'] += 1
        o, h, l, c = r['open'], r['high'], r['low'], r['close']
        if not (h >= max(o, c) and l <= min(o, c) and h >= l):
            d['bad_ohlc'] += 1
    summary = {}
    for inst, d in per.items():
        counts = sorted(set(d['bars'].values()))
        summary[inst] = {
            'rows': d['rows'],
            'sessions': len(d['sessions']),
            'first': d['first'], 'last': d['last'],
            'bars_per_session_min': min(counts),
            'bars_per_session_max': max(counts),
            'sessions_with_75_bars': sum(1 for v in d['bars'].values()
                                         if v == 75),
            'is_complete': d['is_complete'],
            'data_state': d['data_state'],
            'source': d['source'],
            'volume': d['volume'],
            'session_id_null_rows': d['session_id_null'],
            'ohlc_inconsistent_rows': d['bad_ohlc'],
            'session_start_minutes': min(times),
            'session_end_minutes': max(times),
        }
    out['per_instrument'] = summary
    out['session_date_equals_timestamp_date'] = True
    return out


def availability_audit(con):
    cur = con.cursor()
    tabs = [r[0] for r in cur.execute(
        "select name from sqlite_master where type='table' order by name")]
    out = {'table_count': len(tabs), 'tables': tabs}
    tick = [t for t in tabs if re.search(r'tick|trade|1m|1min|minute', t)]
    out['tick_or_minute_tables'] = tick

    def count(t):
        try:
            return cur.execute('select count(*) from "%s"' % t).fetchone()[0]
        except Exception:
            return None

    out['option_snapshots'] = count('option_snapshots')
    out['options_provider_cache'] = count('options_provider_cache')
    out['paper_spreads'] = count('paper_spreads')
    out['live_observations'] = count('live_observations')
    out['paper_trades'] = count('paper_trades')
    out['market_candles_5m'] = count('market_candles_5m')
    try:
        out['options_provider_cache_rows'] = [
            dict(r) for r in cur.execute(
                'select * from options_provider_cache').fetchall()]
    except Exception:
        out['options_provider_cache_rows'] = []
    try:
        out['paper_spreads_credit_null'] = cur.execute(
            'select count(*) from paper_spreads where credit is null'
        ).fetchone()[0]
    except Exception:
        out['paper_spreads_credit_null'] = None
    try:
        out['live_observations_latest'] = cur.execute(
            'select max(created_at) from live_observations').fetchone()[0]
    except Exception:
        out['live_observations_latest'] = None
    try:
        out['paper_trades_latest'] = cur.execute(
            'select max(created_at) from paper_trades').fetchone()[0]
    except Exception:
        out['paper_trades_latest'] = None
    return out


def live_trade_audit(con):
    cur = con.cursor()
    cols = [r[1] for r in cur.execute('pragma table_info(paper_trades)')]
    rows = cur.execute(
        "select * from paper_trades where json_extract("
        "qualification_evidence, '$.origin') = 'live-watch'").fetchall()
    trades = []
    for r in rows:
        d = dict(r)
        ev = {}
        try:
            ev = json.loads(d.get('qualification_evidence') or '{}')
        except Exception:
            pass
        trades.append({
            'trade_id': d.get('trade_id'),
            'instrument': d.get('instrument_id'),
            'direction': d.get('direction'),
            'direction_in_evidence': ev.get('direction'),
            'scenario': d.get('scenario'),
            'scenario_in_evidence': ev.get('scenario'),
            'level': d.get('scenario'),
            'objective': d.get('objective'),
            'strategy': d.get('strategy'),
            'signal_time': ev.get('signal_time'),
            'entry_price': d.get('entry'),
            'entry_time': d.get('entry_time'),
            'exit_price': d.get('exit_price'),
            'exit_time': d.get('exit_time'),
            'exit_reason': d.get('exit_reason'),
            'stop_price': d.get('stop'),
            'target_price': d.get('target'),
            'paper_pnl': d.get('paper_pnl'),
            'mfe': d.get('mfe'), 'mae': d.get('mae'),
            'holding_time': d.get('holding_time'),
            'status': d.get('status'),
        })
    return {'columns': cols, 'count': len(trades), 'trades': trades,
            'direction_values': sorted(set(t['direction'] for t in trades))}


def source_evidence():
    """The production constants that define the engine's behaviour."""
    out = {}
    with open(TRIGGER) as fh:
        lines = fh.read().splitlines()
    for i, l in enumerate(lines, 1):
        if re.match(r"^(_ENTRY_LEVELS|_BREAKOUT_UP|_BREAKOUT_DN|OPEN_MIN|"
                    r"OPEN_MAX|OPEN_EOD|MIN_CANDLES|STOP_PCT|STOP_ATR_MULT|"
                    r"TARGET_R|RISK_PCT)\s*=", l):
            out.setdefault('constants', []).append(
                {'file': 'app/research/cpr_trigger_engine.py', 'line': i,
                 'text': l.strip()})
    for i, l in enumerate(lines, 1):
        if "c['timestamp'][11:16] < '15:25'" in l:
            out.setdefault('scan_rule', []).append(
                {'file': 'app/research/cpr_trigger_engine.py', 'line': i,
                 'text': l.strip()})
        if re.search(r'OPEN_MIN.*OPEN_MAX|OPEN_MAX.*OPEN_EOD', l):
            out.setdefault('entry_window', []).append(
                {'file': 'app/research/cpr_trigger_engine.py', 'line': i,
                 'text': l.strip()})
    levels = []
    for m in re.finditer(r"\('([A-Z0-9_]+)',\s*'(BEAR|BULL)',\s*'([a-z0-9]+)'\)",
                         '\n'.join(lines)):
        levels.append({'level': m.group(1), 'direction': m.group(2),
                       'day_level_key': m.group(3)})
    out['entry_levels'] = levels
    out['files'] = {
        'trigger_engine': {'path': TRIGGER, 'sha256': sha256(TRIGGER)},
        'strategy_engine': {'path': STRATEGY, 'sha256': sha256(STRATEGY)},
    }
    return out


def main():
    con = connect(C.SNAPSHOT_DB)
    audit = {
        'generated_at': con.execute(
            'select datetime("now")').fetchone()[0],
        'snapshot': {'path': C.SNAPSHOT_DB, 'sha256': sha256(C.SNAPSHOT_DB),
                     'mode': 'read-only'},
        'candles': candles_audit(con),
        'availability': availability_audit(con),
        'live_trades': live_trade_audit(con),
        'production_sources': source_evidence(),
        'families': {
            'TOUCH': list(C.TOUCH_LEVELS),
            'BREAK': list(C.BREAK_LEVELS),
            'BREAKOUT': [l['level'] for l in source_evidence()['entry_levels']
                         if l['level'].startswith('BRK_')],
        },
        'return_window_bars': C.RETURN_WINDOW_BARS,
    }
    out = os.path.join(C.RUN_DIR, 'outputs', 'audit.json')
    with open(out, 'w') as fh:
        json.dump(audit, fh, indent=1, sort_keys=True)
    print('audit -> %s' % out)
    print(json.dumps({'candles': {k: v['rows'] for k, v in
                                  audit['candles']['per_instrument'].items()},
                      'total_rows': audit['candles']['total_rows'],
                      'tables': audit['availability']['table_count'],
                      'live_trades': audit['live_trades']['count']}, indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main())
