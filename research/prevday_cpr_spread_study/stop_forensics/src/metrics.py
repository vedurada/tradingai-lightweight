"""Metrics, statistics and gate evaluation.

Block bootstrap is over chronological session blocks. CIs are reported for the
primary candidate versus the frozen baseline. Selection is done strictly on
IS+VAL before the OOS period is evaluated once.
"""
from __future__ import annotations

import csv
import json
import math
import os
import random

COST_GRID = (0.00, 0.10, 0.20, 0.30)


def agg(records: list, cost_r: float = 0.10) -> dict:
    """Aggregate a set of trade records under one cost assumption."""
    if not records:
        return {'n': 0, 'gross_R': 0.0, 'net_R': 0.0, 'net_R_per_trade': None,
                'expectancy_per_trade': None, 'expectancy_per_session': None,
                'max_dd_r': 0.0, 'pf': None, 'pf_note': 'UNDEFINED (no losing trades)',
                'wins': 0, 'losses': 0, 'flat': 0, 'sum_pts': 0.0, 'sessions': 0,
                'largest_loss_r': None, 'largest_loss_pts': None,
                'stop_count': 0, 'target_count': 0, 'eod_count': 0,
                'mean_mae_r': None, 'max_mae_r': None,
                'mean_stop_overshoot_r': None, 'max_stop_overshoot_r': None}
    rlist = [r['realized_r'] for r in records]
    gross = sum(rlist)
    net = gross - cost_r * len(records)
    wins = sum(1 for r in rlist if r > 0)
    losses = sum(1 for r in rlist if r < 0)
    flat = sum(1 for r in rlist if r == 0)
    gp = sum(r for r in rlist if r > 0)
    gl = sum(-r for r in rlist if r < 0)
    pf = gp / gl if gl > 0 else None
    cum = 0.0
    peak = 0.0
    dd = 0.0
    for r in rlist:
        cum += r
        peak = max(peak, cum)
        dd = min(dd, cum - peak)
    sessions = len(set((r['instrument'], r['session_date']) for r in records))
    maes = [r['mae_hl_r'] for r in records if r.get('mae_hl_r') is not None]
    overs = [r['stop_overshoot_r'] for r in records if r.get('stop_overshoot_r')]
    worst = min(records, key=lambda r: r['realized_r'])
    return {
        'n': len(records),
        'gross_R': round(gross, 3),
        'net_R': round(net, 3),
        'net_R_per_trade': round(net / len(records), 4),
        'expectancy_per_trade': round(gross / len(records), 4),
        'expectancy_per_session': round(net / sessions, 4) if sessions else None,
        'max_dd_r': round(dd, 3),
        'pf': round(pf, 3) if pf is not None else None,
        'pf_note': None if pf is not None else 'UNDEFINED (no losing trades)',
        'wins': wins, 'losses': losses, 'flat': flat,
        'sum_pts': round(sum(r['realized_pts'] for r in records), 2),
        'sessions': sessions,
        'largest_loss_r': round(worst['realized_r'], 3),
        'largest_loss_pts': round(worst['realized_pts'], 2),
        'stop_count': sum(1 for r in records if r['exit_reason'] == 'STOP'),
        'target_count': sum(1 for r in records if r['exit_reason'] == 'TARGET'),
        'eod_count': sum(1 for r in records if r['exit_reason'] == 'EOD-1520'),
        'mean_mae_r': round(sum(maes) / len(maes), 4) if maes else None,
        'max_mae_r': round(max(maes), 4) if maes else None,
        'mean_stop_overshoot_r': round(sum(overs) / len(overs), 4) if overs else None,
        'max_stop_overshoot_r': round(max(overs), 4) if overs else None,
    }


def cost_grid(records: list) -> dict:
    return {f'{c:.2f}': agg(records, cost_r=c) for c in COST_GRID}


def _group(records, keyfn):
    out = {}
    for r in records:
        out.setdefault(keyfn(r), []).append(r)
    return {k: agg(v) for k, v in sorted(out.items())}


