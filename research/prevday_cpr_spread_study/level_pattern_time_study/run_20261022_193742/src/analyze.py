"""Aggregation of the built event / pattern / entry datasets into the
required summary CSVs."""
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config as C  # noqa: E402
import data as D  # noqa: E402


def read_csv(name):
    path = os.path.join(C.RUN_DIR, 'outputs', name)
    rows = []
    with open(path, newline='') as fh:
        for r in csv.DictReader(fh):
            rows.append(r)
    return rows


def _num(v):
    try:
        return float(v)
    except Exception:
        return None


def _mean(xs):
    xs = [x for x in xs if x is not None]
    if not xs:
        return None
    return sum(xs) / len(xs)


def _median(xs):
    xs = sorted([x for x in xs if x is not None])
    if not xs:
        return None
    m = len(xs) // 2
    if len(xs) % 2:
        return xs[m]
    return (xs[m - 1] + xs[m]) / 2.0


def fwd_stats(rows, field):
    vals = [_num(r.get(field)) for r in rows]
    vals = [v for v in vals if v is not None]
    return {'n': len(vals), 'mean': _mean(vals), 'median': _median(vals)}


def fwd_rate(rows, field):
    vals = [_num(r.get(field)) for r in rows]
    vals = [v for v in vals if v is not None and v > 0]
    return {'n': len(vals), 'rate': len(vals) / len([v for v in vals if v is not None]) if vals else None}


