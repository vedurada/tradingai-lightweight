"""Driver: build the event dataset, the pattern instances and the candidate
entries (all under both predeclared tolerance variants)."""
import csv
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config as C  # noqa: E402
import data as D  # noqa: E402
import entries as EN  # noqa: E402
import events as E  # noqa: E402
import levels as L  # noqa: E402
import patterns as P  # noqa: E402

TOL_VARIANTS = ('fixed', 'vol')


def partitions(dates):
    """Chronological, session separated IS / VALIDATION / OOS."""
    n = len(dates)
    is_n = int(n * C.IS_FRACTION)
    val_n = is_n + int(n * C.VALIDATION_FRACTION)
    out = {}
    for i, d in enumerate(dates):
        if i < is_n:
            out[d] = 'IS'
        elif i < val_n:
            out[d] = 'VALIDATION'
        else:
            out[d] = 'OOS'
    return out, is_n, val_n


def main():
    sessions = D.load_sessions()
    dates = sorted(set(d for inst in C.INSTRUMENTS for d in sessions[inst]))
    part, n_is, n_val_cum = partitions(dates)
    n_val = n_val_cum - n_is
    n_oos = len(dates) - n_val_cum

    event_rows = []
    pattern_rows = []
    entry_rows = []
    ev_id = 0
    ent_id = 0

    for inst in C.INSTRUMENTS:
        for date in sorted(sessions[inst]):
            sess = sessions[inst][date]
            sess['instrument'] = inst
            bars = sess['bars']
            lv = sess['levels']
            prev = sess['prev']
            ctx = {
                'open': bars[0]['o'],
                'session_high': max(b['h'] for b in bars),
                'session_low': min(b['l'] for b in bars),
                'close': bars[-1]['c'],
                'prev_close': prev['close'] if prev else '',
                'prev_high': prev['high'] if prev else '',
                'prev_low': prev['low'] if prev else '',
                'cpr_width_pct': round(L.cpr_width_pct(lv), 4) if lv else '',
                'prev_range': round(sess.get('prev_range', 0), 4),
                'prev_mean_bar_range': round(
                    sess.get('prev_mean_bar_range', 0), 4),
                'gap': ('ABOVE_PDH' if lv and bars[0]['o'] > lv['pdh'] else
                        'BELOW_PDL' if lv and bars[0]['o'] < lv['pdl'] else
                        'ABOVE_PDC' if lv and bars[0]['o'] > lv['pdc'] else
                        'BELOW_PDC' if lv and bars[0]['o'] < lv['pdc'] else
                        'INSIDE'),
                'chop_zone_changes': E.session_chop(sess)['zone_changes'],
                'bars': len(bars),
                'partition': part[date],
            }
            for variant in TOL_VARIANTS:
                tol = sess['tol'].get(variant, C.TOL_FIXED_POINTS.get(inst, 10.0))
                evs = E.detect_level_events(sess, tol)
                pats = P.build(sess, evs, inst, tol)
                for e in evs:
                    ev_id += 1
                    row = {
                        'event_id': 'E%06d' % ev_id,
                        'tol_variant': variant, 'tolerance': round(tol, 4),
                        'instrument': inst, 'date': date,
                        'partition': part[date],
                        'event': e['event'], 'level': e['level'],
                        'level_price': (round(e['level_price'], 4)
                                        if e.get('level_price') is not None
                                        else ''),
                        'role': e.get('role', ''),
                        'direction_hint': e.get('direction') or '',
                        'bar_idx': e['bar_idx'], 'timestamp': e['ts'],
                        'time': e['t'], 'close': e['close'],
                        'touch_number': e.get('touch_number', ''),
                        'break_bar': e.get('break_bar', ''),
                        'target_level': e.get('target_level', ''),
                        'target_price': (round(e['target_price'], 4)
                                         if e.get('target_price') is not None
                                         else ''),
                        'distance': (round(e['distance'], 4)
                                     if e.get('distance') is not None else ''),
                        'detail': e.get('note', ''),
                    }
                    row.update(ctx)
                    event_rows.append(row)
                for p in pats:
                    prow = {
                        'tol_variant': variant, 'tolerance': round(tol, 4),
                        'instrument': inst, 'date': date,
                        'partition': part[date],
                        'pattern_id': p['pattern_id'], 'pattern_name': p['name'],
                        'family': p['family'], 'level': p['level'],
                        'level_price': (round(p['level_price'], 4)
                                        if p.get('level_price') is not None
                                        else ''),
                        'direction': p['direction'],
                        'anchor_idx': p['anchor_idx'],
                        'anchor_ts': p['anchor_ts'], 'anchor_t': p['anchor_t'],
                        'rejection_idx': p.get('rejection_idx')
                        if p.get('rejection_idx') is not None else '',
                        'retest_idx': p.get('retest_idx')
                        if p.get('retest_idx') is not None else '',
                        'note': p.get('note', ''),
                    }
                    prow.update(ctx)
                    pattern_rows.append(prow)
                for p in pats:
                    for r in EN.apply_rules(sess, p, inst, tol, variant):
                        r['partition'] = part[date]
                        if r['status'] == 'ENTERED':
                            ent_id += 1
                            r['entry_id'] = 'T%06d' % ent_id
                            for w in (3, 6, 12):
                                mins = w * 5
                                fo = EN.forward(sess, r['entry_idx'],
                                                r['direction'], r['level'],
                                                tol, w)
                                r['fwd_%d' % mins] = fo['forward_move']
                                r['mfe_%d' % mins] = fo['mfe']
                                r['mae_%d' % mins] = fo['mae']
                                r['complete_%d' % mins] = int(
                                    fo['window_complete'])
                                if mins == 60:
                                    r['time_to_fav_60'] = fo[
                                        'time_to_favourable']
                                    r['time_to_adv_60'] = fo['time_to_adverse']
                                    r['reversal_60'] = int(
                                        bool(fo['reversal']))
                                    r['failure_60'] = int(
                                        bool(fo['breakout_failure']))
                                    r['reached_next_60'] = int(
                                        bool(fo['reached_next_level']))
                                    r['next_level'] = fo['next_level']
                                    r['room_to_next'] = fo[
                                        'room_to_next_level']
                        else:
                            r['entry_id'] = ''
                        for k in ('fwd_15', 'mfe_15', 'mae_15', 'complete_15',
                                  'fwd_30', 'mfe_30', 'mae_30', 'complete_30',
                                  'fwd_60', 'mfe_60', 'mae_60', 'complete_60',
                                  'time_to_fav_60', 'time_to_adv_60',
                                  'reversal_60', 'failure_60',
                                  'reached_next_60', 'next_level',
                                  'room_to_next'):
                            r.setdefault(k, '')
                        entry_rows.append(r)

    outdir = os.path.join(C.RUN_DIR, 'outputs')

    def write_csv(name, rows, fields=None):
        path = os.path.join(outdir, name)
        if not rows:
            open(path, 'w').write('')
            return path
        fields = fields or list(rows[0].keys())
        with open(path, 'w', newline='') as fh:
            w = csv.DictWriter(fh, fieldnames=fields, extrasaction='ignore')
            w.writeheader()
            for r in rows:
                w.writerow(r)
        return path

    ev_fields = ['event_id', 'tol_variant', 'tolerance', 'instrument', 'date',
                 'partition', 'event', 'level', 'level_price', 'role',
                 'direction_hint', 'bar_idx', 'timestamp', 'time', 'close',
                 'touch_number', 'break_bar', 'target_level', 'target_price',
                 'distance', 'detail', 'open', 'session_high', 'session_low',
                 'close', 'prev_close', 'prev_high', 'prev_low',
                 'cpr_width_pct', 'prev_range', 'prev_mean_bar_range', 'gap',
                 'chop_zone_changes', 'bars']
    ent_fields = ['entry_id', 'tol_variant', 'instrument', 'date', 'partition',
                  'rule', 'status', 'skip_reason', 'pattern_id',
                  'pattern_name', 'family', 'level', 'level_price',
                  'direction', 'anchor_idx', 'anchor_t', 'entry_idx',
                  'entry_ts', 'entry_t', 'entry_price', 'fwd_15', 'fwd_30',
                  'fwd_60', 'mfe_15', 'mfe_30', 'mfe_60', 'mae_15',
                  'mae_30', 'mae_60', 'complete_15', 'complete_30',
                  'complete_60', 'time_to_fav_60', 'time_to_adv_60',
                  'reversal_60', 'failure_60', 'reached_next_60',
                  'next_level', 'room_to_next', 'cpr_width_pct', 'gap',
                  'chop_zone_changes', 'prev_range', 'open', 'close']
    write_csv('level_events.csv', event_rows, ev_fields)
    write_csv('patterns_raw.csv', pattern_rows)
    write_csv('entries.csv', entry_rows, ent_fields)

    meta = {
        'generated_at': datetime.now().astimezone().isoformat(),
        'sessions_total': len(dates),
        'partitions': {'IS': n_is, 'VALIDATION': n_val, 'OOS': n_oos},
        'partition_boundary_dates': {
            'IS_last': dates[n_is - 1] if n_is else None,
            'VALIDATION_last': dates[n_val - 1] if n_val else None,
            'OOS_first': dates[n_val] if n_val < len(dates) else None,
            'OOS_last': dates[-1]},
        'tolerance_variants': {
            'fixed': C.TOL_FIXED_POINTS,
            'vol': {'NIFTY': '0.25 x previous session mean 5m bar range',
                    'BANKNIFTY': '0.25 x previous session mean 5m bar range'}},
        'counts': {'events': len(event_rows),
                   'pattern_instances': len(pattern_rows),
                   'entry_records': len(entry_rows),
                   'entered': sum(1 for r in entry_rows
                                  if r['status'] == 'ENTERED'),
                   'skipped': sum(1 for r in entry_rows
                                  if r['status'] == 'SKIPPED')},
        'source_db': C.RESEARCH_DB,
    }
    with open(os.path.join(outdir, 'build_meta.json'), 'w') as fh:
        json.dump(meta, fh, indent=1, sort_keys=True)
    print(json.dumps(meta, indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main())