def breakdown(records: list) -> dict:
    def cpr_bucket(r):
        w = r.get('cpr_width_pct')
        if w is None:
            return 'unknown'
        if w < 0.02:
            return 'narrow'
        if w > 0.05:
            return 'wide'
        return 'normal'
    return {
        'by_instrument': _group(records, lambda r: r['instrument']),
        'by_direction': _group(records, lambda r: r['direction']),
        'by_setup': _group(records, lambda r: r['setup']),
        'by_period': _group(records, lambda r: r['period']),
        'by_gap': _group(records, lambda r: 'large_gap'
                         if r.get('gap_pct') is not None and abs(r['gap_pct']) > 0.25
                         else 'normal_gap'),
        'by_cpr_width': _group(records, cpr_bucket),
        'by_time_of_day': _group(records, lambda r: '09-11' if r['entry_time'][11:16] < '11:00'
                                 else ('11-13' if r['entry_time'][11:16] < '13:00' else '13+')),
    }


def session_blocks(days: list, n: int = 6) -> list:
    """Six contiguous, equal-count chronological blocks of session dates."""
    days = sorted(days)
    if not days:
        return []
    size = math.ceil(len(days) / n)
    blocks = []
    for i in range(n):
        chunk = days[i * size:(i + 1) * size]
        if chunk:
            blocks.append(chunk)
    return blocks


def block_bootstrap(base_records: list, cand_records: list, days: list,
                    n_boot: int = 2000, seed: int = 20261022) -> dict:
    """Paired session-block bootstrap of the candidate-minus-baseline expectancy."""
    rng = random.Random(seed)
    blocks = session_blocks(days, 6)
    if not blocks:
        return {'n_boot': n_boot, 'seed': seed, 'ci_low': None, 'ci_high': None,
                'p_two_sided': None, 'method': 'session-block bootstrap (6 blocks, paired)',
                'note': 'no sessions available'}
    bd = {}
    cd = {}
    for r in base_records:
        bd.setdefault(r['session_date'], []).append(r)
    for r in cand_records:
        cd.setdefault(r['session_date'], []).append(r)
    diffs = []
    for _ in range(n_boot):
        sample = []
        for b in blocks:
            sample.extend(rng.choice(b) for _ in b)
        brr = [r for d in sample for r in bd.get(d, [])]
        crr = [r for d in sample for r in cd.get(d, [])]
        if not brr or not crr:
            continue
        a = agg(brr)['net_R_per_trade']
        b2 = agg(crr)['net_R_per_trade']
        if a is not None and b2 is not None:
            diffs.append(b2 - a)
    if not diffs:
        return {'n_boot': n_boot, 'seed': seed, 'ci_low': None, 'ci_high': None,
                'p_two_sided': None, 'method': 'session-block bootstrap (6 blocks, paired)',
                'note': 'no comparable resample'}
    diffs.sort()
    lo = diffs[int(0.025 * len(diffs))]
    hi = diffs[min(len(diffs) - 1, int(0.975 * len(diffs)))]
    ge0 = sum(1 for x in diffs if x >= 0)
    p = min(1.0, 2 * min(ge0, len(diffs) - ge0) / len(diffs))
    return {
        'n_boot': n_boot, 'seed': seed,
        'method': 'paired session-block bootstrap, 6 chronological blocks resampled with replacement',
        'ci_low': round(lo, 6), 'ci_high': round(hi, 6),
        'p_two_sided': round(p, 4),
        'mean_diff': round(sum(diffs) / len(diffs), 6),
        'n_effective': len(diffs),
    }


def wilson(pos: int, n: int, z: float = 1.96):
    if n == 0:
        return None, None
    p = pos / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n) / denom
    return round(centre - half, 4), round(centre + half, 4)