def build_pattern_summary():
    pats = read_csv('patterns_raw.csv')
    entries = read_csv('entries.csv')
    events = read_csv('level_events.csv')
    out = []
    keys = set()
    for p in pats:
        k = (p.get('tol_variant', ''), p.get('instrument', ''),
             p.get('pattern_id', ''), p.get('direction', ''),
             p.get('level', ''))
        if k in keys:
            continue
        keys.add(k)
        key_rows = [p]
        ents = [e for e in entries if (e.get('tol_variant', ''),
                                       e.get('instrument', ''),
                                       e.get('pattern_id', ''),
                                       e.get('direction', ''),
                                       e.get('level', '')) == k]
        st = fwd_stats([e for e in ents if e.get('status') == 'ENTERED'],
                       'fwd_60')
        ent = [e for e in ents if e.get('status') == 'ENTERED']
        sessions = set((e.get('tol_variant', ''), e.get('instrument', ''),
                        e.get('date', '')) for e in ent)
        out.append({
            'tol_variant': k[0], 'instrument': k[1], 'pattern_id': k[2],
            'family': p.get('family', ''),
            'pattern_name': p.get('pattern_name', ''),
            'level': k[4], 'direction': k[3],
            'n_pattern_instances': 1, 'n_entries': len(ents),
            'n_entered': len(ent), 'n_skipped': len(ents) - len(ent),
            'n_sessions': len(sessions),
            'fwd60_n': st['n'], 'fwd60_mean': st['mean'],
            'fwd60_median': st['median'],
            'mfe60_mean': _mean([_num(e.get('mfe_60')) for e in ent]),
            'mae60_mean': _mean([_num(e.get('mae_60')) for e in ent]),
        })
    fields = ['tol_variant', 'instrument', 'pattern_id', 'family',
              'pattern_name', 'level', 'direction', 'n_pattern_instances',
              'n_entries', 'n_entered', 'n_skipped', 'n_sessions', 'fwd60_n',
              'fwd60_mean', 'fwd60_median', 'mfe60_mean', 'mae60_mean']
    path = os.path.join(C.RUN_DIR, 'outputs', 'pattern_summary.csv')
    with open(path, 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for r in out:
            w.writerow(r)
    return out


def build_time_bucket_summary():
    entries = read_csv('entries.csv')
    pats = read_csv('patterns_raw.csv')
    out = []
    groups = {}
    for e in entries:
        if e.get('status') != 'ENTERED':
            continue
        bucket = D.bucket_of(e.get('entry_t') or '')
        key = (e.get('tol_variant', ''), e.get('instrument', ''),
               e.get('pattern_id', ''), e.get('direction', ''),
               e.get('level', ''), bucket)
        groups.setdefault(key, []).append(e)
    for k, rows in sorted(groups.items()):
        tol, inst, pid, direction, level, bucket = k
        st = fwd_stats(rows, 'fwd_60')
        ent = [e for e in rows if e.get('status') == 'ENTERED']
        out.append({
            'tol_variant': tol, 'instrument': inst, 'pattern_id': pid,
            'family': '', 'pattern_name': '', 'direction': direction,
            'level': level, 'entry_t': bucket, 'bucket': bucket,
            'n_entries': len(rows), 'n_entered': len(ent),
            'n_skipped': len(rows) - len(ent),
            'n_sessions': len(set(e.get('date') for e in rows)),
            'fwd60_n': st['n'], 'fwd60_mean': st['mean'],
            'fwd60_median': st['median'],
            'mfe60_mean': _mean([_num(e.get('mfe_60')) for e in ent]),
            'mae60_mean': _mean([_num(e.get('mae_60')) for e in ent]),
        })
    fields = ['tol_variant', 'instrument', 'pattern_id', 'family',
              'pattern_name', 'direction', 'level', 'entry_t', 'bucket',
              'n_entries', 'n_entered', 'n_skipped', 'n_sessions', 'fwd60_n',
              'fwd60_mean', 'fwd60_median', 'mfe60_mean', 'mae60_mean']
    path = os.path.join(C.RUN_DIR, 'outputs', 'time_bucket_summary.csv')
    with open(path, 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for r in out:
            w.writerow(r)
    return out


def build_instrument_level_summary():
    events = read_csv('level_events.csv')
    entries = read_csv('entries.csv')
    out = []
    groups = {}
    for e in events:
        k = (e.get('tol_variant', ''), e.get('instrument', ''),
             e.get('level', ''), e.get('event', ''))
        groups.setdefault(k, []).append(e)
    keys = set()
    for e in entries:
        k = (e.get('tol_variant', ''), e.get('instrument', ''),
             e.get('level', ''), e.get('pattern_id', ''))
        if k in keys:
            continue
        keys.add(k)
        evs = groups.get((k[0], k[1], k[2], None), [])
        inst = e.get('instrument')
        ent = [x for x in entries if (x.get('tol_variant', ''),
                                     x.get('instrument', ''),
                                     x.get('level', ''),
                                     x.get('pattern_id', '')) == k]
        ent = [x for x in ent if x.get('status') == 'ENTERED']
        out.append({
            'tol_variant': k[0], 'instrument': inst, 'level': k[2],
            'pattern_id': k[3], 'n_entries': len(ent),
            'n_entered': len(ent),
            'mean_fwd60': _mean([_num(x.get('fwd_60')) for x in ent]),
        })
    fields = ['tol_variant', 'instrument', 'level', 'pattern_id', 'n_entries',
              'n_entered', 'mean_fwd60']
    path = os.path.join(C.RUN_DIR, 'outputs', 'instrument_level_summary.csv')
    with open(path, 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for r in out:
            w.writerow(r)
    return out


def build_candidate_comparison():
    entries = read_csv('entries.csv')
    out = []
    groups = {}
    for e in entries:
        if e.get('status') != 'ENTERED':
            continue
        k = (e.get('tol_variant', ''), e.get('instrument', ''),
             e.get('pattern_id', ''), e.get('direction', ''),
             e.get('level', ''), e.get('partition', ''))
        groups.setdefault(k, []).append(e)
    for k, rows in sorted(groups.items()):
        st = fwd_stats(rows, 'fwd_60')
        out.append({
            'tol_variant': k[0], 'instrument': k[1], 'pattern_id': k[2],
            'direction': k[3], 'level': k[4], 'partition': k[5],
            'n': len(rows), 'n_sessions': len(set(r.get('date') for r in rows)),
            'fwd60_n': st['n'], 'fwd60_mean': st['mean'],
            'fwd60_median': st['median'],
            'mfe60_mean': _mean([_num(r.get('mfe_60')) for r in rows]),
            'mae60_mean': _mean([_num(r.get('mae_60')) for r in rows]),
        })
    fields = ['tol_variant', 'instrument', 'pattern_id', 'direction', 'level',
              'partition', 'n', 'n_sessions', 'fwd60_n', 'fwd60_mean',
              'fwd60_median', 'mfe60_mean', 'mae60_mean']
    path = os.path.join(C.RUN_DIR, 'outputs', 'candidate_comparison.csv')
    with open(path, 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for r in out:
            w.writerow(r)
    return out


if __name__ == '__main__':
    print('pattern_summary rows:', len(build_pattern_summary()))
    print('time_bucket rows:', len(build_time_bucket_summary()))
    print('instrument_level rows:', len(build_instrument_level_summary()))
    print('candidate_comparison rows:', len(build_candidate_comparison()))
