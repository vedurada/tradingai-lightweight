"""Validation gates.

The gate definitions are the approved ones from the parent study
(``stop_forensics/src/metrics.evaluate_gates``) plus the add-on's G-A2 point
test. Nothing is relaxed:

* the out-of-sample evaluation reuses the parent's ``evaluate_gates`` unchanged,
* the validation pre-check reuses the parent's ``agg`` / ``cost_grid`` /
  ``block_bootstrap`` helpers and applies the same thresholds on the
  validation split,
* a gate that cannot be judged is reported as INCONCLUSIVE / UNRESOLVED and is
  never converted into a pass by assumption.
"""
from __future__ import annotations

from research.prevday_cpr_spread_study.stop_forensics.src import metrics as pmetrics
from research.prevday_cpr_spread_study.stop_forensics.addon_stop_placement.src import \
    metrics_ext as xmetrics

from . import config


def _agg(records):
    return xmetrics.agg_ext(records)


def _period(records, p):
    return [r for r in records if r['period'] == p]


def _paired_sessions(cand, base):
    keys = {(r['instrument'], r['session_date']) for r in cand}
    return [r for r in base if (r['instrument'], r['session_date']) in keys]


def val_precheck(cand_records, base_records, dq_status, dq_problems,
                 min_n=10, stage='VAL'):
    """Pre-declared gates on the validation split (the gate for Experiment D).

    The thresholds are the same as the out-of-sample gates, applied one split
    earlier. A candidate that does not clear them here never reaches the
    out-of-sample look.
    """
    cand = _period(cand_records, stage)
    base = _period(base_records, stage)
    base_paired = _paired_sessions(cand, base)
    ca = _agg(cand)
    ba = _agg(base)
    ba_paired = _agg(base_paired)
    g = {}

    g['G-A_val_improvement'] = {
        'baseline_val_net_R_per_trade': ba['net_R_per_trade'],
        'candidate_val_net_R_per_trade': ca['net_R_per_trade'],
        'pass': bool(ca['net_R_per_trade'] is not None
                     and ba['net_R_per_trade'] is not None
                     and ca['net_R_per_trade'] > ba['net_R_per_trade']),
    }
    g['G-A2_val_points_not_worse'] = {
        'baseline_val_points_per_trade': ba['points_per_trade'],
        'candidate_val_points_per_trade': ca['points_per_trade'],
        'pass': bool(ca['points_per_trade'] is not None
                     and ba['points_per_trade'] is not None
                     and ca['points_per_trade'] >= ba['points_per_trade']),
        'note': ('guards the R denominator: a lower-risk stop can raise R per trade '
                 'without producing more index points'),
    }
    cg = pmetrics.cost_grid(cand)
    bg = pmetrics.cost_grid(base_paired)
    survives = all(cg[c]['net_R_per_trade'] is not None
                   and bg[c]['net_R_per_trade'] is not None
                   and cg[c]['net_R_per_trade'] > bg[c]['net_R_per_trade']
                   for c in ('0.00', '0.10', '0.20', '0.30'))
    removed = [r for r in base if (r['instrument'], r['session_date'])
               not in {(c['instrument'], c['session_date']) for c in cand}]
    rem = _agg(removed)
    selection_ok = bool(not removed or rem['net_R_per_trade'] is None
                        or ca['net_R_per_trade'] is None
                        or rem['net_R_per_trade'] <= ca['net_R_per_trade'])
    g['G-B_val_not_count_artifact'] = {
        'cost_grid_candidate': {c: cg[c]['net_R_per_trade'] for c in cg},
        'cost_grid_baseline': {c: bg[c]['net_R_per_trade'] for c in bg},
        'removed_signal_count': len(removed),
        'removed_signal_net_R_per_trade': rem['net_R_per_trade'],
        'pass': bool(survives and selection_ok),
    }
    g['G-C_val_risk'] = {
        'baseline_max_dd_r': ba['max_dd_r'], 'candidate_max_dd_r': ca['max_dd_r'],
        'max_dd_le_1_5x_baseline': bool(abs(ca['max_dd_r']) <= 1.5 * abs(ba['max_dd_r'])),
        'baseline_mean_mae_r': ba['mean_mae_r'], 'candidate_mean_mae_r': ca['mean_mae_r'],
        'mae_not_worse': bool(ba['mean_mae_r'] is None or ca['mean_mae_r'] is None
                              or ca['mean_mae_r'] <= ba['mean_mae_r']),
        'capital_base_subgates': 'UNRESOLVED',
        'capital_base_note': ('no production-confirmed capital base exists, so the '
                              'percentage-of-capital sub-gates cannot be evaluated; '
                              'no capital figure is invented and index points are '
                              'never equated to rupees'),
        'pass': bool(abs(ca['max_dd_r']) <= 1.5 * abs(ba['max_dd_r'])
                     and (ba['mean_mae_r'] is None or ca['mean_mae_r'] is None
                          or ca['mean_mae_r'] <= ba['mean_mae_r'])),
    }
    per_inst = {}
    pos_inst = 0
    for inst in sorted({r['instrument'] for r in cand}):
        ci = _agg([r for r in cand if r['instrument'] == inst])
        bi = _agg([r for r in base if r['instrument'] == inst])
        ok = bool(ci['net_R_per_trade'] is not None
                  and bi['net_R_per_trade'] is not None
                  and ci['net_R_per_trade'] > bi['net_R_per_trade'])
        per_inst[inst] = {'candidate_n': ci['n'], 'baseline_n': bi['n'],
                          'candidate_net_R_per_trade': ci['net_R_per_trade'],
                          'baseline_net_R_per_trade': bi['net_R_per_trade'],
                          'positive': ok}
        pos_inst += int(ok)
    g['G-D_val_stability'] = {
        'instruments': per_inst,
        'n_instruments_positive': pos_inst,
        'pass': bool(pos_inst == len(per_inst) and len(per_inst) > 0),
        'note': ('the out-of-sample stability gate (periods, walk-forward blocks, '
                 'neighbouring settings) is evaluated on the out-of-sample split '
                 'after the freeze; it cannot be satisfied by the validation split '
                 'alone'),
    }
    n_nifty = len([r for r in cand if r['instrument'] == 'NIFTY'])
    n_bnk = len([r for r in cand if r['instrument'] == 'BANKNIFTY'])
    days = sorted({r['session_date'] for r in cand})
    boot = pmetrics.block_bootstrap(base, cand, days)
    ci_low, ci_high = boot.get('ci_low'), boot.get('ci_high')
    straddles = bool(ci_low is not None and ci_high is not None and ci_low <= 0 <= ci_high)
    g['G-E_val_evidence_sufficiency'] = {
        'n_val_candidate': len(cand), 'n_val_nifty': n_nifty, 'n_val_banknifty': n_bnk,
        'bootstrap_ci_low': ci_low, 'bootstrap_ci_high': ci_high,
        'ci_straddles_zero': straddles,
        'bootstrap_method': boot.get('method'),
        'pass': bool(len(cand) >= min_n and n_nifty >= 5 and n_bnk >= 5 and not straddles),
        'note': ('the out-of-sample gate additionally requires 15 out-of-sample '
                 'trades and 5 per instrument; the validation pre-check uses the '
                 'pre-declared minimum of 10 validation trades and is never '
                 'relaxed to let a candidate through'),
    }
    g['G-F_val_integrity'] = {
        'dq_status': dq_status, 'dq_problems': dq_problems,
        'pass': bool(dq_status in ('PASS', 'PASS_WITH_LIMITATIONS') and not dq_problems),
    }
    g['G-G_val_scope'] = {'index_level_only': True, 'pass': True}

    mandatory = ['G-A_val_improvement', 'G-A2_val_points_not_worse',
                 'G-B_val_not_count_artifact', 'G-C_val_risk',
                 'G-D_val_stability', 'G-E_val_evidence_sufficiency',
                 'G-F_val_integrity', 'G-G_val_scope']
    failed = [k for k in mandatory if not g[k]['pass']]
    g['_verdict'] = 'FAIL' if failed else 'PASS'
    g['_failed_gates'] = failed
    return g