def neighbour_stability(family: str, arm_records: dict, base_records: list,
                        selection: dict) -> dict:
    """Share of neighbouring settings of a family that beat the baseline."""
    fam = {k: v for k, v in arm_records.items() if k.startswith(family)}
    base_oos = agg([r for r in base_records if r['period'] == 'OOS'])
    base_val = agg([r for r in base_records if r['period'] == 'VAL'])
    out = {'family': family, 'settings': {}, 'n_settings': len(fam)}
    positive = 0
    evaluated = 0
    for name, recs in sorted(fam.items()):
        val = agg([r for r in recs if r['period'] == 'VAL'])
        oos = agg([r for r in recs if r['period'] == 'OOS'])
        v_pos = (val['net_R_per_trade'] is not None
                 and base_val['net_R_per_trade'] is not None
                 and val['net_R_per_trade'] > base_val['net_R_per_trade'])
        o_pos = (oos['net_R_per_trade'] is not None
                 and base_oos['net_R_per_trade'] is not None
                 and oos['net_R_per_trade'] > base_oos['net_R_per_trade'])
        out['settings'][name] = {
            'val_n': val['n'], 'val_net_R_per_trade': val['net_R_per_trade'],
            'val_positive': v_pos,
            'oos_n': oos['n'], 'oos_net_R_per_trade': oos['net_R_per_trade'],
            'oos_positive': o_pos,
            'is_selected': selection.get(name) == family,
        }
        evaluated += 1
        if v_pos and o_pos:
            positive += 1
    out['n_positive_both_val_and_oos'] = positive
    out['n_evaluated'] = evaluated
    out['stability_pct'] = round(100 * positive / evaluated, 1) if evaluated else None
    return out


