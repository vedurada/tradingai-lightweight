"""Phase 4 - why did the opens-execution replay reproduce 0 of 6 live exits?

For every real live trade the study compares, field by field:
  * the recorded live entry (price, timestamp) with the stored 5-minute candle
    that contains it,
  * the recorded live exit (price, timestamp, reason) with the candle that
    contains the exit,
  * the opens-execution replay of the same trade with the recorded result.

Nothing is invented: no fill is assumed and no mismatch is forced. Where the
data cannot decide a question the field is reported as unavailable.
"""
import csv
import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import prodlib as P
import wconfig as C


def connect(path):
    con = sqlite3.connect('file:%s?mode=ro' % path, uri=True)
    con.row_factory = sqlite3.Row
    return con


def load_candles(con, inst):
    rows = con.execute(
        'SELECT timestamp,open,high,low,close FROM market_candles_5m '
        'WHERE instrument_id=? ORDER BY timestamp', (inst,)).fetchall()
    out = {}
    for r in rows:
        d = dict(r)
        out.setdefault(d['timestamp'][:10], []).append(d)
    return out


def parse_ts(ts):
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts))
    except (TypeError, ValueError):
        return None


def naive(ts):
    """A timestamp as naive local time (the stored values are all +05:30)."""
    t = parse_ts(ts)
    return t.replace(tzinfo=None) if t is not None else None


def bar_containing(bars, t):
    """The 5-minute bar whose [start, start+5min) window contains `t`."""
    if t is None:
        return None
    for b in bars:
        try:
            start = datetime.fromisoformat(b['timestamp'])
        except (TypeError, ValueError):
            continue
        if start <= t < start + timedelta(minutes=C.BAR_MINUTES):
            return b
    return None


def nearest_bar(bars, t):
    """The last bar that started at or before `t`."""
    if t is None:
        return None
    best = None
    for b in bars:
        try:
            start = datetime.fromisoformat(b['timestamp'])
        except (TypeError, ValueError):
            continue
        if start <= t:
            best = b
        else:
            break
    return best


def index_r(direction, entry, exit_px):
    try:
        risk = abs(float(entry) * C.OPEN_STOP_PCT)
        pts = ((float(exit_px) - float(entry)) if direction == 'BULL'
               else (float(entry) - float(exit_px)))
        return round(pts / risk, 3) if risk else None
    except (TypeError, ValueError):
        return None


