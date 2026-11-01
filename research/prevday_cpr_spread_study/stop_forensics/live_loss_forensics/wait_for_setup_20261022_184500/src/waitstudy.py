"""Driver for the read-only 'wait for the setup' counterfactual study.

Reads only the sqlite snapshot of the live database (mode=ro) and writes only
into this study's own outputs/reports directories. No production table, file,
process or service is touched.
"""
import csv
import json
import os
import sqlite3
import statistics
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import prodlib as P
import variants as V
import wconfig as C


# ------------------------------------------------------------- data io -----
def connect(path):
    con = sqlite3.connect('file:%s?mode=ro' % path, uri=True)
    con.row_factory = sqlite3.Row
    return con


def load_candles(con, inst):
    rows = con.execute(
        'SELECT timestamp,open,high,low,close FROM market_candles_5m '
        'WHERE instrument_id=? ORDER BY timestamp', (inst,)).fetchall()
    return [dict(r) for r in rows]


def group_sessions(candles):
    out = {}
    for c in candles:
        out.setdefault(c['timestamp'][:10], []).append(c)
    return out


def prev_session_ohlc(sessions, day):
    """Max high / min low / last close of the last session before `day`."""
    days = sorted(sessions)
    prior = [d for d in days if d < day]
    if not prior:
        return None
    d = prior[-1]
    cs = sessions[d]
    try:
        return {'date': d,
                'high': max(float(c['high']) for c in cs),
                'low': min(float(c['low']) for c in cs),
                'close': float(cs[-1]['close'])}
    except (TypeError, ValueError):
        return None


# ------------------------------------------------------- signal replay -----
def replay_session(candles, lv):
    """Current production rules for one session. Returns (sig, skip_bucket).

    Mirrors run_opens_range(variant='plain'): SHORT_ONLY base scan (BEAR),
    SKIP_FRIDAY gate, entry window [09:20,15:20), breakout add-on fallback.
    """
    cs = [c for c in candles if c['timestamp'][11:16] < C.SIGNAL_CUTOFF]
    if len(cs) < C.MIN_CANDLES:
        return None, 'short_day'
    sig = None
    fri = False
    for i, c in enumerate(cs):
        b = P.bear_trigger(c, lv)
        if not b:
            continue
        dr = 'BEAR'
        if P.friday_skip(dr, c['timestamp'][:10]):
            fri = True
            break
        if i + 1 >= len(cs):
            continue
        nt = cs[i + 1]['timestamp'][11:16]
        if not (C.OPEN_MIN <= nt < C.OPEN_EOD):
            continue
        sig = (dr, b, i)
        break
    if not sig and C.BREAKOUT_ADDON:
        bs = P.breakout_signal(cs, lv)
        if bs is not None and not P.friday_skip(bs[0], cs[0]['timestamp'][:10]):
            sig = bs
    if not sig:
        return None, ('skip_friday' if fri else 'no_signal')
    return sig, None


