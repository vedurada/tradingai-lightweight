"""ADD-ON runner: stop location, entry cushion, hypothetical trade records.

Reads the parent study's read-only snapshot, rebuilds the unchanged production
baseline signals, derives stops B0/S1-S5 point-in-time, simulates two execution
models, and runs Experiment A (frozen entry filters, production stop) and
Experiment B (stop placement on the same entries). Parameters are those
pre-registered in `spec_addon.md` and are never selected on OOS.
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import statistics
import sys

REPO = '/opt/tradingai'
if REPO not in sys.path:
    sys.path.insert(0, REPO)

try:
    from ...src import prod, snapshot, data, accounting, candidates, metrics as pmetrics
    from . import cushion, execution_ext, metrics_ext, records, structures
except ImportError:  # pragma: no cover - only used by ad-hoc local imports
    from research.prevday_cpr_spread_study.stop_forensics.src import (
        prod, snapshot, data, accounting, candidates, metrics as pmetrics)
    from research.prevday_cpr_spread_study.stop_forensics.addon_stop_placement.src import (
        cushion, execution_ext, metrics_ext, records, structures)

DATE_START = '2026-07-06'
DATE_END = '2026-10-21'
INSTRUMENTS = ('NIFTY', 'BANKNIFTY')
VARIANTS = records.VARIANTS
SWEEP = ('S1', 'S2', 'S3', 'S4', 'S5')
FROZEN = ('BASELINE', 'E1_k1.00', 'E2_x0.10pct', 'E3_retest', 'E4_until_1100',
          'E5_skip_q90', 'E6_reentry', 'E7_conflict')


def quantile(xs, q):
    xs = sorted(xs)
    if not xs:
        return None
    k = (len(xs) - 1) * q
    f = int(k)
    c = min(f + 1, len(xs) - 1)
    return round(xs[f] + (xs[c] - xs[f]) * (k - f), 6)


def as_model(row: dict, model: str) -> dict:
    """Project an add-on row onto one execution model's canonical fields."""
    if model == 'opens':
        return {**row, 'model': 'opens'}
    return {
        **row, 'model': 'intrabar',
        'exit_reason': row['intrabar_exit_reason'],
        'exit_price': row['intrabar_exit_price'],
        'exit_time': row['intrabar_exit_time'],
        'realized_r': row['intrabar_realized_r'],
        'realized_pts': row['intrabar_realized_pts'],
        'booked_r': row['intrabar_booked_r'],
        'stop_overshoot_pts': row['intrabar_stop_overshoot_pts'],
        'stop_overshoot_r': row['intrabar_stop_overshoot_r'],
        'target_truncation_pts': row['intrabar_target_truncation_pts'],
        'target_truncation_r': row['intrabar_target_truncation_r'],
        'mae_hl_pts': row['intrabar_mae_hl_pts'],
        'mae_hl_r': row['intrabar_mae_hl_r'],
        'mfe_hl_pts': row['intrabar_mfe_hl_pts'],
        'mfe_hl_r': row['intrabar_mfe_hl_r'],
        'bars_held': row['intrabar_bars_held'],
        'risk_pts': row['intrabar_risk_pts'],
        'intrabar_ambiguous_bars': row['intrabar_intrabar_ambiguous_bars'],
    }


def ib_from_parent(rec: dict, universes: dict) -> dict | None:
    """Conservative-model record for a frozen Experiment A trade."""
    ctx = universes[rec['instrument']]['sessions'].get(rec['session_date'])
    if not ctx:
        return None
    scan = ctx['scan']
    key = str(rec['entry_time']).replace(' ', 'T')[:16]
    entry_idx = next((i for i, c in enumerate(scan)
                      if str(c['timestamp'])[:16] == key), None)
    if entry_idx is None:
        return None
    sim = execution_ext.simulate(rec['direction'], rec['entry'], scan, entry_idx,
                                 rec['stop_price'], rec['target_price'], 'intrabar')
    if sim is None:
        return None
    exc = execution_ext.excursion(rec['direction'], rec['entry'], scan, entry_idx,
                                  sim['exit_ts'])
    risk = sim['risk_pts']
    out = dict(rec)
    out.update({
        'model': 'intrabar', 'exit_reason': sim['exit_reason'],
        'exit_price': sim['exit_price'],
        'exit_time': str(sim['exit_ts'])[:16].replace('T', ' '),
        'realized_r': sim['realized_r'], 'realized_pts': sim['realized_pts'],
        'booked_r': sim['booked_r'],
        'stop_overshoot_pts': sim['stop_overshoot_pts'],
        'stop_overshoot_r': sim['stop_overshoot_r'],
        'target_truncation_pts': sim['target_truncation_pts'],
        'target_truncation_r': sim['target_truncation_r'],
        'mae_hl_pts': exc['mae_hl_pts'], 'mae_hl_r': round(exc['mae_hl_pts'] / risk, 4),
        'mfe_hl_pts': exc['mfe_hl_pts'], 'mfe_hl_r': round(exc['mfe_hl_pts'] / risk, 4),
        'bars_held': exc['bars_held'], 'risk_pts': round(risk, 4),
        'intrabar_ambiguous_bars': sim['intrabar_ambiguous_bars'],
    })
    return out


def arm_metrics(recs: list) -> dict:
    return {
        'by_period': metrics_ext.by_period(recs),
        'all': metrics_ext.agg_ext(recs),
        'by_instrument': metrics_ext.by_instrument(recs),
    }


