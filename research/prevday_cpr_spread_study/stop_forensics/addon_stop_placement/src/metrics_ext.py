"""Extended metrics and the add-on gates (spec_addon.md §6, never relaxed)."""
from __future__ import annotations

try:
    from ...src import metrics as pmetrics
    from . import structures
except ImportError:  # pragma: no cover
    import metrics as pmetrics
    import structures


def agg_ext(records: list) -> dict:
    base = pmetrics.agg(records)
    n = len(records)
    if not n:
        base.update({'net_points': 0.0, 'points_per_trade': None, 'stop_out_rate': None,
                     'target_attainment': None, 'avg_loss_r': None, 'avg_loss_pts': None,
                     'largest_loss_pts': None, 'mean_mfe_r': None,
                     'gap_through_stops': 0, 'mean_stop_distance_pct': None})
        return base
    pts = [r['realized_pts'] for r in records]
    stops = [r for r in records if r['exit_reason'] == 'STOP']
    targets = [r for r in records if r['exit_reason'] == 'TARGET']
    losses = [r['realized_r'] for r in records if r['realized_r'] < 0]
    mfes = [r['mfe_hl_r'] for r in records if r.get('mfe_hl_r') is not None]
    dists = [r['stop_distance_pct'] for r in records
             if r.get('stop_distance_pct') is not None]
    base.update({
        'net_points': round(sum(pts), 2),
        'points_per_trade': round(sum(pts) / n, 3),
        'stop_out_rate': round(len(stops) / n, 4),
        'target_attainment': round(len(targets) / n, 4),
        'avg_loss_r': round(sum(losses) / len(losses), 4) if losses else None,
        'avg_loss_pts': (round(sum(r['realized_pts'] for r in records
                                   if r['realized_r'] < 0) / len(losses), 2)
                         if losses else None),
        'largest_loss_pts': (min((r['realized_pts'] for r in records
                                  if r['realized_r'] < 0), default=None)),
        'mean_mfe_r': round(sum(mfes) / len(mfes), 4) if mfes else None,
        'gap_through_stops': sum(1 for r in stops
                                 if (r.get('stop_overshoot_pts') or 0) > 0.011),
        'mean_stop_distance_pct': (round(sum(dists) / len(dists), 6)
                                   if dists else None),
    })
    return base


def by_instrument(records: list) -> dict:
    out = {}
    for inst in sorted({r['instrument'] for r in records}):
        out[inst] = agg_ext([r for r in records if r['instrument'] == inst])
    return out


def by_period(records: list) -> dict:
    return {p: agg_ext([r for r in records if r['period'] == p])
            for p in ('IS', 'VAL', 'OOS')}


def paired(reference: list, variant_rows: list) -> list:
    """The reference arm restricted to the signals the variant actually trades."""
    keys = {r['signal_key'] for r in variant_rows}
    return [r for r in reference if r['signal_key'] in keys]


def _blocks_positive(days: list, cand: list, base: list, n_blocks: int = 6) -> tuple:
    blocks = pmetrics.session_blocks(days, n_blocks)
    cd, bd = {}, {}
    for r in cand:
        cd.setdefault(r['session_date'], []).append(r)
    for r in base:
        bd.setdefault(r['session_date'], []).append(r)
    out = []
    pos = 0
    for i, b in enumerate(blocks):
        crr = [r for d in b for r in cd.get(d, [])]
        brr = [r for d in b for r in bd.get(d, [])]
        ca = agg_ext(crr)['net_R_per_trade'] if crr else None
        ba = agg_ext(brr)['net_R_per_trade'] if brr else None
        ok = bool(ca is not None and ba is not None and ca > ba)
        pos += int(ok)
        out.append({'block': i + 1, 'sessions': len(b), 'candidate_n': len(crr),
                    'baseline_n': len(brr), 'candidate_net_R_per_trade': ca,
                    'baseline_net_R_per_trade': ba, 'positive': ok})
    return out, pos