# --------------------------------------------------------- evaluation ------
def evaluate_signal(book, inst, day, direction, level, i, candles, lv, extra=None):
    """Run every variant on one signal. Returns a list of per-variant dicts."""
    rows = []
    base = None
    for name in C.VARIANT_ORDER:
        if name == 'V0_BASELINE':
            idx = i + 1
            if idx >= len(candles):
                rows.append(_row(book, inst, day, direction, level, i, name,
                                 'NO_ENTRY_BAR', None))
                continue
            if not (C.OPEN_MIN <= candles[idx]['timestamp'][11:16] < C.OPEN_EOD):
                rows.append(_row(book, inst, day, direction, level, i, name,
                                 'CUTOFF', None))
                continue
            entry = float(candles[idx]['open'])
            got = {'status': 'ENTERED', 'entry_idx': idx, 'entry': entry,
                   'direction': direction, 'level': level, 'wait_bars': 0}
        else:
            got = V.VARIANT_FUNCS[name](candles, i, lv, direction, level)
        row = _row(book, inst, day, direction, level, i, name,
                   got['status'], got.get('wait_bars'))
        row.update({
            'variant_direction': got.get('direction'),
            'variant_level': got.get('level'),
            'level_price': P.level_price(level, lv),
        })
        if got['status'] == 'ENTERED':
            out = P.evaluate_outcome(got['direction'], got['entry'],
                                      got['entry_idx'], candles, inst)
            if out is None:
                row['status'] = 'MISSING_EOD'
            else:
                row.update({
                    'entry': out['entry'], 'entry_time': out['entry_time'],
                    'exit': out['exit'], 'exit_time': out['exit_time'],
                    'exit_reason': out['exit_reason'],
                    'r_multiple': out['r_multiple'], 'points': out['points'],
                    'win_loss': out['win_loss'], 'mae_pts': out['mae_pts'],
                    'mae_r': out['mae_r'],
                })
        rows.append(row)
    base = next(r for r in rows if r['variant'] == 'V0_BASELINE')
    for r in rows:
        if r['variant'] != 'V0_BASELINE' and r.get('r_multiple') is not None \
                and base.get('r_multiple') is not None:
            r['delta_r'] = round(r['r_multiple'] - base['r_multiple'], 3)
            r['delta_vs_base_label'] = _label_delta(base.get('win_loss'),
                                                     r.get('win_loss'))
    if extra:
        for r in rows:
            r.update(extra)
    return rows


def _label_delta(base_label, new_label):
    if new_label is None or base_label is None:
        return ''
    if new_label == base_label:
        return 'SAME'
    order = {'LOSS': 0, 'FLAT': 1, 'WIN': 2}
    if base_label == 'WIN' and new_label != 'WIN':
        return 'WIN_LOST'
    if base_label == 'LOSS' and new_label == 'WIN':
        return 'LOSS_SAVED'
    return 'CHANGED'


def _row(book, inst, day, direction, level, i, variant, status, wait_bars):
    return {'book': book, 'instrument': inst, 'session_date': day,
            'signal_direction': direction, 'signal_level': level,
            'signal_index': i, 'variant': variant, 'status': status,
            'wait_bars': wait_bars}


# ------------------------------------------------------------- summary -----
def summarize(rows, variant):
    v = [r for r in rows if r['variant'] == variant]
    traded = [r for r in v if r.get('r_multiple') is not None]
    skipped = [r for r in v if r.get('r_multiple') is None]
    wins = [r for r in traded if r.get('win_loss') == 'WIN']
    losses = [r for r in traded if r.get('win_loss') == 'LOSS']
    flat = [r for r in traded if r.get('win_loss') == 'FLAT']
    rs = [r['r_multiple'] for r in traded]
    skip_reasons = {}
    for r in skipped:
        skip_reasons[r['status']] = skip_reasons.get(r['status'], 0) + 1
    return {
        'variant': variant,
        'label': C.VARIANT_LABELS.get(variant, variant),
        'signals': len(v),
        'traded': len(traded),
        'skipped': len(skipped),
        'skip_reasons': skip_reasons,
        'wins': len(wins), 'losses': len(losses), 'flats': len(flat),
        'win_rate_pct': round(100.0 * len(wins) / len(traded), 1) if traded else None,
        'loss_rate_pct': round(100.0 * len(losses) / len(traded), 1) if traded else None,
        'total_r': round(sum(rs), 3) if rs else 0.0,
        'mean_r': round(statistics.fmean(rs), 3) if rs else None,
        'median_r': round(statistics.median(rs), 3) if rs else None,
        'net_r_after_cost': round(sum(rs) - C.COST_R_PER_TRADE * len(traded), 3) if rs else None,
        'best_r': max(rs) if rs else None,
        'worst_r': min(rs) if rs else None,
        'mean_mae_r': round(statistics.fmean([r['mae_r'] for r in traded if r.get('mae_r') is not None]), 3)
        if any(r.get('mae_r') is not None for r in traded) else None,
        'mean_wait_bars': round(statistics.fmean([r['wait_bars'] for r in traded if r.get('wait_bars') is not None]), 2)
        if any(r.get('wait_bars') is not None for r in traded) else None,
    }