def main():
    con = connect(C.SNAPSHOT_DB)
    out = {'generated_at': datetime.now().isoformat(timespec='seconds'),
           'snapshot': C.SNAPSHOT_DB, 'trades': [],
           'data_availability': {}, 'conclusions': {}}
    try:
        candles = {i: load_candles(con, i) for i in C.INSTRUMENTS}
        # what price data exists at all
        avail = {}
        for t in ('market_candles_5m', 'option_snapshots', 'options_provider_cache',
                  'paper_spreads', 'live_observations', 'qualified_trades'):
            try:
                n = con.execute('SELECT COUNT(*) FROM %s' % t).fetchone()[0]
            except sqlite3.Error as e:
                n = 'ERROR: %s' % e
            avail[t] = n
        cols = [r[1] for r in con.execute(
            'PRAGMA table_info(market_candles_5m)').fetchall()]
        avail['market_candles_5m_columns'] = ','.join(cols)
        avail['intraday_granularity_available'] = '5 minutes only (market_candles_5m)'
        avail['tick_series'] = 'ABSENT - no tick or 1-minute table in the database'
        avail['options_chain_state'] = 'OPTIONS_UNAVAILABLE (options_provider_cache)'
        out['data_availability'] = avail

        rows = con.execute('SELECT * FROM paper_trades').fetchall()
        for r in rows:
            rec = dict(r)
            try:
                ev = json.loads(rec['qualification_evidence'] or '{}')
            except (TypeError, ValueError):
                ev = {}
            if ev.get('origin') != 'live-watch':
                continue
            inst = rec['instrument_id']
            d_raw = str(rec['direction'] or '').upper()
            direction = ('BEAR' if d_raw in ('BEAR', 'BEARISH', 'SHORT') else 'BULL')
            day = str(ev.get('signal_time') or rec['entry_time'])[:10]
            sessions = candles.get(inst, {})
            sig_bars = sessions.get(day, [])

            t = {
                'trade_id': rec['trade_id'], 'instrument': inst,
                'direction': direction, 'scenario': ev.get('scenario'),
                'signal_time': ev.get('signal_time'),
                'recorded_entry': rec['entry'], 'recorded_entry_time': rec['entry_time'],
                'recorded_exit': rec['exit_price'], 'recorded_exit_time': rec['exit_time'],
                'recorded_exit_reason': rec['exit_reason'],
                'recorded_stop': rec['stop'], 'recorded_target': rec['target'],
                'recorded_paper_pnl': rec['paper_pnl'],
                'recorded_strategy': rec['strategy'],
            }
            t['index_r_recorded'] = index_r(direction, rec['entry'],
                                            rec['exit_price'])

            # ---- the entry: the live price vs the stored candle
            et = parse_ts(rec['entry_time'])
            eb = bar_containing(sig_bars, et) if et else None
            if eb:
                t['entry_bar'] = eb['timestamp']
                t['entry_bar_open'] = eb['open']
                t['entry_bar_close'] = eb['close']
                t['entry_price_minus_candle_open'] = round(rec['entry'] - eb['open'], 2)
                t['entry_price_inside_candle_range'] = bool(
                    eb['low'] <= rec['entry'] <= eb['high'])
                t['entry_fill_type'] = ('BAR_OPEN' if et and
                                        et == datetime.fromisoformat(eb['timestamp'])
                                        else 'INTRABAR')
            else:
                t['entry_bar'] = None
                t['entry_fill_type'] = 'NO_CANDLE_FOR_ENTRY_TIME'

            # ---- the exit: which bar, and is it reachable from the candle?
            xt = parse_ts(rec['exit_time'])
            xday = str(rec['exit_time'])[:10] if rec['exit_time'] else None
            xbars = sessions.get(xday, [])
            xb = bar_containing(xbars, xt) if xt else None
            if xb:
                t['exit_bar'] = xb['timestamp']
                t['exit_bar_open'] = xb['open']
                t['exit_bar_high'] = xb['high']
                t['exit_bar_low'] = xb['low']
                t['exit_bar_close'] = xb['close']
                t['exit_price_inside_exit_bar_range'] = bool(
                    xb['low'] <= rec['exit_price'] <= xb['high'])
                t['exit_fill_type'] = ('BAR_OPEN' if xt and
                                       xt == datetime.fromisoformat(xb['timestamp'])
                                       else 'INTRABAR')
                thr = rec['stop'] if rec['exit_reason'] == 'STOP' else rec['target']
                t['exit_threshold'] = thr
                if thr is not None:
                    t['threshold_inside_exit_bar_range'] = bool(
                        xb['low'] <= thr <= xb['high'])
                    t['fill_beyond_threshold_pts'] = round(
                        (rec['exit_price'] - thr) if direction == 'BEAR'
                        else (thr - rec['exit_price']), 2)
            else:
                t['exit_bar'] = None
                t['exit_fill_type'] = 'NO_CANDLE_FOR_EXIT_TIME'

            # ---- the exit mechanism
            mech = 'UNKNOWN'
            if rec['exit_reason'] == 'STOP':
                mech = 'INTRABAR_STOP' if t.get('exit_fill_type') == 'INTRABAR' \
                    else 'STOP_AT_BAR_OPEN'
            elif rec['exit_reason'] == 'TARGET':
                mech = 'INTRABAR_TARGET' if t.get('exit_fill_type') == 'INTRABAR' \
                    else 'TARGET_AT_BAR_OPEN'
            elif rec['exit_reason'] in ('EOD', 'TIME', 'EOD-1510', 'EOD-1520'):
                mech = 'TIME_EXIT'
            t['exit_mechanism'] = mech

            # ---- the opens-execution replay of the same trade
            trig = None
            if ev.get('signal_time'):
                st = str(ev['signal_time'])[:16].replace('T', ' ')
                trig = next((k for k, c in enumerate(sig_bars)
                             if c['timestamp'][:16].replace('T', ' ') == st), None)
            prev = None
            days = sorted(sessions)
            prior = [d for d in days if d < day]
            if prior:
                cs = sessions[prior[-1]]
                prev = {'high': max(float(c['high']) for c in cs),
                        'low': min(float(c['low']) for c in cs),
                        'close': float(cs[-1]['close'])}
            lv = P.day_levels(prev['high'], prev['low'], prev['close']) if prev else None
            replay = None
            if trig is not None and lv is not None and trig + 1 < len(sig_bars):
                nxt = sig_bars[trig + 1]
                if C.OPEN_MIN <= nxt['timestamp'][11:16] < C.OPEN_EOD:
                    replay = P.evaluate_outcome(direction, float(nxt['open']),
                                                trig + 1, sig_bars, inst)
            if replay:
                t['model_entry'] = replay['entry']
                t['model_entry_time'] = replay['entry_time']
                t['model_exit'] = replay['exit']
                t['model_exit_time'] = replay['exit_time']
                t['model_exit_reason'] = replay['exit_reason']
                t['model_r'] = replay['r_multiple']
                t['model_label'] = replay['win_loss']
                t['model_entry_diff_pts'] = round(replay['entry'] - rec['entry'], 2)
                t['reproduced'] = bool(replay['exit'] == rec['exit_price'] and
                                       replay['exit_reason'] == rec['exit_reason'])
                t['exit_event_reproduced'] = bool(
                    t['reproduced'] and
                    naive(replay['exit_time']) == naive(rec['exit_time']))
                t['exit_price_diff_pts'] = (round(replay['exit'] - rec['exit_price'], 2)
                                            if replay['exit'] is not None else None)
                t['exit_reason_match'] = (replay['exit_reason'] ==
                                          rec['exit_reason'])
                t['exit_time_diff_minutes'] = None
                if replay['exit_time'] and rec['exit_time']:
                    a = naive(replay['exit_time'])
                    b = naive(rec['exit_time'])
                    if a and b:
                        t['exit_time_diff_minutes'] = round((b - a).total_seconds() / 60.0, 1)
            else:
                t['reproduced'] = False
                t['exit_event_reproduced'] = False
                t['model_exit_reason'] = 'NO_REPLAY'
            out['trades'].append(t)
    finally:
        con.close()

    n = len(out['trades'])
    rep = sum(1 for t in out['trades'] if t.get('reproduced'))
    intrabar = sum(1 for t in out['trades']
                    if t.get('exit_fill_type') == 'INTRABAR')
    inside = sum(1 for t in out['trades']
                  if t.get('exit_price_inside_exit_bar_range'))
    thr_ok = sum(1 for t in out['trades']
                 if t.get('threshold_inside_exit_bar_range'))
    reason_match = sum(1 for t in out['trades'] if t.get('exit_reason_match'))
    out['conclusions'] = {
        'live_trades': n,
        'opens_model_reproduced': rep,
        'exit_events_reproduced': sum(1 for t in out['trades']
                                      if t.get('exit_event_reproduced')),
        'exit_timestamps_matched': sum(1 for t in out['trades']
                                       if t.get('exit_time_diff_minutes') == 0),
        'entry_price_diff_pts': [t.get('entry_price_minus_candle_open')
                                 for t in out['trades']],
        'intrabar_exits': intrabar,
        'exit_price_inside_the_stored_exit_bar': inside,
        'threshold_reachable_in_the_exit_bar': thr_ok,
        'exit_reason_matched': reason_match,
        'entry_fill_type_counts': {},
    }
    counts = {}
    for t in out['trades']:
        k = t.get('entry_fill_type')
        counts[k] = counts.get(k, 0) + 1
    out['conclusions']['entry_fill_type_counts'] = counts
    counts = {}
    for t in out['trades']:
        k = t.get('exit_mechanism')
        counts[k] = counts.get(k, 0) + 1
    out['conclusions']['exit_mechanism_counts'] = counts

    with open(os.path.join(C.OUT_DIR, 'execution_gap.json'), 'w') as fh:
        json.dump(out, fh, indent=2, sort_keys=True, default=str)

    fields = ['trade_id', 'instrument', 'direction', 'scenario', 'signal_time',
              'recorded_entry', 'recorded_entry_time', 'entry_bar',
              'entry_bar_open', 'entry_price_minus_candle_open',
              'entry_price_inside_candle_range', 'entry_fill_type',
              'recorded_exit', 'recorded_exit_time', 'exit_bar',
              'exit_bar_open', 'exit_bar_high', 'exit_bar_low',
              'exit_price_inside_exit_bar_range', 'exit_fill_type',
              'recorded_exit_reason', 'exit_mechanism', 'exit_threshold',
              'threshold_inside_exit_bar_range', 'fill_beyond_threshold_pts',
              'model_entry', 'model_entry_time', 'model_exit', 'model_exit_time',
              'model_exit_reason', 'model_r', 'model_label', 'reproduced',
              'exit_event_reproduced',
              'exit_reason_match', 'exit_price_diff_pts', 'exit_time_diff_minutes',
              'index_r_recorded', 'recorded_paper_pnl', 'recorded_strategy']
    csv_path = os.path.join(C.OUT_DIR, 'execution_gap.csv')
    with open(csv_path, 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction='ignore')
        w.writeheader()
        for t in out['trades']:
            w.writerow(t)

    print('live trades:', n, '| reproduced by the opens model:', rep)
    for t in out['trades']:
        print('  %-16s %-9s rec=%s@%s model=%s@%s (%s) fill=%s inside_bar=%s' % (
            t['trade_id'], t['scenario'], t['recorded_exit'], t['recorded_exit_reason'],
            t.get('model_exit'), t.get('model_exit_reason'),
            t.get('exit_time_diff_minutes'), t.get('exit_fill_type'),
            t.get('exit_price_inside_exit_bar_range')))
    print('wrote', csv_path)
    return out


if __name__ == '__main__':
    main()