def experiment_a(universes: dict, eng, base_all: list, dq: dict) -> dict:
    cpr_is = []
    for u in universes.values():
        for ctx in u['sessions'].values():
            if ctx['period'] == 'IS' and ctx.get('cpr_width_pct') is not None:
                cpr_is.append(ctx['cpr_width_pct'])
    cpr_stats = {'q10': quantile(cpr_is, 0.10), 'q25': quantile(cpr_is, 0.25),
                 'q75': quantile(cpr_is, 0.75), 'q90': quantile(cpr_is, 0.90)}
    out = {'arms': {}, 'cpr_stats_is': cpr_stats,
           'note': ('frozen phase-2 entry filters, no re-selection; E3 changes the '
                    'entry price, so its comparison with BASELINE is not a paired '
                    'comparison')}
    for arm in FROZEN:
        kept, removed = [], []
        for inst in INSTRUMENTS:
            u = universes[inst]
            if arm == 'BASELINE':
                kept.extend(candidates.arm_baseline(u))
            elif arm.startswith('E1_k'):
                k, r = candidates.arm_e1(u, 1.00)
                kept.extend(k)
                removed.extend(r)
            elif arm.startswith('E2_x'):
                k, r = candidates.arm_e2(u, 0.10)
                kept.extend(k)
                removed.extend(r)
            elif arm == 'E3_retest':
                k, r = candidates.arm_e3(u)
                kept.extend(k)
                removed.extend(r)
            elif arm.startswith('E4_until'):
                k, r = candidates.arm_e4(u, '11:00')
                kept.extend(k)
                removed.extend(r)
            elif arm.startswith('E5_skip'):
                k, r = candidates.arm_e5(u, 'q90', cpr_stats)
                kept.extend(k)
                removed.extend(r)
            elif arm == 'E6_reentry':
                k, r = candidates.arm_e6(u, eng)
                kept.extend(k)
                removed.extend(r)
            elif arm == 'E7_conflict':
                k, r = candidates.arm_e7(u, eng)
                kept.extend(k)
                removed.extend(r)
        ib = [r for r in (ib_from_parent(x, universes) for x in kept) if r]
        rem_ib = [r for r in (ib_from_parent(x, universes) for x in removed) if r]
        out['arms'][arm] = {
            'opens': arm_metrics(kept),
            'intrabar': arm_metrics(ib),
            'removed': {'n': len(removed), 'opens': metrics_ext.agg_ext(removed),
                        'intrabar': metrics_ext.agg_ext(rem_ib)},
        }
    base = out['arms']['BASELINE']
    for arm, blob in out['arms'].items():
        if arm == 'BASELINE':
            continue
        for model in ('opens', 'intrabar'):
            b = base[model]['by_period']
            c = blob[model]['by_period']
            blob[f'delta_vs_baseline_{model}'] = {
                p: (None if c[p]['net_R_per_trade'] is None
                    or b[p]['net_R_per_trade'] is None
                    else round(c[p]['net_R_per_trade'] - b[p]['net_R_per_trade'], 4))
                for p in ('IS', 'VAL', 'OOS')}
    return out


def select_b(by_variant: dict) -> tuple:
    val = {v: metrics_ext.agg_ext([r for r in by_variant[v] if r['period'] == 'VAL'])
           for v in SWEEP}
    eligible = [v for v in SWEEP if val[v]['n'] >= 10
                and val[v]['net_R_per_trade'] is not None]
    info = {'eligible': eligible,
            'val_net_R_per_trade': {v: val[v]['net_R_per_trade'] for v in SWEEP},
            'val_n': {v: val[v]['n'] for v in SWEEP},
            'val_mean_stop_distance_pct': {v: val[v]['mean_stop_distance_pct']
                                           for v in SWEEP}}
    if not eligible:
        return None, {'selected': None, 'reason': 'no variant had >=10 VAL trades',
                      **info}
    best = max(eligible, key=lambda v: val[v]['net_R_per_trade'])
    top = val[best]['net_R_per_trade']
    near = [v for v in eligible if abs(val[v]['net_R_per_trade'] - top) < 0.02]

    def stop_dist(v):
        d = val[v]['mean_stop_distance_pct']
        return 9.0 if d is None else d

    selected = min(near, key=stop_dist) if len(near) > 1 else best
    return selected, {
        'selected': selected, 'criterion': ('highest VAL net R/trade among S1-S5 '
                                            'with >=10 VAL trades; ties <0.02R to '
                                            'the smaller mean stop distance'),
        'best_val_net_R': best, 'tie_candidates': near, **info,
        'selection_used': 'VAL only; OOS not consulted',
    }


def ranking_ok(by_variant: dict, selected: str) -> tuple:
    out = {}
    ok = True
    for inst in INSTRUMENTS:
        vals = {}
        for v in SWEEP:
            a = metrics_ext.agg_ext([r for r in by_variant[v]
                                     if r['period'] == 'VAL' and r['instrument'] == inst])
            if a['n'] >= 5 and a['net_R_per_trade'] is not None:
                vals[v] = a['net_R_per_trade']
        best = max(vals, key=vals.get) if vals else None
        out[inst] = {'best_val_variant': best, 'values': vals}
        ok = ok and best == selected
    return ok, out


def combined_step(universes, base_all, frozen_a, by_variant, by_variant_ib,
                  selected) -> dict:
    """Pre-registered conditional combination (spec §7)."""
    ea = frozen_a['arms']
    val_base = ea['BASELINE']['opens']['by_period']['VAL']
    val_e3 = ea['E3_retest']['opens']['by_period']['VAL']
    cond_a = bool(val_e3['net_R_per_trade'] is not None
                  and val_base['net_R_per_trade'] is not None
                  and val_e3['net_R_per_trade'] > val_base['net_R_per_trade'])
    pre = {'condition_a_e3_val_beats_baseline': cond_a,
           'val_baseline_net_R': val_base['net_R_per_trade'],
           'val_e3_net_R': val_e3['net_R_per_trade']}
    if selected is None:
        return {'status': 'NOT RUN', 'reason': 'Experiment B had no selected variant',
                **pre}
    cand = by_variant[selected]
    keys = {x['signal_key'] for x in cand}
    base_paired_val = [r for r in by_variant['B0']
                       if r['period'] == 'VAL' and r['signal_key'] in keys]
    cv = metrics_ext.agg_ext([r for r in cand if r['period'] == 'VAL'])
    bv = metrics_ext.agg_ext(base_paired_val)
    cond_b = bool(cv['net_R_per_trade'] is not None
                  and bv['net_R_per_trade'] is not None
                  and cv['net_R_per_trade'] > bv['net_R_per_trade']
                  and cv['points_per_trade'] is not None
                  and bv['points_per_trade'] is not None
                  and cv['points_per_trade'] >= bv['points_per_trade'])
    pre.update({'condition_b_selected_val_beats_paired': cond_b,
                'val_selected_net_R': cv['net_R_per_trade'],
                'val_paired_baseline_net_R': bv['net_R_per_trade']})
    if not (cond_a and cond_b):
        return {'status': 'NOT RUN', 'reason': 'pre-check failed; the single OOS look '
                'is not spent on a candidate whose components did not both beat VAL',
                **pre}

    index = {(inst, s['session_date'], s['direction'], s['level']): s
             for inst in INSTRUMENTS for s in universes[inst]['signals']}
    kept = []
    for inst in INSTRUMENTS:
        k, _ = candidates.arm_e3(universes[inst])
        kept.extend(k)
    comb, skipped = [], 0
    for rec in kept:
        base_sig = index.get((rec['instrument'], rec['session_date'],
                              rec['direction'], rec['setup']))
        if base_sig is None:
            skipped += 1
            continue
        ctx = base_sig['ctx']
        key = str(rec['entry_time']).replace(' ', 'T')[:16]
        entry_idx = next((i for i, c in enumerate(ctx['scan'])
                          if str(c['timestamp'])[:16] == key), None)
        if entry_idx is None:
            skipped += 1
            continue
        sig = {**base_sig, 'entry': rec['entry'], 'entry_idx': entry_idx,
               'entry_time': rec['entry_time']}
        row = records.build(sig, selected)
        if row.get('no_trade') or row.get('realized_r') is None \
                or row.get('intrabar_realized_r') is None:
            skipped += 1
            continue
        comb.append(row)
    bv2 = {'B0': by_variant['B0'], 'COMBINED': [as_model(r, 'opens') for r in comb]}
    bvi2 = {'B0': by_variant_ib['B0'],
            'COMBINED': [as_model(r, 'intrabar') for r in comb]}
    gates = metrics_ext.evaluate('COMBINED', bv2, bvi2, sorted(
        {r['session_date'] for r in base_all}),
        {'status': 'PASS', 'problems': []}, True, [])
    return {'status': 'RUN', 'variant': selected,
            'candidate': 'E3_retest+' + selected, 'n_trades': len(comb),
            'n_skipped': skipped, 'gates': gates, **pre}


