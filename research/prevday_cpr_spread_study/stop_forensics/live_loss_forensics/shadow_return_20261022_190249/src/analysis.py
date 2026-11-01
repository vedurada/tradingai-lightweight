"""Phase 3 - the family-separated analysis of the shadow annotations.

Everything is computed from outputs/shadow_annotations.json. The production
result stays the reference: the outcome of every setup is the outcome the
engine actually produced (book A: the recorded paper_align result; book B: the
current engine replayed; book C: the recorded live trade).

Uncertainty: Wilson score intervals for proportions, a seeded percentile
bootstrap for rates and rate differences, and an exact Fisher test for the
2x2 outcome tables. No third-party dependency.
"""
import csv
import json
import math
import os
import random
import statistics
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import wconfig as C


# ------------------------------------------------------------ statistics ---
def wilson(k, n, z=1.96):
    """Wilson score interval for a proportion."""
    if not n:
        return {'lo': None, 'hi': None, 'pct': None, 'k': k, 'n': n}
    p = k / n
    d = 1.0 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return {'lo': round(max(0.0, centre - half), 4),
            'hi': round(min(1.0, centre + half), 4),
            'pct': round(100 * p, 1), 'k': k, 'n': n}


def boot_proportion(k, n, draws=C.BOOTSTRAP_DRAWS, seed=C.BOOTSTRAP_SEED):
    """Seeded percentile bootstrap for a proportion (k successes of n)."""
    if not n:
        return {'lo': None, 'hi': None}
    rng = random.Random(seed)
    vals = [1.0] * k + [0.0] * (n - k)
    out = []
    for _ in range(draws):
        s = 0
        for _ in range(n):
            s += vals[rng.randrange(n)]
        out.append(s / n)
    out.sort()
    lo = out[int(0.025 * draws)]
    hi = out[min(draws - 1, int(0.975 * draws))]
    return {'lo': round(100 * lo, 1), 'hi': round(100 * hi, 1)}


def boot_diff(a_w, a_n, b_w, b_n, draws=C.BOOTSTRAP_DRAWS, seed=C.BOOTSTRAP_SEED):
    """Seeded percentile bootstrap for (win rate A - win rate B) in points."""
    if not a_n or not b_n:
        return {'lo': None, 'hi': None, 'diff_pct': None}
    rng = random.Random(seed + 1)
    a = [1.0] * a_w + [0.0] * (a_n - a_w)
    b = [1.0] * b_w + [0.0] * (b_n - b_w)
    out = []
    for _ in range(draws):
        sa = sum(a[rng.randrange(a_n)] for _ in range(a_n)) / a_n
        sb = sum(b[rng.randrange(b_n)] for _ in range(b_n)) / b_n
        out.append(100 * (sa - sb))
    out.sort()
    return {'lo': round(out[int(0.025 * draws)], 1),
            'hi': round(out[min(draws - 1, int(0.975 * draws))], 1),
            'diff_pct': round(100 * (a_w / a_n - b_w / b_n), 1)}


def fisher_exact(a, b, c, d):
    """Two-sided Fisher exact p-value for the table [[a,b],[c,d]]."""
    n = a + b + c + d
    if n == 0:
        return None
    r1, r2 = a + b, c + d
    c1 = a + c

    def pr(x):
        return math.comb(r1, x) * math.comb(r2, c1 - x) / math.comb(n, c1)

    p0 = pr(a)
    total = 0.0
    for x in range(max(0, c1 - r2), min(r1, c1) + 1):
        p = pr(x)
        if p <= p0 * (1 + 1e-9):
            total += p
    return round(min(1.0, total), 4)


def mean_ci(values, draws=C.BOOTSTRAP_DRAWS, seed=C.BOOTSTRAP_SEED):
    """Seeded percentile bootstrap for the mean (returns None if empty)."""
    vals = [v for v in values if v is not None]
    if not vals:
        return {'mean': None, 'median': None, 'lo': None, 'hi': None, 'n': 0}
    rng = random.Random(seed + 2)
    out = []
    for _ in range(draws):
        s = sum(vals[rng.randrange(len(vals))] for _ in range(len(vals)))
        out.append(s / len(vals))
    out.sort()
    return {'mean': round(statistics.fmean(vals), 2),
            'median': round(statistics.median(vals), 2),
            'lo': round(out[int(0.025 * draws)], 2),
            'hi': round(out[min(draws - 1, int(0.975 * draws))], 2),
            'n': len(vals)}