def paired(rows, variant):
    """Paired comparison against the baseline on the same signals."""
    base = {r['key']: r for r in rows if r['variant'] == 'V0_BASELINE'}
    var = {r['key']: r for r in rows if r['variant'] == variant}
    out = {'variant': variant, 'compared': 0, 'win_lost': 0, 'loss_saved': 0,
           'changed': 0, 'skipped': 0, 'same': 0, 'delta_r_total': 0.0,
           'improved': 0, 'worsened': 0}
    for k, b in base.items():
        if k not in var:
            continue
        v = var[k]
        out['compared'] += 1
        if v.get('r_multiple') is None:
            out['skipped'] += 1
            if b.get('r_multiple') is not None:
                out['delta_r_total'] += -b['r_multiple']
                if b.get('win_loss') == 'WIN':
                    out['worsened'] += 1
            continue
        d = (v['r_multiple'] - b['r_multiple']) if b.get('r_multiple') is not None else 0.0
        out['delta_r_total'] += d
        if d > 0:
            out['improved'] += 1
        elif d < 0:
            out['worsened'] += 1
        dl = _label_delta(b.get('win_loss'), v.get('win_loss'))
        if dl == 'WIN_LOST':
            out['win_lost'] += 1
        elif dl == 'LOSS_SAVED':
            out['loss_saved'] += 1
        elif dl == 'SAME':
            out['same'] += 1
        else:
            out['changed'] += 1
    out['delta_r_total'] = round(out['delta_r_total'], 3)
    return out


def sign_test(improved, worsened):
    """Two-sided exact sign test p-value on the non-tied paired differences."""
    from math import comb
    n = improved + worsened
    if n == 0:
        return None
    k = min(improved, worsened)
    tail = sum(comb(n, j) for j in range(0, k + 1)) / (2.0 ** n)
    return round(min(1.0, 2 * tail), 4)


# --------------------------------------------------------------- books -----
def book_recorded(con, sessions_by_inst):
    """Book A: the recorded live-engine signal book (paper_align, plain)."""
    rows = con.execute(
        "SELECT session_date,instrument_id,variant,state,direction,level,"
        "entry_time,entry_price,stop_price,target_price,exit_time,exit_price,"
        "exit_reason,r_multiple,result FROM paper_align "
        "WHERE variant='plain' AND instrument_id IN ('NIFTY','BANKNIFTY') "
        "ORDER BY session_date,instrument_id").fetchall()
    out = []
    for r in rows:
        rec = dict(r)
        inst = rec['instrument_id']
        day = rec['session_date']
        sessions = sessions_by_inst.get(inst, {})
        candles = sessions.get(day, [])
        if not candles:
            out.append((rec, None, 'NO_CANDLES', None, None, None))
            continue
        prev = prev_session_ohlc(sessions, day)
        if not prev:
            out.append((rec, None, 'NO_PREV_SESSION', None, None, None))
            continue
        lv = P.day_levels(prev['high'], prev['low'], prev['close'])
        if not lv:
            out.append((rec, None, 'NO_LEVELS', None, None, None))
            continue
        et = str(rec['entry_time'] or '')[:16]
        idx = next((k for k, c in enumerate(candles) if c['timestamp'][:16].replace('T', ' ') == et), None)
        if idx is None or idx == 0:
            out.append((rec, None, 'NO_ENTRY_BAR', None, None, None))
            continue
        out.append((rec, candles, 'OK', idx, idx - 1, lv))
    return out