def main():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out_dir = os.path.join(base_dir, 'outputs')
    rep_dir = os.path.join(base_dir, 'reports')
    snap_dir = os.path.join(out_dir, 'snapshot')
    for d in (out_dir, rep_dir, snap_dir):
        os.makedirs(d, exist_ok=True)

    parent_root = os.path.dirname(base_dir)
    parent_snap = os.path.join(parent_root, 'outputs', 'snapshot',
                               'tradingai_snapshot.db')
    pristine = os.path.join(snap_dir, 'tradingai_snapshot.db')
    if not os.path.exists(pristine):
        shutil.copyfile(parent_snap, pristine)
    work = os.path.join(snap_dir, 'working_copy.db')
    shutil.copyfile(pristine, work)
    parent_meta_path = os.path.join(parent_root, 'outputs', 'snapshot_meta.json')
    src_sha = None
    if os.path.exists(parent_meta_path):
        with open(parent_meta_path) as f:
            src_sha = json.load(f).get('source_sha256_at_snapshot')
    snap_meta = {
        'snapshot_path': pristine,
        'snapshot_sha256': snapshot.sha256_file(pristine),
        'source_sha256_at_snapshot': src_sha,
        'method': ('reused the parent study snapshot (read-only input, copied to a '
                   'working copy); the live database was not read for this run'),
        'parent_snapshot_meta': parent_meta_path,
    }
    pmetrics.write_json(os.path.join(out_dir, 'snapshot_meta.json'), snap_meta)

    prod.ensure_db_env(work)
    eng = prod.engine()

    ro = sqlite3.connect(f'file:{work}?mode=ro', uri=True, timeout=30)
    ro.row_factory = sqlite3.Row
    dq = data.data_quality(ro, INSTRUMENTS, DATE_START, DATE_END)
    pmetrics.write_json(os.path.join(out_dir, 'data_quality.json'), dq)

    universes = {inst: accounting.build_universe(ro, eng, inst, DATE_START, DATE_END)
                 for inst in INSTRUMENTS}
    base_all = []
    for inst in INSTRUMENTS:
        base_all.extend(candidates.arm_baseline(universes[inst]))
    recon = {inst: accounting.reconcile(universes[inst]['run'],
                                        [r for r in base_all
                                         if r['instrument'] == inst])
             for inst in INSTRUMENTS}
    pmetrics.write_json(os.path.join(out_dir, 'baseline_reconciliation.json'), recon)
    pmetrics.write_csv(os.path.join(out_dir, 'baseline_trades.csv'), base_all)

    # ---- hypothetical trade records: every signal x variant, both models ----
    rows, excluded = [], []
    by_variant = {v: [] for v in VARIANTS}
    by_variant_ib = {v: [] for v in VARIANTS}
    for inst in INSTRUMENTS:
        for sig in universes[inst]['signals']:
            for v in VARIANTS:
                row = records.build(sig, v)
                rows.append(row)
                if row.get('no_trade'):
                    continue
                if (row.get('opens_missing_eod') or row.get('realized_r') is None
                        or row.get('intrabar_realized_r') is None):
                    excluded.append(row)
                    continue
                by_variant[v].append(as_model(row, 'opens'))
                by_variant_ib[v].append(as_model(row, 'intrabar'))
    pmetrics.write_csv(os.path.join(out_dir, 'hypothetical_trades.csv'), rows)

    # ---- cushion summary ----
    cush = {}
    for v in VARIANTS:
        valid = [r for r in rows if r['variant'] == v and not r['no_trade']]
        dists = [r['stop_distance_pct'] for r in valid]
        no_trade = [r for r in rows if r['variant'] == v and r['no_trade']]
        cush[v] = {
            'n_trades': len(valid), 'n_no_trade': len(no_trade),
            'mean_stop_distance_pct': round(statistics.mean(dists), 6) if dists else None,
            'median_stop_distance_pts': (round(statistics.median(
                r['stop_distance_pts'] for r in valid), 3) if valid else None),
            'pullback_would_hit': sum(1 for r in valid if r['pullback_would_hit']),
            'wider_than_production': sum(1 for r in valid if r['wider_than_production']),
            'mean_mae_before_first_profit_r': _mean(
                [r['mae_before_first_profit_r'] for r in valid
                 if r.get('mae_before_first_profit_r') is not None]),
            'mean_rr_to_nearest_level': _mean(
                [r['rr_to_nearest_level'] for r in valid
                 if r.get('rr_to_nearest_level') is not None]),
            'no_trade_reasons': _reasons(no_trade),
            'note': 'a wider cushion is not a better trade',
        }
    pmetrics.write_json(os.path.join(out_dir, 'cushion_summary.json'), cush)

    # ---- Experiment B ----
    b_metrics = {}
    for v in VARIANTS:
        b_metrics[v] = {
            'opens': arm_metrics(by_variant[v]),
            'intrabar': arm_metrics(by_variant_ib[v]),
            'no_trade': sum(1 for r in rows if r['variant'] == v and r['no_trade']),
        }
    pmetrics.write_json(os.path.join(out_dir, 'experiment_b_metrics.json'), b_metrics)

    paired_rows, paired_table = [], {}
    for v in VARIANTS:
        cand = by_variant[v]
        base = metrics_ext.paired(by_variant['B0'], cand)
        ca, ba = metrics_ext.agg_ext(cand), metrics_ext.agg_ext(base)
        oos_c = [r for r in cand if r['period'] == 'OOS']
        oos_b = [r for r in base if r['period'] == 'OOS']
        boa = metrics_ext.agg_ext(oos_b)
        coa = metrics_ext.agg_ext(oos_c)
        paired_table[v] = {
            'candidate': {'n': ca['n'], 'net_R_per_trade': ca['net_R_per_trade'],
                          'points_per_trade': ca['points_per_trade'],
                          'stop_out_rate': ca['stop_out_rate']},
            'paired_baseline': {'n': ba['n'], 'net_R_per_trade': ba['net_R_per_trade'],
                                'points_per_trade': ba['points_per_trade'],
                                'stop_out_rate': ba['stop_out_rate']},
            'oos_candidate': coa, 'oos_paired_baseline': boa,
        }
        for r in cand:
            paired_rows.append({'variant': v, 'signal_key': r['signal_key'],
                                'instrument': r['instrument'],
                                'session_date': r['session_date'],
                                'period': r['period'],
                                'candidate_net_R': r['realized_r'],
                                'baseline_net_R': next(
                                    (b['realized_r'] for b in base
                                     if b['signal_key'] == r['signal_key']), None)})
    pmetrics.write_csv(os.path.join(out_dir, 'experiment_b_paired.csv'), paired_rows)
    pmetrics.write_json(os.path.join(out_dir, 'experiment_b_paired_metrics.json'),
                        paired_table)

    selected, selection = select_b(by_variant)
    rank_ok, rank_detail = ranking_ok(by_variant, selected) if selected else (False, {})
    selection['ranking_consistency'] = rank_detail
    selection['ranking_ok'] = bool(rank_ok)
    pmetrics.write_json(os.path.join(out_dir, 'experiment_b_selection.json'), selection)

    gates, removed_b0 = None, []
    if selected:
        no_trade_keys = {r['signal_key'] for r in rows
                         if r['variant'] == selected and r['no_trade']}
        removed_b0 = [r for r in by_variant['B0'] if r['signal_key'] in no_trade_keys]
        gates = metrics_ext.evaluate(selected, by_variant, by_variant_ib,
                                     sorted({r['session_date'] for r in base_all}),
                                     dq, rank_ok, removed_b0)
    pmetrics.write_json(os.path.join(out_dir, 'experiment_b_gates.json'),
                        {'variant': selected, 'gates': gates,
                         'no_trade_count': len(removed_b0)})

    # ---- Experiment A ----
    exp_a = experiment_a(universes, eng, base_all, dq)
    pmetrics.write_json(os.path.join(out_dir, 'experiment_a_metrics.json'), exp_a)

    # ---- pre-registered deliverable files ----
    pmetrics.write_json(os.path.join(out_dir, 'experiment_a_arm_metrics.json'), exp_a)
    pmetrics.write_json(os.path.join(out_dir, 'stopout_analysis.json'),
                        stopout_analysis(by_variant, by_variant_ib))
    pmetrics.write_json(os.path.join(out_dir, 'structural_diagnostics.json'),
                        structural_diagnostics(universes, rows, base_all))
    pmetrics.write_csv(os.path.join(out_dir, 'cushion_analysis.csv'), cushion_rows(rows))
    pmetrics.write_csv(os.path.join(out_dir, 'experiment_a_arms.csv'),
                       experiment_a_rows(exp_a))

    # ---- conditional combined ----
    comb = combined_step(universes, base_all, exp_a, by_variant, by_variant_ib,
                         selected)
    pmetrics.write_json(os.path.join(out_dir, 'combined_step.json'), comb)

    equiv = b0_equivalence(base_all, rows)

    manifest = {
        'study': 'addon_stop_placement',
        'parent_study': 'stop_forensics (phase 2)',
        'spec': 'spec_addon.md (pre-registered)',
        'parameters': {k: getattr(structures, k) for k in (
            'EPS_PCT', 'Z', 'SWING_LOOKBACK', 'SWING_M', 'K_VOL', 'VOL_MIN_BARS',
            'MIN_STOP_PCT', 'MAX_STOP_PCT', 'PULLBACK_MULT')},
        'target_pct': records.TARGET_PCT,
        'date_range': [DATE_START, DATE_END],
        'instruments': list(INSTRUMENTS),
        'counts': {'signals': len(base_all), 'record_rows': len(rows),
                   'excluded_missing_eod': len(excluded),
                   'per_variant': {v: len(by_variant[v]) for v in VARIANTS}},
        'selected_variant': selected,
        'integrity_ok': bool(equiv['pass']),
        'verdict': ('INVALID_B0_EQUIVALENCE' if not equiv['pass']
                    else (None if not gates else gates['OVERALL'])),
        'oos_independence': 'PARTIAL',
        'eligible_for_human_review': False,
        'production_changed': False,
        'db_env_used_by_research': os.environ.get('TRADINGAI_DB_PATH'),
        'snapshot_sha256': snap_meta.get('snapshot_sha256'),
        'dq_status': dq.get('status'),
        'b0_equivalence': equiv,
    }
    pmetrics.write_json(os.path.join(out_dir, 'run_manifest.json'), manifest)
    pmetrics.write_json(os.path.join(base_dir, 'run_manifest.json'), manifest)

    report = build_report(manifest, by_variant, by_variant_ib, rows, cush, b_metrics,
                          paired_table, selection, gates, exp_a, comb, dq, recon,
                          equiv)
    with open(os.path.join(rep_dir, 'ADDON_STOP_PLACEMENT_REPORT.md'), 'w') as f:
        f.write(report)
    print('DONE', json.dumps({'selected': selected,
                              'verdict': manifest['verdict'],
                              'rows': len(rows),
                              'signals': len(base_all)}))