# ------------------------------------------------------------- helpers -----
def outcome_split(rows):
    w = sum(1 for r in rows if r.get('outcome_label') == 'WIN')
    l = sum(1 for r in rows if r.get('outcome_label') == 'LOSS')
    f = sum(1 for r in rows if r.get('outcome_label') == 'FLAT')
    return {'wins': w, 'losses': l, 'flats': f, 'n': len(rows),
            'win_rate_pct': round(100.0 * w / len(rows), 1) if rows else None}


def r_total(rows):
    vals = [r.get('outcome_r') for r in rows if r.get('outcome_r') is not None]
    return round(sum(vals), 3)


def filter_economics(rows, retained_key, r_key, label_key, diff_key):
    """The economics of one hypothetical filter, with explicit denominators."""
    kept = [r for r in rows if r.get(retained_key)]
    skipped = [r for r in rows if not r.get(retained_key)]
    ks = outcome_split(kept)
    ss = outcome_split(skipped)
    kept_r = [r.get(r_key) for r in kept if r.get(r_key) is not None]
    kept_rs = r_total(kept)
    skipped_r = r_total(skipped)
    diffs = [r.get(diff_key) for r in kept if r.get(diff_key) is not None]
    return {
        'filter': retained_key,
        'retained': len(kept),
        'retained_of_eligible_pct': round(100.0 * len(kept) / len(rows), 1) if rows else None,
        'retained_wins': ks['wins'], 'retained_losses': ks['losses'],
        'retained_flats': ks['flats'],
        'retained_win_rate_pct': ks['win_rate_pct'],
        'retained_total_r': kept_rs,
        'retained_r_per_trade': round(kept_rs / len(kept), 3) if kept else None,
        'retained_mean_r': round(statistics.fmean(kept_r), 3) if kept_r else None,
        'skipped': len(skipped),
        'skipped_winners_discarded': ss['wins'],
        'skipped_losers_discarded': ss['losses'],
        'skipped_flats_discarded': ss['flats'],
        'skipped_baseline_r_discarded': skipped_r,
        'skipped_baseline_r_per_setup': round(skipped_r / len(skipped), 3) if skipped else None,
        'skipped_baseline_win_rate_pct': ss['win_rate_pct'],
        'counterfactual_labels': outcome_split(kept) if label_key else None,
        'entry_diff_points': mean_ci(diffs),
    }