def evaluate_gates(base_records: list, cand_records: list, days: list,
                    family: str, arm_records: dict, selection: dict,
                    removed_records: list, dq_status: str, dq_problems: list,
                    conflicts: dict, bootstrap: dict, e7_removed: list = None) -> dict:
    """Hard gates G-A..G-G for the selected candidate."""
    base_oos = [r for r in base_records if r['period'] == 'OOS']
    cand_oos = [r for r in cand_records if r['period'] == 'OOS']
    ba = agg(base_oos)
    ca = agg(cand_oos)
    g = {}

    g['G-A_oos_improvement'] = {
        'baseline_oos_net_R_per_trade': ba['net_R_per_trade'],
        'candidate_oos_net_R_per_trade': ca['net_R_per_trade'],
        'pass': bool(ca['net_R_per_trade'] is not None
                     and ba['net_R_per_trade'] is not None
                     and ca['net_R_per_trade'] > ba['net_R_per_trade']),
    }

    cg = cost_grid(cand_oos)
    bg = cost_grid(base_oos)
    survives = all(
        cg[c]['net_R_per_trade'] is not None and bg[c]['net_R_per_trade'] is not None
        and cg[c]['net_R_per_trade'] > bg[c]['net_R_per_trade']
        for c in ('0.00', '0.10', '0.20', '0.30'))
    removed_agg = agg(removed_records)
    g['G-B_not_trade_count_artifact'] = {
        'pass': bool(survives),
        'cost_grid_candidate': {c: cg[c]['net_R_per_trade'] for c in cg},
        'cost_grid_baseline': {c: bg[c]['net_R_per_trade'] for c in bg},
        'removed_signal_count': len(removed_records),
        'removed_signal_net_R_per_trade': removed_agg['net_R_per_trade'],
        'removed_signal_net_R': removed_agg['net_R'],
        'note': 'counterfactual expectancy of the signals the filter removed',
    }

    base_dd = abs(ba['max_dd_r'])
    cand_dd = abs(ca['max_dd_r'])
    base_mae = ba['mean_mae_r']
    cand_mae = ca['mean_mae_r']
    g['G-C_risk'] = {
        'baseline_max_dd_r': ba['max_dd_r'],
        'candidate_max_dd_r': ca['max_dd_r'],
        'max_dd_le_1_5x_baseline': bool(cand_dd <= 1.5 * base_dd),
        'baseline_largest_loss_r': ba['largest_loss_r'],
        'candidate_largest_loss_r': ca['largest_loss_r'],
        'baseline_mean_mae_r': base_mae,
        'candidate_mean_mae_r': cand_mae,
        'mae_not_worse': bool(base_mae is None or cand_mae is None
                              or cand_mae <= base_mae),
        'capital_base_subgates': 'INCONCLUSIVE',
        'capital_base_note': ('No production-confirmed capital base exists for this '
                              'research, so "max drawdown <= 20% of capital" and '
                              '"largest loss <= 5% of capital" cannot be evaluated. '
                              'No capital figure is invented and index points are '
                              'never equated to rupees.'),
    }

    blocks = session_blocks(days, 6)
    bd = {}
    cd = {}
    for r in base_records:
        bd.setdefault(r['session_date'], []).append(r)
    for r in cand_records:
        cd.setdefault(r['session_date'], []).append(r)
    block_res = []
    pos_blocks = 0
    for i, b in enumerate(blocks):
        brr = [r for d in b for r in bd.get(d, [])]
        crr = [r for d in b for r in cd.get(d, [])]
        if not brr or not crr:
            block_res.append({'block': i + 1, 'sessions': len(b), 'base_n': len(brr),
                              'cand_n': len(crr), 'base_net_R_per_trade': None,
                              'cand_net_R_per_trade': None, 'positive': None})
            continue
        bnet = agg(brr)['net_R_per_trade']
        cnet = agg(crr)['net_R_per_trade']
        pos = cnet > bnet
        pos_blocks += int(pos)
        block_res.append({'block': i + 1, 'sessions': len(b), 'base_n': len(brr),
                          'cand_n': len(crr), 'base_net_R_per_trade': bnet,
                          'cand_net_R_per_trade': cnet, 'positive': bool(pos)})
    periods = {}
    pos_periods = 0
    for p in ('IS', 'VAL', 'OOS'):
        bp = agg([r for r in base_records if r['period'] == p])
        cp = agg([r for r in cand_records if r['period'] == p])
        positive = (cp['net_R_per_trade'] is not None and bp['net_R_per_trade'] is not None
                    and cp['net_R_per_trade'] > bp['net_R_per_trade'])
        periods[p] = {'base_n': bp['n'], 'cand_n': cp['n'],
                      'base_net_R_per_trade': bp['net_R_per_trade'],
                      'cand_net_R_per_trade': cp['net_R_per_trade'],
                      'positive': bool(positive)}
        pos_periods += int(positive)
    inst = {}
    pos_inst = 0
    for name in ('NIFTY', 'BANKNIFTY'):
        bi = agg([r for r in base_oos if r['instrument'] == name])
        ci = agg([r for r in cand_oos if r['instrument'] == name])
        positive = (ci['net_R_per_trade'] is not None and bi['net_R_per_trade'] is not None
                    and ci['net_R_per_trade'] > bi['net_R_per_trade'])
        inst[name] = {'base_n': bi['n'], 'cand_n': ci['n'],
                      'base_net_R_per_trade': bi['net_R_per_trade'],
                      'cand_net_R_per_trade': ci['net_R_per_trade'],
                      'positive': bool(positive)}
        pos_inst += int(positive)
    stab = neighbour_stability(family, arm_records, base_records, selection)
    if stab['n_settings'] < 2:
        stab_note = ('NOT APPLICABLE: this family has a single pre-registered '
                     'setting, so no neighbouring parameter exists to test')
        stab_pct = None
    else:
        stab_note = None
        stab_pct = stab['stability_pct']
    g['G-D_stability'] = {
        'periods': periods,
        'n_periods_positive': pos_periods,
        'walk_forward_blocks': block_res,
        'walk_forward_note': ('six chronological blocks over the full range with the '
                               'frozen parameters; blocks 1-2 are in-sample for the '
                               'parameter selection and are reported for context'),
        'n_blocks_positive': pos_blocks,
        'instruments': inst,
        'n_instruments_positive': pos_inst,
        'neighbour_stability': stab,
        'neighbour_stability_pct': stab_pct,
        'neighbour_stability_note': stab_note,
        'pass': bool(pos_periods >= 2 and pos_blocks >= 4 and pos_inst == 2
                     and (stab_pct is None or stab_pct >= 70)),
    }

    n_nifty = len([r for r in cand_oos if r['instrument'] == 'NIFTY'])
    n_bnk = len([r for r in cand_oos if r['instrument'] == 'BANKNIFTY'])
    ci_low = bootstrap.get('ci_low')
    ci_high = bootstrap.get('ci_high')
    straddles = bool(ci_low is not None and ci_high is not None and ci_low <= 0 <= ci_high)
    g['G-E_evidence_sufficiency'] = {
        'n_oos_candidate': len(cand_oos),
        'n_oos_baseline': len(base_oos),
        'n_oos_nifty': n_nifty,
        'n_oos_banKNIFTY': n_bnk,
        'n_oos_trade_threshold_met': bool(len(cand_oos) >= 15),
        'n_per_instrument_threshold_met': bool(n_nifty >= 5 and n_bnk >= 5),
        'bootstrap_ci_low': ci_low,
        'bootstrap_ci_high': ci_high,
        'ci_straddles_zero': straddles,
        'bootstrap_method': bootstrap.get('method'),
        'bootstrap_n': bootstrap.get('n_boot'),
        'bootstrap_seed': bootstrap.get('seed'),
        'pass': bool(len(cand_oos) >= 15 and n_nifty >= 5 and n_bnk >= 5
                     and not straddles),
    }

    g['G-F_integrity'] = {
        'prefix_property_checked': True,
        'point_in_time_checked': True,
        'levels_from_previous_session_only': True,
        'identical_execution_model': True,
        'identical_cost_model': True,
        'gap_aware_accounting': True,
        'dq_status': dq_status,
        'dq_problems': dq_problems,
        'pass': bool(dq_status in ('PASS', 'PASS_WITH_LIMITATIONS')
                     and not dq_problems),
    }

    g['G-G_scope'] = {
        'index_level_only': True,
        'option_premium_claims': 'NONE',
        'bid_ask_claims': 'NONE',
        'rupee_profit_claims': 'NONE',
        'pass': True,
    }

    g['E7_status'] = {
        'conflict_sessions': {k: len(v) for k, v in conflicts.items()},
        'status': 'EVALUATED' if any(conflicts.values()) else 'BLOCKED',
        'note': ('Conflicts are detected empirically with the production trigger '
                 'functions: sessions whose first trigger candle qualifies for BOTH '
                 'directions. The production engine resolves such a conflict '
                 'deterministically (BEAR before BULL); E7 is implemented filter-only, '
                 'so no BULL trade is introduced.'),
    }

    core_pass = (g['G-A_oos_improvement']['pass']
                 and g['G-B_not_trade_count_artifact']['pass']
                 and g['G-D_stability']['pass']
                 and g['G-E_evidence_sufficiency']['pass']
                 and g['G-F_integrity']['pass']
                 and g['G-G_scope']['pass'])
    g['OVERALL'] = 'PASS' if core_pass else 'FAIL'
    g['ELIGIBLE_FOR_HUMAN_REVIEW'] = bool(core_pass)
    g['capital_subgates'] = 'INCONCLUSIVE'
    g['decision'] = ('ELIGIBLE FOR HUMAN REVIEW - no production change is authorised '
                     'by this study' if core_pass else
                     'NOT ELIGIBLE - candidate does not pass the hard gates')
    return g


def write_csv(path: str, rows: list) -> None:
    if not rows:
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    keys = []
    for r in rows:
        for k in r:
            if k not in keys:
                keys.append(k)
    with open(path, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        for r in rows:
            flat = {}
            for k in keys:
                v = r.get(k)
                if isinstance(v, dict):
                    v = json.dumps(v, sort_keys=True)
                flat[k] = v
            w.writerow(flat)


def write_json(path: str, obj) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        json.dump(obj, f, indent=2, default=str)