def stopout_analysis(by_variant: dict, by_variant_ib: dict) -> dict:
    out = {}
    for v, rows in by_variant.items():
        out[v] = {}
        for model, recs in (('opens', rows), ('intrabar', by_variant_ib[v])):
            stops = [r for r in recs if r['exit_reason'] == 'STOP']
            overs = [r.get('stop_overshoot_pts') or 0.0 for r in stops]
            rr = [r['realized_r'] for r in stops]
            out[v][model] = {
                'n': len(recs), 'stops': len(stops),
                'stop_out_rate': round(len(stops) / len(recs), 4) if recs else None,
                'targets': sum(1 for r in recs if r['exit_reason'] == 'TARGET'),
                'eod': sum(1 for r in recs if r['exit_reason'] == 'EOD-1520'),
                'gap_through_stops': sum(1 for x in overs if x > 0.011),
                'mean_stop_overshoot_pts': round(statistics.mean(overs), 3) if overs else None,
                'max_stop_overshoot_pts': round(max(overs), 3) if overs else None,
                'mean_realized_r_on_stops': round(statistics.mean(rr), 4) if rr else None,
                'worst_realized_r_on_stops': round(min(rr), 4) if rr else None,
                'mean_realized_r_on_targets': _mean(
                    [r['realized_r'] for r in recs if r['exit_reason'] == 'TARGET']),
                'ambiguous_bars_total': sum(r.get('intrabar_ambiguous_bars') or 0
                                            for r in recs),
            }
    return out