def family_block(rows, family):
    """All the Phase-3 numbers for one family of one book."""
    f = [r for r in rows if r.get('setup_family') == family]
    if not f:
        return None
    ok = [r for r in f if r.get('observation_status') == 'OK']
    censored = [r for r in f if r.get('observation_status') != 'OK']
    censor_reasons = {}
    for r in censored:
        k = r.get('censor_reason') or r.get('observation_status')
        censor_reasons[k] = censor_reasons.get(k, 0) + 1

    ret = [r for r in ok if r.get('return_observed')]
    noret = [r for r in ok if not r.get('return_observed')]
    conf = [r for r in ok if r.get('rejection_at_or_after_return')]
    conf_strict = [r for r in ok if r.get('rejection_after_return')]
    conf_ret = [r for r in ret if r.get('rejection_at_or_after_return')]

    ret_out = outcome_split(ret)
    noret_out = outcome_split(noret)
    a = ret_out['wins']
    b = ret_out['losses']
    c = noret_out['wins']
    d = noret_out['losses']

    block = {
        'family': family,
        'eligible_signals': len(f),
        'complete_observations': len(ok),
        'censored_observations': len(censored),
        'censor_reasons': censor_reasons,
        'returned_12b': len(ret),
        'return_freq_pct': wilson(len(ret), len(ok)),
        'return_freq_bootstrap_pct': boot_proportion(len(ret), len(ok)),
        'not_returned': len(noret),
        'confirmed_at_or_after_return': len(conf),
        'confirmed_strictly_after_return': len(conf_strict),
        'confirm_freq_of_all_complete_pct': wilson(len(conf), len(ok)),
        'confirm_freq_of_returned_pct': wilson(len(conf), len(ret)),
        'confirmed_bootstrap_pct': boot_proportion(len(conf), len(ok)),
        'outcome_returned': ret_out,
        'outcome_not_returned': noret_out,
        'outcome_discrimination': {
            'win_rate_diff_pct': boot_diff(a, a + b, c, c + d).get('diff_pct'),
            'bootstrap_ci_pct': boot_diff(a, a + b, c, c + d),
            'fisher_p': fisher_exact(a, b, c, d),
            'table': {'returned_win': a, 'returned_loss': b,
                      'not_returned_win': c, 'not_returned_loss': d},
        },
        'filters': {
            'WAIT_RETURN_12B': filter_economics(
                ok, 'filter_return_retained', 'cf_return_r', 'cf_return_label',
                'cf_entry_diff_pts'),
            'WAIT_CONFIRM_AFTER_RETURN': filter_economics(
                ok, 'filter_confirm_retained', 'cf_confirm_r',
                'cf_confirm_label', 'cf_confirm_entry_diff_pts'),
        },
        'excursion': {
            'mfe_pts_from_signal': mean_ci([r.get('mfe_pts_from_signal') for r in ok]),
            'mae_pts_from_signal': mean_ci([r.get('mae_pts_from_signal') for r in ok]),
            'mae_r_from_signal': mean_ci([r.get('mae_r_from_signal') for r in ok]),
            'mfe_pts_after_return': mean_ci([r.get('mfe_pts_after_return') for r in ret]),
            'mae_pts_after_return': mean_ci([r.get('mae_pts_after_return') for r in ret]),
        },
        'baseline': {
            'total_r': r_total(ok),
            'r_per_setup': round(r_total(ok) / len(ok), 3) if ok else None,
            'outcome': outcome_split(ok),
        },
        'levels': {},
        'instruments': {},
        'sessions': {},
    }

    # per level
    for lv in sorted({r.get('setup_level') for r in f if r.get('setup_level')}):
        sub = [r for r in ok if r.get('setup_level') == lv]
        if not sub:
            continue
        subret = [r for r in sub if r.get('return_observed')]
        block['levels'][lv] = {
            'n': len(sub),
            'returned': len(subret),
            'return_freq_pct': wilson(len(subret), len(sub)),
            'confirmed': sum(1 for r in sub if r.get('rejection_at_or_after_return')),
            'outcome': outcome_split(sub),
            'total_r': r_total(sub),
        }

    # per instrument
    for inst in sorted({r.get('instrument') for r in f if r.get('instrument')}):
        sub = [r for r in ok if r.get('instrument') == inst]
        if not sub:
            continue
        subret = [r for r in sub if r.get('return_observed')]
        block['instruments'][inst] = {
            'n': len(sub),
            'returned': len(subret),
            'return_freq_pct': wilson(len(subret), len(sub)),
            'confirmed': sum(1 for r in sub if r.get('rejection_at_or_after_return')),
            'outcome': outcome_split(sub),
            'total_r': r_total(sub),
            'r_per_setup': round(r_total(sub) / len(sub), 3),
            'filters': {
                'WAIT_RETURN_12B': filter_economics(
                    sub, 'filter_return_retained', 'cf_return_r', 'cf_return_label',
                    'cf_entry_diff_pts'),
                'WAIT_CONFIRM_AFTER_RETURN': filter_economics(
                    sub, 'filter_confirm_retained', 'cf_confirm_r',
                    'cf_confirm_label', 'cf_confirm_entry_diff_pts'),
            },
        }

    # per session
    for day in sorted({r.get('session_date') for r in f if r.get('session_date')}):
        sub = [r for r in ok if r.get('session_date') == day]
        if not sub:
            continue
        subret = [r for r in sub if r.get('return_observed')]
        block['sessions'][day] = {
            'n': len(sub),
            'returned': len(subret),
            'confirmed': sum(1 for r in sub if r.get('rejection_at_or_after_return')),
            'wins': sum(1 for r in sub if r.get('outcome_label') == 'WIN'),
            'losses': sum(1 for r in sub if r.get('outcome_label') == 'LOSS'),
            'total_r': r_total(sub),
        }
    return block