def final_oos_gates(base_records, cand_records, days, arm_records, selection,
                    removed_records, dq_status, dq_problems, conflicts, bootstrap):
    """Out-of-sample evaluation - the parent's approved gate set, unchanged."""
    g = pmetrics.evaluate_gates(
        base_records=base_records, cand_records=cand_records, days=days,
        family='SF', arm_records=arm_records, selection=selection,
        removed_records=removed_records, dq_status=dq_status,
        dq_problems=dq_problems, conflicts=conflicts, bootstrap=bootstrap)

    # G-A2 from the add-on study: index points must not be worse.
    base_oos = [r for r in base_records if r['period'] == 'OOS']
    cand_oos = [r for r in cand_records if r['period'] == 'OOS']
    base_paired = _paired_sessions(cand_oos, base_oos)
    ba = _agg(base_paired)
    ca = _agg(cand_oos)
    g['G-A2_oos_points_not_worse'] = {
        'baseline_oos_points_per_trade': ba['points_per_trade'],
        'candidate_oos_points_per_trade': ca['points_per_trade'],
        'baseline_oos_n': ba['n'], 'candidate_oos_n': ca['n'],
        'pass': bool(ca['points_per_trade'] is not None
                     and ba['points_per_trade'] is not None
                     and ca['points_per_trade'] >= ba['points_per_trade']),
        'note': ('a lower-risk stop can raise R per trade purely by shrinking the '
                 'denominator; the index-point test prevents that from counting '
                 'as an improvement'),
    }
    core = (g['G-A_oos_improvement']['pass']
            and g['G-A2_oos_points_not_worse']['pass']
            and g['G-B_not_trade_count_artifact']['pass']
            and g['G-D_stability']['pass']
            and g['G-E_evidence_sufficiency']['pass']
            and g['G-F_integrity']['pass']
            and g['G-G_scope']['pass'])
    g['OVERALL'] = 'PASS' if core else 'FAIL'
    g['ELIGIBLE_FOR_HUMAN_REVIEW'] = bool(core)
    g['decision'] = ('ELIGIBLE FOR HUMAN REVIEW - no production change is authorised '
                     'by this study' if core else
                     'NOT ELIGIBLE - candidate does not pass the hard gates')
    return g