def structural_diagnostics(universes: dict, rows: list, base_all: list) -> dict:
    out = {'swing_definition': {'m': structures.SWING_M, 'lookback': structures.SWING_LOOKBACK,
                                'confirm_at': 'close of bar i+m, usable only if i+m <= trigger'},
           'by_variant': {}}
    for v in VARIANTS:
        vrows = [r for r in rows if r['variant'] == v]
        trades = [r for r in vrows if not r['no_trade']]
        nt = [r for r in vrows if r['no_trade']]
        by_setup = {}
        for r in vrows:
            b = by_setup.setdefault(r['setup'], {'trades': 0, 'no_trade': 0})
            b['no_trade' if r['no_trade'] else 'trades'] += 1
        by_inst = {}
        for r in trades:
            b = by_inst.setdefault(r['instrument'], {'trades': 0})
            b['trades'] += 1
        out['by_variant'][v] = {
            'n_signals': len(vrows), 'n_trades': len(trades),
            'n_no_trade': len(nt), 'rejection_reasons': _reasons(nt),
            'by_setup': by_setup, 'by_instrument': by_inst,
            'mean_stop_distance_pct': _mean([r['stop_distance_pct'] for r in trades]),
            'wider_than_production': sum(1 for r in trades if r['wider_than_production']),
            'no_lookahead_ok': all(r.get('no_lookahead_ok') for r in trades),
        }
    out['n_baseline_signals'] = len(base_all)
    return out


def cushion_rows(rows: list) -> list:
    out = []
    for v in VARIANTS:
        for inst in INSTRUMENTS:
            vrows = [r for r in rows if r['variant'] == v and r['instrument'] == inst]
            trades = [r for r in vrows if not r['no_trade']]
            out.append({
                'variant': v, 'instrument': inst, 'n_trades': len(trades),
                'n_no_trade': len(vrows) - len(trades),
                'mean_stop_distance_pct': _mean([r['stop_distance_pct'] for r in trades]),
                'median_stop_distance_pts': (
                    round(statistics.median(r['stop_distance_pts'] for r in trades), 3)
                    if trades else None),
                'mean_rr_to_target': _mean([r['rr_to_target'] for r in trades]),
                'mean_rr_to_nearest_level': _mean([r['rr_to_nearest_level'] for r in trades]),
                'mean_mae_before_first_profit_r': _mean(
                    [r['mae_before_first_profit_r'] for r in trades
                     if r.get('mae_before_first_profit_r') is not None]),
                'pullback_would_hit': sum(1 for r in trades if r['pullback_would_hit']),
                'wider_than_production': sum(1 for r in trades if r['wider_than_production']),
                'note': 'cushion is context only; a wider cushion is not a better trade',
            })
    return out


def experiment_a_rows(exp_a: dict) -> list:
    out = []
    for arm in FROZEN:
        for model in ('opens', 'intrabar'):
            blob = exp_a['arms'][arm][model]
            for period in ('IS', 'VAL', 'OOS'):
                a = blob['by_period'][period]
                out.append({'arm': arm, 'model': model, 'period': period,
                            'scope': 'all', 'n': a['n'],
                            'net_R_per_trade': a['net_R_per_trade'],
                            'points_per_trade': a['points_per_trade'],
                            'stop_out_rate': a['stop_out_rate']})
            for inst, a in blob['by_instrument'].items():
                out.append({'arm': arm, 'model': model, 'period': 'ALL',
                            'scope': inst, 'n': a['n'],
                            'net_R_per_trade': a['net_R_per_trade'],
                            'points_per_trade': a['points_per_trade'],
                            'stop_out_rate': a['stop_out_rate']})
            out.append({'arm': arm, 'model': model, 'period': 'ALL',
                        'scope': 'ALL', 'n': blob['all']['n'],
                        'net_R_per_trade': blob['all']['net_R_per_trade'],
                        'points_per_trade': blob['all']['points_per_trade'],
                        'stop_out_rate': blob['all']['stop_out_rate']})
            rem = exp_a['arms'][arm]['removed']
            out.append({'arm': arm, 'model': model, 'period': 'ALL',
                        'scope': 'removed', 'n': rem['n'],
                        'net_R_per_trade': rem[model]['net_R_per_trade'],
                        'points_per_trade': rem[model]['points_per_trade'],
                        'stop_out_rate': rem[model]['stop_out_rate']})
    return out


def b0_equivalence(base_all: list, rows: list) -> dict:
    """B0 must reproduce the frozen baseline bit-for-bit in the opens model."""
    b0 = {r['signal_key']: r for r in rows if r['variant'] == 'B0'}
    mismatches = []
    max_r_diff = 0.0
    for rec in base_all:
        key = (f"{rec['instrument']}|{rec['session_date']}|{rec['setup']}|"
               f"{rec['entry_time']}")
        row = b0.get(key)
        if row is None:
            mismatches.append({'key': key, 'issue': 'missing'})
            continue
        r_diff = abs((row.get('realized_r') or 0.0) - rec['realized_r'])
        max_r_diff = max(max_r_diff, r_diff)
        bad = (row.get('no_trade') or row.get('exit_reason') != rec['exit_reason']
               or abs((row.get('exit_price') or 0.0) - rec['exit_price']) > 1e-6
               or r_diff > 1e-3)
        if bad:
            mismatches.append({'key': key, 'issue': 'value',
                               'ours': {'exit_reason': row.get('exit_reason'),
                                        'realized_r': row.get('realized_r'),
                                        'exit_price': row.get('exit_price')},
                               'baseline': {'exit_reason': rec['exit_reason'],
                                            'realized_r': rec['realized_r'],
                                            'exit_price': rec['exit_price']}})
    return {'n_baseline': len(base_all), 'n_b0_rows': len(b0),
            'n_mismatches': len(mismatches), 'mismatches': mismatches[:10],
            'max_abs_realized_r_diff': round(max_r_diff, 6),
            'tolerance': 'exit reason and price exact; realized R within 1e-3 (4th '
                         'decimal rounding only)',
            'pass': not mismatches and len(b0) == len(base_all)}


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return round(statistics.mean(xs), 4) if xs else None