# ---------------------------------------------------------------- main -----
def main():
    src = os.path.join(C.OUT_DIR, 'shadow_annotations.json')
    data = json.load(open(src))
    rows = data['annotations']

    results = {
        'generated_at': datetime.now().isoformat(timespec='seconds'),
        'source': src,
        'constants': {'return_window_bars': C.RETURN_WINDOW_BARS},
        'books': {},
    }

    for book in C.BOARDS:
        brows = [r for r in rows if r.get('book') == book]
        if not brows:
            continue
        blk = {}
        for fam in C.FAMILIES:
            b = family_block(brows, fam)
            if b:
                blk[fam] = b
        # an "all families" roll-up (ignoring the family split)
        ok = [r for r in brows if r.get('observation_status') == 'OK']
        ret = [r for r in ok if r.get('return_observed')]
        blk['ALL'] = {
            'family': 'ALL',
            'eligible_signals': len(brows),
            'complete_observations': len(ok),
            'censored_observations': len(brows) - len(ok),
            'returned_12b': len(ret),
            'return_freq_pct': wilson(len(ret), len(ok)),
            'return_freq_bootstrap_pct': boot_proportion(len(ret), len(ok)),
            'confirmed_at_or_after_return': sum(
                1 for r in ok if r.get('rejection_at_or_after_return')),
            'outcome_returned': outcome_split(ret),
            'outcome_not_returned': outcome_split(
                [r for r in ok if not r.get('return_observed')]),
            'baseline': {'total_r': r_total(ok),
                         'r_per_setup': round(r_total(ok) / len(ok), 3) if ok else None,
                         'outcome': outcome_split(ok)},
            'filters': {
                'WAIT_RETURN_12B': filter_economics(
                    ok, 'filter_return_retained', 'cf_return_r', 'cf_return_label',
                    'cf_entry_diff_pts'),
                'WAIT_CONFIRM_AFTER_RETURN': filter_economics(
                    ok, 'filter_confirm_retained', 'cf_confirm_r',
                    'cf_confirm_label', 'cf_confirm_entry_diff_pts'),
            },
        }
        results['books'][book] = blk

    with open(os.path.join(C.OUT_DIR, 'shadow_results.json'), 'w') as fh:
        json.dump(results, fh, indent=2, sort_keys=True, default=str)

    # ---- the TOUCH / BREAK comparison CSV
    out_rows = []
    for book, blk in results['books'].items():
        for scope, key in (('FAMILY', 'TOUCH'), ('FAMILY', 'BREAK'),
                           ('FAMILY', 'BREAKOUT'), ('ALL', 'ALL')):
            b = blk.get(key)
            if not b:
                continue
            row = {'scope': scope, 'book': book, 'group': key}
            row.update({
                'eligible_signals': b.get('eligible_signals'),
                'complete_observations': b.get('complete_observations'),
                'censored_observations': b.get('censored_observations'),
                'returned_12b': b.get('returned_12b'),
                'return_freq_pct': (b.get('return_freq_pct') or {}).get('pct'),
                'return_freq_lo_pct': (b.get('return_freq_pct') or {}).get('lo'),
                'return_freq_hi_pct': (b.get('return_freq_pct') or {}).get('hi'),
                'return_freq_bootstrap_lo_pct': (b.get('return_freq_bootstrap_pct') or {}).get('lo'),
                'return_freq_bootstrap_hi_pct': (b.get('return_freq_bootstrap_pct') or {}).get('hi'),
                'confirmed_at_or_after_return': b.get('confirmed_at_or_after_return'),
                'confirm_freq_of_complete_pct': (b.get('confirm_freq_of_all_complete_pct') or {}).get('pct'),
                'confirm_freq_of_returned_pct': (b.get('confirm_freq_of_returned_pct') or {}).get('pct'),
                'returned_wins': (b.get('outcome_returned') or {}).get('wins'),
                'returned_losses': (b.get('outcome_returned') or {}).get('losses'),
                'returned_win_rate_pct': (b.get('outcome_returned') or {}).get('win_rate_pct'),
                'not_returned_wins': (b.get('outcome_not_returned') or {}).get('wins'),
                'not_returned_losses': (b.get('outcome_not_returned') or {}).get('losses'),
                'not_returned_win_rate_pct': (b.get('outcome_not_returned') or {}).get('win_rate_pct'),
                'outcome_win_rate_diff_pct': (b.get('outcome_discrimination') or {}).get('win_rate_diff_pct'),
                'outcome_diff_ci_lo_pct': ((b.get('outcome_discrimination') or {}).get('bootstrap_ci_pct') or {}).get('lo'),
                'outcome_diff_ci_hi_pct': ((b.get('outcome_discrimination') or {}).get('bootstrap_ci_pct') or {}).get('hi'),
                'fisher_p': (b.get('outcome_discrimination') or {}).get('fisher_p'),
                'baseline_total_r': (b.get('baseline') or {}).get('total_r'),
                'baseline_r_per_setup': (b.get('baseline') or {}).get('r_per_setup'),
                'baseline_win_rate_pct': ((b.get('baseline') or {}).get('outcome') or {}).get('win_rate_pct'),
                'filter_return_retained': ((b.get('filters') or {}).get('WAIT_RETURN_12B') or {}).get('retained'),
                'filter_return_retained_win_rate_pct': ((b.get('filters') or {}).get('WAIT_RETURN_12B') or {}).get('retained_win_rate_pct'),
                'filter_return_total_r': ((b.get('filters') or {}).get('WAIT_RETURN_12B') or {}).get('retained_total_r'),
                'filter_return_r_per_trade': ((b.get('filters') or {}).get('WAIT_RETURN_12B') or {}).get('retained_r_per_trade'),
                'filter_return_skipped_winners': ((b.get('filters') or {}).get('WAIT_RETURN_12B') or {}).get('skipped_winners_discarded'),
                'filter_return_skipped_losses': ((b.get('filters') or {}).get('WAIT_RETURN_12B') or {}).get('skipped_losers_discarded'),
                'filter_return_skipped_r': ((b.get('filters') or {}).get('WAIT_RETURN_12B') or {}).get('skipped_baseline_r_discarded'),
                'filter_return_entry_diff_mean_pts': (((b.get('filters') or {}).get('WAIT_RETURN_12B') or {}).get('entry_diff_points') or {}).get('mean'),
                'filter_return_entry_diff_median_pts': (((b.get('filters') or {}).get('WAIT_RETURN_12B') or {}).get('entry_diff_points') or {}).get('median'),
                'filter_confirm_retained': ((b.get('filters') or {}).get('WAIT_CONFIRM_AFTER_RETURN') or {}).get('retained'),
                'filter_confirm_retained_win_rate_pct': ((b.get('filters') or {}).get('WAIT_CONFIRM_AFTER_RETURN') or {}).get('retained_win_rate_pct'),
                'filter_confirm_total_r': ((b.get('filters') or {}).get('WAIT_CONFIRM_AFTER_RETURN') or {}).get('retained_total_r'),
                'filter_confirm_r_per_trade': ((b.get('filters') or {}).get('WAIT_CONFIRM_AFTER_RETURN') or {}).get('retained_r_per_trade'),
                'filter_confirm_skipped_winners': ((b.get('filters') or {}).get('WAIT_CONFIRM_AFTER_RETURN') or {}).get('skipped_winners_discarded'),
                'filter_confirm_skipped_losses': ((b.get('filters') or {}).get('WAIT_CONFIRM_AFTER_RETURN') or {}).get('skipped_losers_discarded'),
                'filter_confirm_skipped_r': ((b.get('filters') or {}).get('WAIT_CONFIRM_AFTER_RETURN') or {}).get('skipped_baseline_r_discarded'),
                'filter_confirm_entry_diff_mean_pts': (((b.get('filters') or {}).get('WAIT_CONFIRM_AFTER_RETURN') or {}).get('entry_diff_points') or {}).get('mean'),
                'filter_confirm_entry_diff_median_pts': (((b.get('filters') or {}).get('WAIT_CONFIRM_AFTER_RETURN') or {}).get('entry_diff_points') or {}).get('median'),
            })
            out_rows.append(row)

    csv_path = os.path.join(C.OUT_DIR, 'touch_break_comparison.csv')
    with open(csv_path, 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=list(out_rows[0].keys()))
        w.writeheader()
        for r in out_rows:
            w.writerow(r)

    # ---- console summary
    for book, blk in results['books'].items():
        print('\n==', book)
        for fam in ('TOUCH', 'BREAK', 'BREAKOUT', 'ALL'):
            b = blk.get(fam)
            if not b:
                continue
            rf = b.get('return_freq_pct') or {}
            print('  %-9s n=%3d ok=%3d ret=%3d (%s%%, CI %s-%s) conf=%3d '
                  'wr_ret=%s%% wr_noret=%s%% fisher=%s baseR=%s'
                  % (fam, b.get('eligible_signals'),
                     b.get('complete_observations'), b.get('returned_12b'),
                     rf.get('pct'), rf.get('lo'), rf.get('hi'),
                     b.get('confirmed_at_or_after_return'),
                     (b.get('outcome_returned') or {}).get('win_rate_pct'),
                     (b.get('outcome_not_returned') or {}).get('win_rate_pct'),
                     (b.get('outcome_discrimination') or {}).get('fisher_p'),
                     (b.get('baseline') or {}).get('total_r')))
    print('\nwrote', csv_path)
    return results


if __name__ == '__main__':
    main()