def book_replay(con, sessions_by_inst):
    """Book B: the current production engine replayed over every session."""
    out = []
    for inst in C.INSTRUMENTS:
        sessions = sessions_by_inst.get(inst, {})
        for day in sorted(sessions):
            candles = sessions[day]
            prev = prev_session_ohlc(sessions, day)
            if not prev:
                out.append((inst, day, None, 'NO_PREV_SESSION'))
                continue
            lv = P.day_levels(prev['high'], prev['low'], prev['close'])
            if not lv:
                out.append((inst, day, None, 'NO_LEVELS'))
                continue
            sig, skip = replay_session(candles, lv)
            if not sig:
                out.append((inst, day, None, skip))
                continue
            dr, lvl, i = sig
            out.append((inst, day, (dr, lvl, i), 'OK'))
    return out


def live_rows(con):
    out = []
    for r in con.execute('SELECT * FROM paper_trades').fetchall():
        rec = dict(r)
        try:
            ev = json.loads(rec['qualification_evidence'] or '{}')
        except (TypeError, ValueError):
            ev = {}
        if ev.get('origin') == 'live-watch':
            rec['_ev'] = ev
            out.append(rec)
    return out


# ---------------------------------------------------------------- main -----
def main():
    os.makedirs(C.OUT_DIR, exist_ok=True)
    os.makedirs(C.REPORT_DIR, exist_ok=True)
    con = connect(C.SNAPSHOT_DB)
    try:
        candles_by_inst = {i: load_candles(con, i) for i in C.INSTRUMENTS}
        sessions_by_inst = {i: group_sessions(c) for i, c in candles_by_inst.items()}
        all_rows = []
        parity = []

        # ---- Book A: the recorded live-engine book
        for rec, candles, status, idx, trig, lv in book_recorded(con, sessions_by_inst):
            if status != 'OK':
                parity.append({'session_date': rec['session_date'],
                               'instrument_id': rec['instrument_id'],
                               'status': status})
                continue
            inst = rec['instrument_id']
            day = rec['session_date']
            rows = evaluate_signal('A_RECORDED_BOOK', inst, day,
                                    rec['direction'], rec['level'], trig,
                                    candles, lv,
                                    extra={'recorded_entry': rec['entry_price'],
                                           'recorded_r': rec['r_multiple'],
                                           'recorded_label': rec['result'],
                                           'recorded_exit': rec['exit_price'],
                                           'recorded_exit_reason': rec['exit_reason']})
            for r in rows:
                r['key'] = '%s|%s|%s' % (inst, day, rec['level'])
            all_rows.extend(rows)
            v0 = rows[0]
            parity.append({
                'session_date': day, 'instrument_id': inst,
                'status': 'OK',
                'recorded_level': rec['level'],
                'recorded_direction': rec['direction'],
                'recorded_entry': rec['entry_price'],
                'replay_entry': v0.get('entry'),
                'entry_diff': (round(v0.get('entry') - rec['entry_price'], 2)
                               if v0.get('entry') is not None and rec['entry_price'] is not None else None),
                'recorded_exit': rec['exit_price'],
                'replay_exit': v0.get('exit'),
                'recorded_r': rec['r_multiple'],
                'replay_r': v0.get('r_multiple'),
                'recorded_label': rec['result'],
                'replay_label': v0.get('win_loss'),
                'recorded_exit_reason': rec['exit_reason'],
                'replay_exit_reason': v0.get('exit_reason'),
            })

        # ---- Book B: the current-engine replay
        replay_skip = {}
        for inst, day, sig, status in book_replay(con, sessions_by_inst):
            if sig is None:
                replay_skip[status] = replay_skip.get(status, 0) + 1
                continue
            dr, lvl, i = sig
            sessions = sessions_by_inst[inst]
            candles = sessions[day]
            prev = prev_session_ohlc(sessions, day)
            lv = P.day_levels(prev['high'], prev['low'], prev['close'])
            rows = evaluate_signal('B_CURRENT_ENGINE_REPLAY', inst, day,
                                    dr, lvl, i, candles, lv)
            for r in rows:
                r['key'] = '%s|%s|%s' % (inst, day, lvl)
            all_rows.extend(rows)

        # ---- the real live trades
        live_rows_out = []
        for rec in live_rows(con):
            inst = rec['instrument_id']
            ev = rec['_ev']
            day = str(ev.get('signal_time') or rec['entry_time'])[:10]
            sessions = sessions_by_inst.get(inst, {})
            candles = sessions.get(day, [])
            prev = prev_session_ohlc(sessions, day) if candles else None
            lv = P.day_levels(prev['high'], prev['low'], prev['close']) if prev else None
            level = ev.get('scenario')
            direction = 'BEAR' if rec['direction'] == 'BEARISH' else 'BULL'
            trig = None
            if candles and ev.get('signal_time'):
                st = str(ev['signal_time'])[:16].replace('T', ' ')
                trig = next((k for k, c in enumerate(candles)
                             if c['timestamp'][:16].replace('T', ' ') == st), None)
            rows = []
            if trig is None or lv is None:
                rows = [{'book': 'C_LIVE_TRADES', 'instrument': inst,
                         'session_date': day, 'signal_direction': direction,
                         'signal_level': level, 'signal_index': trig,
                         'variant': 'V0_BASELINE',
                         'status': 'NO_TRIGGER_BAR' if trig is None else 'NO_LEVELS',
                         'wait_bars': None}]
            else:
                rows = evaluate_signal('C_LIVE_TRADES', inst, day, direction,
                                        level, trig, candles, lv,
                                        extra={'live_trade_id': rec['trade_id'],
                                               'recorded_entry': rec['entry'],
                                               'recorded_exit': rec['exit_price'],
                                               'recorded_exit_reason': rec['exit_reason'],
                                               'recorded_stop': rec['stop'],
                                               'recorded_target': rec['target']})
            for r in rows:
                r['key'] = '%s|%s' % (inst, rec['trade_id'])
            live_rows_out.extend(rows)
    finally:
        con.close()

    # ---- summaries
    summaries = {}
    for book in ('A_RECORDED_BOOK', 'B_CURRENT_ENGINE_REPLAY'):
        brows = [r for r in all_rows if r['book'] == book]
        if not brows:
            continue
        summaries[book] = {
            'signals': len({r['key'] for r in brows}),
            'variants': {v: summarize(brows, v) for v in C.VARIANT_ORDER},
            'paired': {v: paired(brows, v) for v in C.VARIANT_ORDER},
        }
        for v in C.VARIANT_ORDER:
            if v in summaries[book]['paired']:
                summaries[book]['paired'][v]['sign_test_p'] = sign_test(
                    summaries[book]['paired'][v]['improved'],
                    summaries[book]['paired'][v]['worsened'])
    summaries['B_CURRENT_ENGINE_REPLAY']['session_buckets'] = replay_skip

    live_summary = {
        'variants': {v: summarize(live_rows_out, v) for v in C.VARIANT_ORDER},
    }

    # ---- outputs
    def write_csv(path, rows, fields):
        with open(path, 'w', newline='') as fh:
            w = csv.DictWriter(fh, fieldnames=fields, extrasaction='ignore')
            w.writeheader()
            for r in rows:
                w.writerow(r)

    fields = ['book', 'instrument', 'session_date', 'signal_direction', 'signal_level',
              'signal_index', 'level_price', 'variant', 'variant_direction',
              'variant_level', 'status', 'wait_bars', 'entry', 'entry_time',
              'exit', 'exit_time', 'exit_reason', 'r_multiple', 'points',
              'win_loss', 'mae_pts', 'mae_r', 'delta_r', 'delta_vs_base_label',
              'recorded_entry', 'recorded_exit', 'recorded_exit_reason',
              'recorded_r', 'recorded_label', 'live_trade_id', 'key']
    write_csv(os.path.join(C.OUT_DIR, 'wait_variant_trades.csv'), all_rows, fields)
    write_csv(os.path.join(C.OUT_DIR, 'live_trade_counterfactual.csv'), live_rows_out, fields)
    write_csv(os.path.join(C.OUT_DIR, 'replay_parity.csv'), parity,
              ['session_date', 'instrument_id', 'status', 'recorded_level',
               'recorded_direction', 'recorded_entry', 'replay_entry', 'entry_diff',
               'recorded_exit', 'replay_exit', 'recorded_r', 'replay_r',
               'recorded_label', 'replay_label', 'recorded_exit_reason',
               'replay_exit_reason'])

    summary_rows = []
    for book, s in summaries.items():
        if book == 'B_CURRENT_ENGINE_REPLAY' and 'session_buckets' in s:
            pass
        for v, vs in s.get('variants', {}).items():
            p = s.get('paired', {}).get(v, {})
            summary_rows.append({
                'book': book, 'variant': v, 'label': vs['label'],
                'signals': vs['signals'], 'traded': vs['traded'],
                'skipped': vs['skipped'],
                'skip_reasons': json.dumps(vs['skip_reasons'], sort_keys=True),
                'wins': vs['wins'], 'losses': vs['losses'], 'flats': vs['flats'],
                'win_rate_pct': vs['win_rate_pct'], 'loss_rate_pct': vs['loss_rate_pct'],
                'total_r': vs['total_r'], 'mean_r': vs['mean_r'],
                'median_r': vs['median_r'],
                'net_r_after_cost': vs['net_r_after_cost'],
                'mean_mae_r': vs['mean_mae_r'], 'mean_wait_bars': vs['mean_wait_bars'],
                'delta_r_total': p.get('delta_r_total'),
                'win_lost': p.get('win_lost'), 'loss_saved': p.get('loss_saved'),
                'skipped_vs_base': p.get('skipped'),
                'improved': p.get('improved'), 'worsened': p.get('worsened'),
                'sign_test_p': p.get('sign_test_p'),
            })
    write_csv(os.path.join(C.OUT_DIR, 'variant_summary.csv'), summary_rows,
              list(summary_rows[0].keys()) if summary_rows else ['book', 'variant'])

    payload = {'generated_at': datetime.now().isoformat(timespec='seconds'),
               'snapshot': C.SNAPSHOT_DB,
               'constants': {'stop_pct': C.OPEN_STOP_PCT, 'target_pct': C.OPEN_TARGET_PCT,
                             'wait_expiry_bars': C.WAIT_EXPIRY_BARS,
                             'cost_r_per_trade': C.COST_R_PER_TRADE,
                             'entry_window': [C.OPEN_MIN, C.OPEN_EOD]},
               'books': summaries,
               'live_trades': live_summary}
    with open(os.path.join(C.OUT_DIR, 'wait_study_summary.json'), 'w') as fh:
        json.dump(payload, fh, indent=2, sort_keys=True, default=str)

    print('rows:', len(all_rows), 'live rows:', len(live_rows_out))
    for book in ('A_RECORDED_BOOK', 'B_CURRENT_ENGINE_REPLAY'):
        if book not in summaries:
            continue
        print('\n==', book, 'signals:', summaries[book]['signals'])
        for v in C.VARIANT_ORDER:
            vs = summaries[book]['variants'][v]
            p = summaries[book]['paired'][v]
            print('  %-28s traded %3d skipped %3d W/L %3d/%-3d wr %5s%% totalR %8s '
                  'netR %8s dR %8s winLost %3d lossSaved %3d p %s'
                  % (v, vs['traded'], vs['skipped'], vs['wins'], vs['losses'],
                     vs['win_rate_pct'], vs['total_r'], vs['net_r_after_cost'],
                     p.get('delta_r_total'), p.get('win_lost'), p.get('loss_saved'),
                     p.get('sign_test_p')))
    print('\n== live trades')
    for v in C.VARIANT_ORDER:
        vs = live_summary['variants'][v]
        print('  %-28s traded %2d skipped %2d W/L %2d/%-2d totalR %7s'
              % (v, vs['traded'], vs['skipped'], vs['wins'], vs['losses'], vs['total_r']))
    return payload


if __name__ == '__main__':
    main()