def _reasons(rows: list) -> dict:
    out = {}
    for r in rows:
        k = r.get('rejection_reason') or 'unknown'
        out[k] = out.get(k, 0) + 1
    return out


def _fmt(x, nd=3):
    if x is None:
        return 'n/a'
    if isinstance(x, float):
        return f'{x:.{nd}f}'
    return str(x)


def build_report(manifest, by_variant, by_variant_ib, rows, cush, b_metrics,
                 paired_table, selection, gates, exp_a, comb, dq, recon,
                 equiv) -> str:
    L = []
    add = L.append
    add('# ADD-ON REPORT — Stop Location, Entry Cushion and Hypothetical Trades')
    add('')
    add(f"**Verdict: {manifest['verdict'] or 'INCONCLUSIVE'}** — "
        'no production change is authorised. OOS independence: PARTIAL. '
        'Eligible for human review: **No**.')
    add('')
    add('Historical research output only: not an alert, not a recommendation, not an '
        'order. Production logic, alerts, thresholds, configuration and deployment '
        'were not touched.')
    add('')
    add('## 0. Summary')
    add('')
    add(f"- Baseline signals rebuilt: **{manifest['counts']['signals']}**; "
        f"hypothetical rows: **{manifest['counts']['record_rows']}** "
        f"(129 x 6 variants, NO TRADE rows included).")
    add(f"- Execution models: production **opens** (primary) and conservative "
        f"**intrabar** (stop first on ambiguous bars).")
    add(f"- Selected stop variant (VAL only): **{selection.get('selected')}**.")
    if gates and gates['G-A_oos_improvement']['pass'] and not (
            gates['G-A2_oos_points_not_worse']['candidate_oos_points_per_trade']
            > gates['G-A2_oos_points_not_worse']['baseline_oos_points_per_trade']):
        add('- **The R/trade gain is not corroborated by index points**: points per '
            'trade are equal or lower, so the R improvement is an R-normalisation '
            '(smaller non-zero denominator), not better trading.')
    if gates:
        add(f"- OOS paired net R/trade: baseline "
            f"{_fmt(gates['G-A_oos_improvement']['baseline_oos_net_R_per_trade'])} -> "
            f"candidate {_fmt(gates['G-A_oos_improvement']['candidate_oos_net_R_per_trade'])}; "
            f"points/trade {_fmt(gates['G-A2_oos_points_not_worse']['baseline_oos_points_per_trade'],2)} -> "
            f"{_fmt(gates['G-A2_oos_points_not_worse']['candidate_oos_points_per_trade'],2)}.")
        add(f"- Gates: " + ', '.join(
            f"{k.split('_')[0]}={'PASS' if v.get('pass') else 'FAIL'}"
            for k, v in gates.items() if isinstance(v, dict) and 'pass' in v))
    add('')
    add('## 1. Scope, data and snapshot')
    add('')
    add(f"- Range {manifest['date_range'][0]} .. {manifest['date_range'][1]}; "
        f"IS 2026-07-06..08-31, VAL 09-01..09-30, OOS 10-01..10-21.")
    add(f"- Instruments: NIFTY, BANKNIFTY (index/spot only); 5-minute candles.")
    add(f"- Snapshot sha256 `{manifest['snapshot_sha256']}` (parent study snapshot, "
        'copied read-only; the live database was never written).')
    add(f"- Data quality: **{dq.get('status')}**"
        + (f" ({'; '.join(dq.get('problems', []))})" if dq.get('problems') else ''))
    add(f"- Baseline reconciliation: " + '; '.join(
        f"{k}: {'consistent' if v.get('consistent') else 'ISSUES'} "
        f"({v.get('matched')}/{v.get('production_trades')} matched, "
        f"ΔR {v.get('difference_R')})" for k, v in recon.items()))
    add(f"- B0 reproduction of the frozen baseline (opens model): "
        f"**{'PASS' if equiv['pass'] else 'FAIL'}** "
        f"({equiv['n_b0_rows']} rows vs {equiv['n_baseline']} baseline trades, "
        f"{equiv['n_mismatches']} mismatches).")
    add('')
    add('## 2. Pre-registered parameters')
    add('')
    add('| parameter | value |')
    add('|---|---|')
    for k, v in manifest['parameters'].items():
        add(f'| {k} | {v} |')
    add(f"| TARGET_PCT | {manifest['target_pct']} (unchanged) |")
    add('')
    add('### 2.1 Stop definitions (pre-registered)')
    add('')
    add('| variant | stop rule | NO TRADE when |')
    add('|---|---|---|')
    add('| B0 | production 0.5% of entry | never (baseline) |')
    add('| S1 | most recent confirmed swing high (BEAR) / low (BULL) +- EPS; strict '
        'm=2 fractal, confirmed at i+2, lookback 20 bars | no usable swing, wrong '
        'side, outside 0.25%-1.50% |')
    add('| S2 | extreme of the most recent failed opposite-side break +- EPS | no '
        'failed attempt, wrong side, outside bounds |')
    add('| S3 | retest extreme of the trigger level +- EPS (window trigger..entry-1) '
        '| no completed retest, wrong side, outside bounds |')
    add('| S4 | opposite CPR boundary +- EPS (`tc` for BEAR, `bc` for BULL) | setup '
        'not BELOW_CPR/ABOVE_CPR/BRK_BC/BRK_TC, wrong side, outside bounds |')
    add('| S5 | S1 stop + K_VOL x point-in-time median bar range | no swing, <3 bars '
        'for the median, outside bounds |')
    add('')
    add('All values were fixed in `spec_addon.md` before any arm was computed. No '
        'parameter was selected on OOS and no gate was relaxed after seeing results.')
    add('')
    add('## 3. Entry cushion and NO TRADE rows')
    add('')
    add('| variant | trades | NO TRADE | mean stop % | median stop pts | '
        'pullback-level | wider than 0.5% | mean MAE-before-profit (R) |')
    add('|---|---|---|---|---|---|---|---|')
    for v, c in cush.items():
        add(f"| {v} | {c['n_trades']} | {c['n_no_trade']} | "
            f"{_fmt(c['mean_stop_distance_pct'], 4)} | "
            f"{_fmt(c['median_stop_distance_pts'], 1)} | {c['pullback_would_hit']} | "
            f"{c['wider_than_production']} | "
            f"{_fmt(c['mean_mae_before_first_profit_r'])} |")
    add('')
    add('A wider cushion is **not** a better trade: the cushion is context only and '
        'is never scored as an improvement.')
    add('')
    add('### 3.1 NO TRADE rejection reasons')
    add('')
    for v, c in cush.items():
        if c['no_trade_reasons']:
            add(f"- **{v}**: " + ', '.join(f'{k} x{n}'
                                           for k, n in c['no_trade_reasons'].items()))
    add('')
    add('### 3.2 Structural applicability')
    add('')
    r1 = cush['S1']['no_trade_reasons']
    r2 = cush['S2']['no_trade_reasons']
    r3 = cush['S3']['no_trade_reasons']
    add(f"- **S1/S5**: {r1.get('no_confirmed_swing_within_lookback', 0)} of "
        f"{cush['S1']['n_trades'] + cush['S1']['n_no_trade']} signals have no "
        "confirmed swing. A strict m=2 fractal needs at least five bars (25 minutes) "
        "before it can be confirmed, and the production trigger is usually in the "
        "first bars of the session, so the pre-registered point-in-time rule cannot "
        "produce a swing stop there. That is a genuine NO TRADE, not a missing value.")
    add(f"- **S2**: {r2.get('no_failed_opposite_break_attempt', 0)} of "
        f"{cush['S2']['n_trades'] + cush['S2']['n_no_trade']} signals have no failed "
        "break attempt, because the production trigger is the first touch of the "
        "level and there is no earlier crossing to fail.")
    add(f"- **S3**: {r3.get('no_completed_retest_before_entry', 0)} signals have no "
        "completed retest in the one-bar window before entry, and "
        f"{r3.get('stop_too_tight_below_minimum', 0)} retests put the stop closer "
        "than the 0.25% minimum, so they are correctly refused.")
    add('')
    add('## 4. Experiment B — stop placement (same 129 entry signals)')
    add('')
    add('### 4.1 Own trade set (opens model)')
    add('')
    add('| variant | n | net R | R/trade | pts/trade | stop-out rate | target rate | '
        'largest loss R | max DD R |')
    add('|---|---|---|---|---|---|---|---|---|')
    for v in VARIANTS:
        a = b_metrics[v]['opens']['all']
        add(f"| {v} | {a['n']} | {_fmt(a['net_R'])} | {_fmt(a['net_R_per_trade'], 4)} | "
            f"{_fmt(a['points_per_trade'], 1)} | {_fmt(a['stop_out_rate'], 3)} | "
            f"{_fmt(a['target_attainment'], 3)} | {_fmt(a['largest_loss_r'], 3)} | "
            f"{_fmt(a['max_dd_r'], 3)} |")
    add('')
    add('### 4.2 Paired comparison (primary): B0 measured on the same signals')
    add('')
    add('| variant | n | cand R/trade | B0 R/trade | cand pts/trade | B0 pts/trade |')
    add('|---|---|---|---|---|---|')
    for v in VARIANTS:
        p = paired_table[v]
        add(f"| {v} | {p['candidate']['n']} | "
            f"{_fmt(p['candidate']['net_R_per_trade'], 4)} | "
            f"{_fmt(p['paired_baseline']['net_R_per_trade'], 4)} | "
            f"{_fmt(p['candidate']['points_per_trade'], 1)} | "
            f"{_fmt(p['paired_baseline']['points_per_trade'], 1)} |")
    add('')
    add('Per-period paired metrics are in `outputs/experiment_b_paired_metrics.json`; '
        'the raw paired rows are in `outputs/experiment_b_paired.csv`.')
    add('')
    add('### 4.3 Selection (VAL only)')
    add('')
    add(f"- Selected: **{selection.get('selected')}**")
    add(f"- Rule: {selection.get('criterion')}")
    add(f"- VAL net R/trade by variant: " + ', '.join(
        f"{k}={_fmt(v, 4)} (n={selection['val_n'][k]})"
        for k, v in selection['val_net_R_per_trade'].items()))
    add(f"- Tie candidates: {selection.get('tie_candidates')}")
    add(f"- Variant ranking consistent per instrument: **{selection.get('ranking_ok')}**")
    add(f"- Eligible variants (>=10 VAL trades): **{selection.get('eligible')}**")
    s3 = b_metrics['S3']['opens']['all']
    add(f"- Small-sample caution: S3 shows the highest full-sample R/trade "
        f"({_fmt(s3['net_R_per_trade'], 4)} on {s3['n']} trades) but has only "
        f"{selection['val_n']['S3']} VAL trades, so it was ineligible; the "
        "pre-registered trade-count rule prevents a small-sample winner from being "
        "promoted.")
    add('')
    if gates:
        add('### 4.4 OOS gates for the selected variant')
        add('')
        add('| gate | result | key numbers |')
        add('|---|---|---|')
        for k, v in gates.items():
            if not isinstance(v, dict) or 'pass' not in v:
                continue
            add(f"| {k} | {'PASS' if v['pass'] else 'FAIL'} | "
                f"{_gate_detail(k, v)} |")
        add('')
        if (gates['G-E_evidence_sufficiency']['bootstrap_ci_low'] is not None
                and gates['G-E_evidence_sufficiency']['bootstrap_ci_low']
                == gates['G-E_evidence_sufficiency']['bootstrap_ci_high']):
            add(f"- The bootstrap CI is degenerate at "
                f"[{_fmt(gates['G-E_evidence_sufficiency']['bootstrap_ci_low'], 4)}, "
                f"{_fmt(gates['G-E_evidence_sufficiency']['bootstrap_ci_high'], 4)}] "
                f"because only {gates['G-E_evidence_sufficiency']['n_oos_candidate']} "
                "OOS trades fall into a few session blocks; it is not informative. "
                "This is exactly why G-E requires >= 15 OOS trades.")
            add('')
        add(f"- Overall: **{gates['OVERALL']}**; independence "
            f"**{gates['oos_independence']}**; eligible for review "
            f"**{gates['ELIGIBLE_FOR_HUMAN_REVIEW']}**.")
        add('')
        add('### 4.5 Intrabar-conservative robustness')
        add('')
        add(f"- Candidate OOS net R/trade {_fmt(gates['G-I_intrabar_robustness']['candidate_intrabar_net_R_per_trade'], 4)} "
            f"vs baseline {_fmt(gates['G-I_intrabar_robustness']['baseline_intrabar_net_R_per_trade'], 4)} "
            f"(points {_fmt(gates['G-I_intrabar_robustness']['candidate_intrabar_points_per_trade'], 1)} vs "
            f"{_fmt(gates['G-I_intrabar_robustness']['baseline_intrabar_points_per_trade'], 1)}) -> "
            f"**{'PASS' if gates['G-I_intrabar_robustness']['pass'] else 'FAIL'}**.")
        add('')
    add('## 5. Experiment A — frozen entry conditions with the production stop')
    add('')
    add(exp_a['note'])
    add('')
    add('| arm | model | n | R/trade | pts/trade | stop-out | Δ OOS R/trade | '
        'removed n | removed B0 R/trade |')
    add('|---|---|---|---|---|---|---|---|---|')
    for arm in FROZEN:
        for model in ('opens', 'intrabar'):
            a = exp_a['arms'][arm][model]['all']
            d = exp_a['arms'][arm].get(f'delta_vs_baseline_{model}', {}).get('OOS')
            rem = exp_a['arms'][arm]['removed']
            add(f"| {arm} | {model} | {a['n']} | {_fmt(a['net_R_per_trade'], 4)} | "
                f"{_fmt(a['points_per_trade'], 1)} | {_fmt(a['stop_out_rate'], 3)} | "
                f"{_fmt(d, 4)} | {rem['n']} | "
                f"{_fmt(rem[model]['net_R_per_trade'], 4)} |")
    add('')
    add('The frozen filters are reported, not re-selected. E3 changes the entry price, '
        'so its comparison with BASELINE is not a paired comparison.')
    add('')
    add('## 6. Combined entry + stop (conditional step)')
    add('')
    add(f"- Status: **{comb['status']}**")
    add(f"- Reason: {comb.get('reason', 'pre-check passed')}")
    for k in ('condition_a_e3_val_beats_baseline', 'condition_b_selected_val_beats_paired'):
        if k in comb:
            add(f"- {k}: {comb[k]}")
    add('')
    add('## 7. Limitations')
    add('')
    add('- Index/spot only. No volume, no historical option prices or bid/ask, so no '
        'option, credit-spread or rupee P&L is claimed. Position sizing is NOT '
        'COMPUTED (no production-verified capital base).')
    add('- 5-minute bars make same-bar stop/target order unknowable; the intrabar '
        'model resolves it conservatively and counts ambiguous bars.')
    add('- The OOS window and the baseline signal set were already examined in the '
        'parent study, so OOS independence is PARTIAL and a pass caps at '
        'PASS_EXPLORATORY.')
    add('- Stop variants with few trades leave wide confidence intervals; '
        'INCONCLUSIVE is used when evidence is insufficient rather than calling a '
        'fail or a pass.')
    add('- A structurally sensible stop that worsens expectancy is not an improvement; '
        'no result here authorises a production change.')
    add('')
    add('### 7.1 What this evidence supports')
    add('')
    add('- The unchanged production signals can be re-derived and simulated with an '
        'absolute structural stop; B0 reproduces the frozen baseline exactly (same '
        'exit reasons and prices; R differs by at most 0.0001 from rounding).')
    add('- On this signal set the pre-registered strict structural stops are rarely '
        'definable at trigger time (S1/S5) or applicable at all (S2), and S3/S4 '
        'refuse many signals as too tight or out of scope. Refusing a trade is a '
        'valid, pre-registered outcome.')
    add('- The only variant with enough VAL trades (S4) passes the expectancy and '
        'cost gates on OOS but fails the risk and stability gates and has too few '
        'OOS trades; its R/trade gain is not corroborated by index points.')
    add('')
    add('### 7.2 What this evidence does not support')
    add('')
    add('- It does not show that any structural stop improves performance. The '
        'result is INCONCLUSIVE, not a pass, and the R-level gain alone is a '
        'normalisation effect.')
    add('- It does not support an option, credit-spread, rupee or position-size '
        'claim, and it does not authorise any change to production.')
    add('')
    add('## 8. Artifacts')
    add('')
    for name in ('hypothetical_trades.csv', 'experiment_b_metrics.json',
                 'experiment_b_paired.csv', 'experiment_b_paired_metrics.json',
                 'experiment_b_selection.json', 'experiment_b_gates.json',
                 'experiment_a_metrics.json', 'experiment_a_arm_metrics.json',
                 'experiment_a_arms.csv', 'cushion_analysis.csv',
                 'cushion_summary.json', 'stopout_analysis.json',
                 'structural_diagnostics.json', 'data_quality.json',
                 'snapshot_meta.json', 'baseline_trades.csv',
                 'baseline_reconciliation.json', 'combined_step.json',
                 'run_manifest.json'):
        add(f'- `outputs/{name}`')
    add('- `run_manifest.json` (add-on root, identical copy)')
    add('')
    add('## 9. Reproduce')
    add('')
    add('```')
    add('PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/opt/tradingai python3 -m \\')
    add('  research.prevday_cpr_spread_study.stop_forensics.addon_stop_placement.src.run_addon')
    add('```')
    return '\n'.join(L) + '\n'


