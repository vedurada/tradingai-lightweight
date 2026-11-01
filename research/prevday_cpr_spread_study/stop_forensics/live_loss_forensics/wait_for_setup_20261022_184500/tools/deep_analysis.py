"""Deeper analysis of the wait-for-setup study outputs (read-only, post-processing).

Reads outputs/wait_variant_trades.csv and prints/writes the decision-relevant
cut-ups: the economics of the skipped setups, the per-level breakdown, the
wait-time distribution, the risk profile and the live-trade counterfactual.
"""
import collections
import csv
import json
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, 'src'))

import wconfig as C  # noqa: E402


def load(name):
    with open(os.path.join(ROOT, 'outputs', name)) as fh:
        return list(csv.DictReader(fh))


def f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def risk_profile(rs):
    """Total R, the max drawdown in R, the profit factor and the expectancy."""
    if not rs:
        return {}
    peak = 0.0
    cum = 0.0
    mdd = 0.0
    for r in rs:
        cum += r
        peak = max(peak, cum)
        mdd = max(mdd, peak - cum)
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r < 0]
    return {
        'n': len(rs),
        'total_r': round(sum(rs), 3),
        'expectancy_r': round(statistics.fmean(rs), 4),
        'profit_factor': round(sum(wins) / abs(sum(losses)), 3) if losses and sum(losses) else None,
        'max_drawdown_r': round(mdd, 3),
        'share_positive_pct': round(100.0 * len(wins) / len(rs), 1),
    }


def analyse(rows, book, out):
    brows = [r for r in rows if r['book'] == book]
    base = {r['key']: r for r in brows if r['variant'] == 'V0_BASELINE'}
    out[book] = {}
    for v in C.VARIANT_ORDER:
        if v == 'V0_BASELINE':
            continue
        var = {r['key']: r for r in brows if r['variant'] == v}
        skipped = []
        traded = []
        for k, b in base.items():
            r = var.get(k)
            if r is None:
                continue
            if f(r.get('r_multiple')) is None:
                skipped.append((b, r))
            else:
                traded.append((b, r))
        sk_base_r = [f(b['r_multiple']) for b, _ in skipped if f(b['r_multiple']) is not None]
        sk_wins = sum(1 for b, _ in skipped if b.get('win_loss') == 'WIN')
        sk_losses = sum(1 for b, _ in skipped if b.get('win_loss') == 'LOSS')
        entry_gain = []
        for b, r in traded:
            e0, e1 = f(b.get('entry')), f(r.get('entry'))
            if e0 and e1:
                entry_gain.append(e0 - e1 if b.get('signal_direction') == 'BEAR' else e1 - e0)
        rs = [f(r['r_multiple']) for _, r in traded]
        out[book][v] = {
            'traded': len(traded),
            'skipped': len(skipped),
            'skipped_baseline_wins': sk_wins,
            'skipped_baseline_losses': sk_losses,
            'skipped_baseline_total_r': round(sum(sk_base_r), 3) if sk_base_r else 0.0,
            'skipped_baseline_mean_r': round(statistics.fmean(sk_base_r), 4) if sk_base_r else None,
            'entry_improvement_pts_mean': round(statistics.fmean(entry_gain), 2) if entry_gain else None,
            'entry_improvement_pts_median': round(statistics.median(entry_gain), 2) if entry_gain else None,
            'risk_profile': risk_profile(rs),
            'wait_bars': risk_profile([f(r['wait_bars']) for _, r in traded if f(r.get('wait_bars')) is not None]),
            'levels_traded': dict(collections.Counter(r.get('signal_level') for _, r in traded)),
            'levels_skipped': dict(collections.Counter(b.get('signal_level') for b, _ in skipped)),
        }


TOUCH_LEVELS = {'R1', 'R2', 'PDH', 'S1', 'S2', 'PDL'}
BREAK_LEVELS = {'BELOW_CPR', 'ABOVE_CPR'}


def family_of(level):
    if level in TOUCH_LEVELS:
        return 'TOUCH (the trigger is a touch of the level)'
    if level in BREAK_LEVELS:
        return 'BREAK (the trigger is a close beyond the CPR band)'
    if level and level.startswith('BRK_'):
        return 'BREAKOUT (a close-cross of a pivot)'
    return 'OTHER'


def family_analysis(rows, book):
    """Split by signal family: the entry-quality story differs by family."""
    brows = [r for r in rows if r['book'] == book]
    out = {}
    base = {r['key']: r for r in brows if r['variant'] == 'V0_BASELINE'}
    fams = sorted({family_of(r.get('signal_level')) for r in brows})
    for fam in fams:
        keys = [k for k, b in base.items() if family_of(b.get('signal_level')) == fam]
        per = {}
        for v in C.VARIANT_ORDER:
            vs = [r for r in brows if r['variant'] == v and r['key'] in keys]
            traded = [r for r in vs if f(r.get('r_multiple')) is not None]
            rs = [f(r['r_multiple']) for r in traded]
            gains = []
            for r in traded:
                b = base[r['key']]
                e0, e1 = f(b.get('entry')), f(r.get('entry'))
                if e0 and e1:
                    gains.append(e0 - e1 if b.get('signal_direction') == 'BEAR' else e1 - e0)
            per[v] = {
                'signals': len(keys),
                'traded': len(traded),
                'skipped': len(keys) - len(traded),
                'wins': sum(1 for r in traded if r.get('win_loss') == 'WIN'),
                'losses': sum(1 for r in traded if r.get('win_loss') == 'LOSS'),
                'win_rate_pct': round(100.0 * sum(1 for r in traded if r.get('win_loss') == 'WIN') / len(traded), 1) if traded else None,
                'total_r': round(sum(rs), 3),
                'expectancy_r': round(statistics.fmean(rs), 4) if rs else None,
                'entry_improvement_pts_mean': round(statistics.fmean(gains), 2) if gains else None,
                'entry_improvement_pts_median': round(statistics.median(gains), 2) if gains else None,
            }
        out[fam] = per
    return out