def evaluate(variant: str, by_variant: dict, by_variant_ib: dict, days: list,
             dq: dict, ranking_ok: bool, removed_b0: list | None = None) -> dict:
    cand = by_variant[variant]
    base_all = by_variant['B0']
    base_paired = paired(base_all, cand)

    c = by_period(cand)
    b = by_period(base_paired)
    oos_c = [r for r in cand if r['period'] == 'OOS']
    oos_b = [r for r in base_paired if r['period'] == 'OOS']

    ca, ba = agg_ext(oos_c), agg_ext(oos_b)
    g = {}

    # G-A expectancy
    g['G-A_oos_improvement'] = {
        'baseline_oos_net_R_per_trade': ba['net_R_per_trade'],
        'candidate_oos_net_R_per_trade': ca['net_R_per_trade'],
        'baseline_oos_n': ba['n'], 'candidate_oos_n': ca['n'],
        'pass': bool(ca['net_R_per_trade'] is not None
                     and ba['net_R_per_trade'] is not None
                     and ca['net_R_per_trade'] > ba['net_R_per_trade']),
    }
    # G-A2 points (guards the R denominator)
    g['G-A2_oos_points_not_worse'] = {
        'baseline_oos_points_per_trade': ba['points_per_trade'],
        'candidate_oos_points_per_trade': ca['points_per_trade'],
        'pass': bool(ca['points_per_trade'] is not None
                     and ba['points_per_trade'] is not None
                     and ca['points_per_trade'] >= ba['points_per_trade']),
        'note': ('a lower-risk stop can raise R per trade purely by shrinking the '
                 'denominator; the index-point test prevents that from counting as '
                 'an improvement'),
    }
    # G-B cost grid on the paired subset
    cg = pmetrics.cost_grid(oos_c)
    bg = pmetrics.cost_grid(oos_b)
    survives = all(cg[k]['net_R_per_trade'] is not None
                   and bg[k]['net_R_per_trade'] is not None
                   and cg[k]['net_R_per_trade'] > bg[k]['net_R_per_trade']
                   for k in ('0.10', '0.20', '0.30'))
    removed_b0 = removed_b0 or []
    rem_oos = [r for r in removed_b0 if r['period'] == 'OOS']
    rem_agg = agg_ext(rem_oos)
    selection_ok = bool(
        not rem_oos or rem_agg['net_R_per_trade'] is None
        or ca['net_R_per_trade'] is None
        or rem_agg['net_R_per_trade'] <= ca['net_R_per_trade'])
    g['G-B_not_cost_artifact'] = {
        'pass': bool(survives and selection_ok),
        'cost_grid_candidate': {k: cg[k]['net_R_per_trade'] for k in cg},
        'cost_grid_baseline': {k: bg[k]['net_R_per_trade'] for k in bg},
        'removed_signal_count_oos': len(rem_oos),
        'removed_signal_b0_net_R_per_trade': rem_agg['net_R_per_trade'],
        'removed_signal_selection_not_explained_by_stop': selection_ok,
        'note': ('the B0 outcome of the signals the variant refuses (NO TRADE) is '
                 'reported; a gain explained by dropping good signals is not a stop '
                 'improvement'),
    }
    # G-C risk
    base_dd, cand_dd = abs(ba['max_dd_r'] or 0), abs(ca['max_dd_r'] or 0)
    largest_ok = (ba['largest_loss_r'] is None or ca['largest_loss_r'] is None
                  or ca['largest_loss_r'] >= ba['largest_loss_r'])
    mae_ok = (ba['mean_mae_r'] is None or ca['mean_mae_r'] is None
              or ca['mean_mae_r'] <= ba['mean_mae_r'])
    g['G-C_risk'] = {
        'baseline_max_dd_r': ba['max_dd_r'], 'candidate_max_dd_r': ca['max_dd_r'],
        'max_dd_le_1_5x_baseline': bool(cand_dd <= 1.5 * base_dd),
        'baseline_largest_loss_r': ba['largest_loss_r'],
        'candidate_largest_loss_r': ca['largest_loss_r'],
        'largest_loss_not_worse': bool(largest_ok),
        'baseline_mean_mae_r': ba['mean_mae_r'],
        'candidate_mean_mae_r': ca['mean_mae_r'],
        'mae_not_worse': bool(mae_ok),
        'capital_base_subgates': 'INCONCLUSIVE',
        'capital_base_note': ('no production-confirmed capital base exists, so '
                              'percentage-of-capital sub-gates cannot be evaluated; '
                              'index points are never equated to rupees'),
        'pass': bool(cand_dd <= 1.5 * base_dd and largest_ok and mae_ok),
    }
    # G-D stability
    periods = {p: {'baseline': b[p]['net_R_per_trade'],
                   'candidate': c[p]['net_R_per_trade'],
                   'positive': bool(c[p]['net_R_per_trade'] is not None
                                    and b[p]['net_R_per_trade'] is not None
                                    and c[p]['net_R_per_trade'] > b[p]['net_R_per_trade'])}
               for p in ('IS', 'VAL', 'OOS')}
    pos_periods = sum(1 for v in periods.values() if v['positive'])
    block_res, pos_blocks = _blocks_positive(days, cand, base_paired)
    inst = {}
    for name, recs in by_instrument(oos_c).items():
        brecs = [r for r in oos_b if r['instrument'] == name]
        bb = agg_ext(brecs)
        inst[name] = {'baseline': bb['net_R_per_trade'],
                      'candidate': recs['net_R_per_trade'],
                      'positive': bool(recs['net_R_per_trade'] is not None
                                       and bb['net_R_per_trade'] is not None
                                       and recs['net_R_per_trade'] > bb['net_R_per_trade'])}
    pos_inst = sum(1 for v in inst.values() if v['positive'])
    g['G-D_stability'] = {
        'periods': periods, 'n_periods_positive': pos_periods,
        'walk_forward_blocks': block_res, 'n_blocks_positive': pos_blocks,
        'instruments_oos': inst, 'n_instruments_positive': pos_inst,
        'variant_ranking_consistent': bool(ranking_ok),
        'note': ('variant ranking consistency replaces neighbour stability: the '
                 'selected stop variant must also be the best VAL variant in each '
                 'instrument separately'),
        'pass': bool(pos_periods >= 2 and pos_blocks >= 4 and pos_inst == 2
                     and ranking_ok),
    }
    # G-E evidence
    n_nifty = sum(1 for r in oos_c if r['instrument'] == 'NIFTY')
    n_bnk = sum(1 for r in oos_c if r['instrument'] == 'BANKNIFTY')
    oos_days = sorted({r['session_date'] for r in oos_c} | {r['session_date'] for r in oos_b})
    boot = pmetrics.block_bootstrap(oos_b, oos_c, oos_days, n_boot=2000)
    lo, hi = boot.get('ci_low'), boot.get('ci_high')
    straddles = bool(lo is not None and hi is not None and lo <= 0 <= hi)
    g['G-E_evidence_sufficiency'] = {
        'n_oos_candidate': len(oos_c), 'n_oos_baseline': len(oos_b),
        'n_oos_nifty': n_nifty, 'n_oos_banknifty': n_bnk,
        'bootstrap_ci_low': lo, 'bootstrap_ci_high': hi,
        'bootstrap_p_two_sided': boot.get('p_two_sided'),
        'ci_straddles_zero': straddles,
        'pass': bool(len(oos_c) >= 15 and n_nifty >= 5 and n_bnk >= 5
                     and lo is not None and hi is not None and not straddles),
    }
    # G-F integrity
    lookahead_ok = all(r.get('no_lookahead_ok') for r in cand)
    keys_ok = {r['signal_key'] for r in cand} <= {r['signal_key'] for r in base_all}
    target_ok = all(abs(r['target_price'] - r['entry'] * (
        1 - 0.02 if r['direction'] == 'BEAR' else 1 + 0.02)) < 1e-6 for r in cand)
    stops_valid = all(structures.validate(r['direction'], r['entry'],
                                          r['stop_price']) is None for r in cand)
    g['G-F_integrity'] = {
        'no_lookahead_checks': bool(lookahead_ok),
        'same_signal_set_as_baseline': bool(keys_ok),
        'target_unchanged': bool(target_ok),
        'stops_on_correct_side_within_bounds': bool(stops_valid),
        'identical_execution_model': True,
        'identical_cost_model': True,
        'gap_aware_accounting': True,
        'dq_status': dq.get('status'), 'dq_problems': dq.get('problems'),
        'pass': bool(lookahead_ok and keys_ok and target_ok and stops_valid
                     and dq.get('status') in ('PASS', 'PASS_WITH_LIMITATIONS')
                     and not dq.get('problems')),
    }
    g['G-G_scope'] = {'index_level_only': True, 'option_premium_claims': 'NONE',
                      'bid_ask_claims': 'NONE', 'rupee_profit_claims': 'NONE',
                      'pass': True}
    # G-I intrabar robustness (added)
    ib_cand = by_variant_ib[variant]
    ib_base = paired(by_variant_ib['B0'], ib_cand)
    ic = agg_ext([r for r in ib_cand if r['period'] == 'OOS'])
    ib = agg_ext([r for r in ib_base if r['period'] == 'OOS'])
    g['G-I_intrabar_robustness'] = {
        'baseline_intrabar_net_R_per_trade': ib['net_R_per_trade'],
        'candidate_intrabar_net_R_per_trade': ic['net_R_per_trade'],
        'baseline_intrabar_points_per_trade': ib['points_per_trade'],
        'candidate_intrabar_points_per_trade': ic['points_per_trade'],
        'pass': bool(ic['net_R_per_trade'] is not None
                     and ib['net_R_per_trade'] is not None
                     and ic['net_R_per_trade'] >= ib['net_R_per_trade']),
        'note': 'conservative intrabar model, stop assumed first on ambiguous bars',
    }
    g['oos_independence'] = 'PARTIAL'
    g['oos_independence_note'] = (
        'the 2026-10-01..10-21 window and baseline signal set were examined in the '
        'parent study; a pass is exploratory and can never be eligible for review '
        'without fresh forward data')

    core = (g['G-A_oos_improvement']['pass'] and g['G-A2_oos_points_not_worse']['pass']
            and g['G-B_not_cost_artifact']['pass'] and g['G-C_risk']['pass']
            and g['G-D_stability']['pass'] and g['G-E_evidence_sufficiency']['pass']
            and g['G-F_integrity']['pass'] and g['G-G_scope']['pass']
            and g['G-I_intrabar_robustness']['pass'])
    enough = bool(c['VAL']['n'] >= 10 and ca['n'] >= 15)
    g['OVERALL'] = ('INCONCLUSIVE' if not enough else
                    ('PASS_EXPLORATORY' if core else 'FAIL'))
    g['ELIGIBLE_FOR_HUMAN_REVIEW'] = False
    g['decision'] = {
        'INCONCLUSIVE': 'INCONCLUSIVE - insufficient evidence (VAL or OOS trade count)',
        'PASS_EXPLORATORY': ('PASS_EXPLORATORY - every gate passed, but the OOS '
                             'window is not independent; no review or change is '
                             'authorised'),
        'FAIL': 'FAIL - the stop variant does not pass the hard gates',
    }[g['OVERALL']]
    return g