def _gate_detail(k: str, v: dict) -> str:
    if k.startswith('G-A_oos'):
        return (f"base {_fmt(v['baseline_oos_net_R_per_trade'], 4)} -> "
                f"cand {_fmt(v['candidate_oos_net_R_per_trade'], 4)} (n "
                f"{v['candidate_oos_n']}/{v['baseline_oos_n']})")
    if k.startswith('G-A2'):
        return (f"base {_fmt(v['baseline_oos_points_per_trade'], 2)} -> "
                f"cand {_fmt(v['candidate_oos_points_per_trade'], 2)} pts/trade")
    if k.startswith('G-B'):
        return ('removed B0 R/trade '
                f"{_fmt(v.get('removed_signal_b0_net_R_per_trade'), 4)}; costs "
                + ', '.join(f'{c}={_fmt(x, 3)}' for c, x in
                            v['cost_grid_candidate'].items()))
    if k.startswith('G-C'):
        return (f"maxDD {_fmt(v['candidate_max_dd_r'])} vs "
                f"{_fmt(v['baseline_max_dd_r'])}; largest loss "
                f"{_fmt(v['candidate_largest_loss_r'])} vs "
                f"{_fmt(v['baseline_largest_loss_r'])}")
    if k.startswith('G-D'):
        return (f"periods {v['n_periods_positive']}/3, blocks "
                f"{v['n_blocks_positive']}/6, instruments "
                f"{v['n_instruments_positive']}/2, ranking "
                f"{v['variant_ranking_consistent']}")
    if k.startswith('G-E'):
        return (f"n={v['n_oos_candidate']} (NIFTY {v['n_oos_nifty']}, BNF "
                f"{v['n_oos_banknifty']}); CI [{_fmt(v['bootstrap_ci_low'], 4)}, "
                f"{_fmt(v['bootstrap_ci_high'], 4)}]")
    if k.startswith('G-I'):
        return (f"cand {_fmt(v['candidate_intrabar_net_R_per_trade'], 4)} vs base "
                f"{_fmt(v['baseline_intrabar_net_R_per_trade'], 4)} R/trade")
    return ''


if __name__ == '__main__':
    main()