def hybrid_analysis(rows, book):
    """Wait only for the family where 'waiting for the setup' is meaningful
    (the touch signals); keep the break signals exactly as the engine trades
    them. The engine takes at most one trade per session, so a skipped setup
    cannot be replaced by another trade in the same session."""
    brows = [r for r in rows if r['book'] == book]
    base = {r['key']: r for r in brows if r['variant'] == 'V0_BASELINE'}
    out = {'V0_BASELINE_ALL': {}}
    out['V0_BASELINE_ALL'] = _agg(brows, base.keys())
    for v in C.VARIANT_ORDER:
        if v == 'V0_BASELINE':
            continue
        var = {r['key']: r for r in brows if r['variant'] == v}
        rs = []
        n = w = l = 0
        for k, b in base.items():
            fam = family_of(b.get('signal_level'))
            r = var.get(k)
            if r is None:
                continue
            if fam.startswith('TOUCH'):
                src = r
            else:
                src = b
            if f(src.get('r_multiple')) is None:
                continue
            rs.append(f(src['r_multiple']))
            n += 1
            w += 1 if src.get('win_loss') == 'WIN' else 0
            l += 1 if src.get('win_loss') == 'LOSS' else 0
        imp = wor = same = 0
        for k, b in base.items():
            fam = family_of(b.get('signal_level'))
            r = var.get(k)
            if r is None:
                continue
            src = r if fam.startswith('TOUCH') else b
            b0, b1 = f(b.get('r_multiple')), f(src.get('r_multiple'))
            if b0 is None or b1 is None:
                continue
            d = b1 - b0
            if d > 0:
                imp += 1
            elif d < 0:
                wor += 1
            else:
                same += 1
        out['HYBRID_' + v] = {'traded': n, 'wins': w, 'losses': l,
                              'paired_improved': imp, 'paired_worsened': wor,
                              'paired_same': same,
                              'win_rate_pct': round(100.0 * w / n, 1) if n else None,
                              'total_r': round(sum(rs), 3),
                              'expectancy_r': round(statistics.fmean(rs), 4) if rs else None,
                              'risk_profile': risk_profile(rs)}
    return out


def _agg(brows, keys):
    rs = []
    for r in brows:
        if r['variant'] != 'V0_BASELINE' or r['key'] not in keys:
            continue
        if f(r.get('r_multiple')) is not None:
            rs.append(f(r['r_multiple']))
    return {'traded': len(rs),
            'total_r': round(sum(rs), 3),
            'expectancy_r': round(statistics.fmean(rs), 4) if rs else None,
            'risk_profile': risk_profile(rs)}


def level_table(rows, book):
    brows = [r for r in rows if r['book'] == book]
    out = []
    levels = sorted({r.get('signal_level') for r in brows if r.get('signal_level')})
    for lvl in levels:
        rec = {'level': lvl}
        for v in C.VARIANT_ORDER:
            vs = [r for r in brows if r['variant'] == v and r.get('signal_level') == lvl
                  and f(r.get('r_multiple')) is not None]
            rec[v] = {
                'n': len(vs),
                'wins': sum(1 for r in vs if r.get('win_loss') == 'WIN'),
                'losses': sum(1 for r in vs if r.get('win_loss') == 'LOSS'),
                'total_r': round(sum(f(r['r_multiple']) for r in vs), 3),
            }
        out.append(rec)
    return out


def main():
    rows = load('wait_variant_trades.csv')
    out = {}
    for book in ('A_RECORDED_BOOK', 'B_CURRENT_ENGINE_REPLAY'):
        analyse(rows, book, out)
        out.setdefault(book + '_levels', level_table(rows, book))
        out.setdefault(book + '_families', family_analysis(rows, book))
        out.setdefault(book + '_hybrid', hybrid_analysis(rows, book))
    live = load('live_trade_counterfactual.csv')
    out['live_trades'] = [r for r in live]
    with open(os.path.join(ROOT, 'outputs', 'deep_analysis.json'), 'w') as fh:
        json.dump(out, fh, indent=2, sort_keys=True, default=str)
    print(json.dumps({k: v for k, v in out.items() if k != 'live_trades'},
                     indent=2, sort_keys=True, default=str))
    print('\n== live trade rows')
    for r in live:
        print('  %-14s %-10s %-28s %-14s status=%-12s entry=%-10s exit=%-10s r=%-8s label=%-5s reason=%-10s wait=%s'
              % (r.get('live_trade_id'), r.get('session_date'), r.get('variant'),
                 r.get('signal_level'), r.get('status'), r.get('entry'), r.get('exit'),
                 r.get('r_multiple'), r.get('win_loss'), r.get('exit_reason'),
                 r.get('wait_bars')))


if __name__ == '__main__':
    main()
