"""Experiment orchestration for the setup-first study.

The pipeline is:

  A. setup identification + state machine (per arm),
  B. Experiment B - entry timing (confirmation rule) against the frozen baseline,
  C. Experiment C - stop placement on the frozen entry policy,
  D. Experiment D - the combined candidate, looked at out-of-sample exactly once
     and only when the pre-declared validation gates pass on the validation split,
  E. robustness, stop-out forensics, opportunity accounting, gates.

Selection happens on the validation split only. The out-of-sample split is
never used to choose a parameter and is never re-used after it has been read.
"""
from __future__ import annotations

import json

from research.prevday_cpr_spread_study.stop_forensics.src import metrics as pmetrics
from research.prevday_cpr_spread_study.stop_forensics.addon_stop_placement.src import \
    metrics_ext as xmetrics
from research.prevday_cpr_spread_study.stop_forensics.src import candidates, forensics as pforensics

from . import config, engine, records, stops

# ---------------------------------------------------------------- pre-registered arms
BASE_PARAMS = {'zone_pct': config.ZONE_PCT, 'expiry_bars': config.EXPIRY_BARS}

# Neighbouring settings of the entry policy (used by the stability gate only).
NEIGHBOUR_ARMS = {
    'SF_C1_S0_Z10_E12': {'rule': 'C1_CLOSE_BACK', 'stop': 'S0',
                         'params': {'zone_pct': 0.0010, 'expiry_bars': 12}},
    'SF_C2_S0_Z10_E12': {'rule': 'C2_REJECTION_CLOSE', 'stop': 'S0',
                         'params': {'zone_pct': 0.0010, 'expiry_bars': 12}},
    'SF_C1_S0_Z07_E12': {'rule': 'C1_CLOSE_BACK', 'stop': 'S0',
                         'params': {'zone_pct': 0.0007, 'expiry_bars': 12}},
    'SF_C1_S0_Z15_E12': {'rule': 'C1_CLOSE_BACK', 'stop': 'S0',
                         'params': {'zone_pct': 0.0015, 'expiry_bars': 12}},
    'SF_C1_S0_Z10_E06': {'rule': 'C1_CLOSE_BACK', 'stop': 'S0',
                         'params': {'zone_pct': 0.0010, 'expiry_bars': 6}},
    'SF_C1_S0_Z10_E18': {'rule': 'C1_CLOSE_BACK', 'stop': 'S0',
                         'params': {'zone_pct': 0.0010, 'expiry_bars': 18}},
}

SELECTION_MIN_TRADES = 10


# ----------------------------------------------------------------------- helpers
def _period(records, p):
    return [r for r in records if r['period'] == p]


def _agg(records):
    return xmetrics.agg_ext(records)


RULE_SHORT = {'C1_CLOSE_BACK': 'C1', 'C2_REJECTION_CLOSE': 'C2'}


def _arm_name(rule, stop_variant):
    return f'SF_{RULE_SHORT[rule]}_{stop_variant}'


def _rule_of_arm(arm):
    """'SF_C1_S0' -> 'C1_CLOSE_BACK' (the arm name is not a rule key)."""
    short = str(arm).split('_')[1]
    return {v: k for k, v in RULE_SHORT.items()}[short]


def _stop_of_arm(arm):
    """'SF_C1_S3' -> 'S3'."""
    return str(arm).split('_')[2]


def _ctx_of(setup):
    return setup['ctx']


def build_arm(base_setups, rule, params, stop_variant):
    """Run the state machine and the entry gates for one arm."""
    rows = []
    eligible = []
    for s in base_setups:
        arm_setup = dict(s)
        arm_setup['zone_pct'] = params['zone_pct']
        arm_setup['expiry_bars'] = params['expiry_bars']
        L = arm_setup['level_price']
        arm_setup['zone_low'] = L - L * params['zone_pct']
        arm_setup['zone_high'] = L + L * params['zone_pct']
        arm_setup['confirm_rule'] = rule
        arm_setup['transitions'] = []
        ctx = _ctx_of(s)
        scan = ctx['scan']
        tracker = engine.SetupTracker(arm_setup, scan)
        tracker.run()
        row = records.setup_rows([arm_setup])[0]
        row['arm'] = _arm_name(rule, stop_variant)
        row['stop_variant'] = stop_variant
        row['confirm_rule'] = rule
        row['zone_pct'] = params['zone_pct']
        row['expiry_bars'] = params['expiry_bars']
        if arm_setup['state'] != config.STATE_CONFIRMED:
            row['decision'] = config.STATE_NO_TRADE
            row['decision_reasons'] = [arm_setup.get('rejection_reason') or 'no_confirmation']
            rows.append(row)
            continue
        core = engine.plan_entry_core(arm_setup, scan)
        row['entry_plan'] = {k: v for k, v in core.items() if k != 'decision'}
        if core['decision'] != 'PENDING_STOP_GATES':
            row['decision'] = core['decision']
            row['decision_reasons'] = core['reasons']
            rows.append(row)
            continue
        entry = core['entry']
        entry_idx = core['entry_idx']
        stop_set = stops.stop_setups(arm_setup, scan, entry, entry_idx,
                                     levels=arm_setup.get('bundle'))
        sv = stop_set[stop_variant]
        if not sv['available']:
            row['decision'] = config.STATE_NO_TRADE
            row['decision_reasons'] = [f'stop_unavailable:{sv["source"]}']
            row['stop_source'] = sv['source']
            rows.append(row)
            continue
        target = entry * (1 - config.TARGET_PCT)
        gated = engine.apply_stop_gates(core, sv['stop_price'], target)
        row['decision'] = gated['decision']
        row['decision_reasons'] = gated['reasons']
        row['stop_price'] = sv['stop_price']
        row['stop_source'] = sv['source']
        row['target_price'] = gated.get('target_price')
        row['rr'] = gated.get('rr')
        row['risk_pts'] = gated.get('risk_pts')
        row['risk_pct'] = gated.get('risk_pct')
        if gated['decision'] == config.STATE_TRADE_ELIGIBLE:
            eligible.append((arm_setup, ctx, core, gated, sv))
        rows.append(row)

    # ---- one opportunity, one trade (no re-entry rule is declared) ---------
    eligible.sort(key=lambda t: (t[0]['confirm_idx'], t[0]['arrival_idx'],
                                  t[0]['setup_id']))
    seen = set()
    trades = []
    for arm_setup, ctx, core, gated, sv in eligible:
        key = (arm_setup['instrument'], arm_setup['session_date'])
        row = next(r for r in rows if r['setup_id'] == arm_setup['setup_id'])
        if key in seen:
            row['decision'] = config.STATE_NO_TRADE
            row['decision_reasons'] = ['one_trade_per_session']
            continue
        seen.add(key)
        rec = records.build_trade(arm_setup, ctx, core['entry'], core['entry_idx'],
                                   sv['stop_price'], gated['target_price'],
                                   arm=_arm_name(rule, stop_variant),
                                   stop_source=sv['source'], stop_variant=stop_variant,
                                   confirm_rule=rule)
        if rec is None:
            row['decision'] = config.STATE_NO_TRADE
            row['decision_reasons'] = ['missing_eod_exit']
            continue
        trades.append(rec)
    return rows, trades


def funnel(rows):
    """Experiment A - setup arrival and confirmation statistics."""
    out = {}
    for r in rows:
        fam = r['setup_family']
        b = out.setdefault(fam, {
            'identified': 0, 'zone_reached': 0, 'confirmed': 0, 'expired': 0,
            'invalidated': 0, 'no_trade': 0, 'no_trade_never_confirmed': 0,
            'missed': 0, 'trade_eligible': 0,
            'arrival_minutes': [], 'confirmation_minutes': [],
            'sessions': set()})
        b['identified'] += 1
        b['sessions'].add((r['instrument'], r['session_date']))
        if r.get('arrival_idx') is not None:
            # the price reached the zone (the final state of a confirmed setup is
            # CONFIRMED, so the arrival cannot be read from the final state)
            b['zone_reached'] += 1
        st = r['state']
        if st == config.STATE_ZONE_REACHED:
            b['zone_reached_only'] = b.get('zone_reached_only', 0) + 1
        elif st == config.STATE_CONFIRMED:
            b['confirmed'] += 1
        elif st == config.STATE_EXPIRED:
            b['expired'] += 1
        elif st == config.STATE_INVALIDATED:
            b['invalidated'] += 1
        if r.get('minutes_to_arrival') is not None:
            b['arrival_minutes'].append(r['minutes_to_arrival'])
        if r.get('minutes_to_confirmation') is not None:
            b['confirmation_minutes'].append(r['minutes_to_confirmation'])
        d = r.get('decision')
        if d == config.STATE_TRADE_ELIGIBLE:
            b['trade_eligible'] += 1
        elif d == config.STATE_NO_TRADE:
            # a setup that never reached the confirmation has no entry decision;
            # only the confirmed setups are counted as an entry-gate refusal
            if st == config.STATE_CONFIRMED:
                b['no_trade'] += 1
            else:
                b['no_trade_never_confirmed'] += 1
        elif d == config.STATE_MISSED:
            b['missed'] += 1
    out2 = {}
    for fam, b in out.items():
        arr = sorted(b['arrival_minutes'])
        con = sorted(b['confirmation_minutes'])
        out2[fam] = {
            'identified': b['identified'],
            'instrument_sessions': len(b['sessions']),
            'zone_reached': b['zone_reached'],
            'confirmed': b['confirmed'],
            'expired': b['expired'],
            'invalidated': b['invalidated'],
            'trade_eligible': b['trade_eligible'],
            'no_trade': b['no_trade'],
            'no_trade_never_confirmed': b['no_trade_never_confirmed'],
            'missed': b['missed'],
            'arrival_rate_pct': round(100 * b['zone_reached'] / b['identified'], 2)
            if b['identified'] else None,
            'confirmation_rate_pct': round(100 * b['confirmed'] / b['identified'], 2)
            if b['identified'] else None,
            'median_minutes_to_arrival': arr[len(arr) // 2] if arr else None,
            'median_minutes_to_confirmation': con[len(con) // 2] if con else None,
        }
    return out2


def _by(records, keyfn):
    out = {}
    for r in records:
        out.setdefault(keyfn(r), []).append(r)
    return out


def breakdown(records, label):
    """Robustness breakdown (instrument, period, family, session-time)."""
    def hour(r):
        return str(r.get('entry_time', ''))[11:13] + ':00'

    def family(r):
        return r.get('setup_family') or 'BASELINE (production trigger)'

    out = {'label': label, 'n': len(records)}
    for name, keyfn in (('instrument', lambda r: r['instrument']),
                        ('period', lambda r: r['period']),
                        ('setup_family', family),
                        ('entry_hour', hour),
                        ('exit_reason', lambda r: r['exit_reason'])):
        rows = {}
        for k, recs in sorted(_by(records, keyfn).items()):
            a = _agg(recs)
            rows[str(k)] = {'n': a['n'], 'net_R_per_trade': a['net_R_per_trade'],
                            'points_per_trade': a['points_per_trade'],
                            'stop_out_rate': a['stop_out_rate'],
                            'target_attainment': a['target_attainment'],
                            'mean_mae_r': a['mean_mae_r'],
                            'max_dd_r': a['max_dd_r']}
        out[name] = rows
    # concentration
    if records:
        rs = sorted((r['realized_pts'] for r in records), reverse=True)
        best = sum(rs[:3])
        total = sum(rs)
        out['concentration'] = {
            'best_3_trades_points': round(best, 2),
            'total_points': round(total, 2),
            'best_3_share_pct': round(100 * best / total, 1) if total else None,
            'note': ('a high share means the result depends on a handful of trades; '
                     'index points only, never rupees'),
        }
    return out


def select_on_val(arms, stage='VAL', min_n=SELECTION_MIN_TRADES, primary='net_R_per_trade'):
    """Pre-declared selection rule on the validation split only."""
    scored = []
    for name in sorted(arms):
        recs = _period(arms[name], stage)
        if len(recs) < min_n:
            continue
        a = _agg(recs)
        if primary == 'net_R_per_trade':
            key = (a['net_R_per_trade'], a['points_per_trade'])
        else:
            key = (a['points_per_trade'], a['net_R_per_trade'])
        scored.append({'arm': name, 'n': len(recs),
                       'val_net_R_per_trade': a['net_R_per_trade'],
                       'val_points_per_trade': a['points_per_trade'],
                       'val_net_R': a['net_R'],
                       'key': key})
    if not scored:
        return None, {'selected': None, 'reason': 'no arm reached the minimum '
                       f'validation sample of {min_n} trades', 'candidates': []}
    scored.sort(key=lambda r: (-r['key'][0], -r['key'][1], r['arm']))
    best = scored[0]
    return best['arm'], {'selected': best['arm'], 'primary_metric': primary,
                         'min_val_trades': min_n, 'candidates': scored,
                         'reason': 'highest validation score among the arms that '
                                   'reached the minimum validation sample'}


def stopped_forward(record, candles, horizon_bars=12):
    """Forward path after a stop-out: 12 bars and the remainder of the session."""
    ts = record['exit_time'].replace(' ', 'T')
    idx = next((i for i, c in enumerate(candles)
                if str(c['timestamp'])[:16] == str(ts)[:16]), None)
    if idx is None:
        return {'note': 'exit bar not found'}
    direction = record['direction']
    fwd = candles[idx + 1:idx + 1 + horizon_bars]
    adv = fav = 0.0
    for c in fwd:
        hi, lo = float(c['high']), float(c['low'])
        a = (hi - record['exit_price']) if direction == 'BEAR' else (record['exit_price'] - lo)
        f = (record['exit_price'] - lo) if direction == 'BEAR' else (hi - record['exit_price'])
        adv = max(adv, a)
        fav = max(fav, f)
    rest = []
    for c in candles[idx + 1:]:
        if str(c['timestamp'])[11:16] >= config.ENTRY_OPEN_MAX:
            break
        rest.append(c)
    if rest:
        last_close = float(rest[-1]['close'])
        pts = ((record['exit_price'] - last_close) if direction == 'BEAR'
               else (last_close - record['exit_price']))
        r = pts / record['risk_pts'] if record['risk_pts'] else None
    else:
        pts, r = None, None
    return {
        'bars_after_exit_12': len(fwd),
        'max_adverse_pts_12bars': round(adv, 2),
        'max_favourable_pts_12bars': round(fav, 2),
        'adverse_exceeds_favourable': bool(adv > fav),
        'remainder_pts': None if pts is None else round(pts, 2),
        'remainder_r': None if r is None else round(r, 4),
        'remainder_bars': len(rest),
        'fwd15_r': record.get('fwd15_r'), 'fwd30_r': record.get('fwd30_r'),
        'fwd60_r': record.get('fwd60_r'),
    }


# --------------------------------------------------------------- main pipeline
def run_experiments(all_setups, universe, base_records, dq, univ_prod, engine_mod,
                    out, reports, run_dir):
    """Run experiments A-D, robustness, forensics and the gates."""
    from . import gates, reporting

    pmetrics.write_json(str(out / 'selection.json'), {'status': 'running'})

    # ---- build the arms ---------------------------------------------------
    arms = {}
    arm_rows = {}
    for rule in engine.CONFIRM_RULES:
        for sv in stops.STOP_VARIANTS:
            name = _arm_name(rule, sv)
            rows, trades = build_arm(all_setups, rule, BASE_PARAMS, sv)
            arms[name] = trades
            arm_rows[name] = rows
    neighbour_records = {}
    for name, spec in NEIGHBOUR_ARMS.items():
        rows, trades = build_arm(all_setups, spec['rule'], spec['params'], spec['stop'])
        neighbour_records[name] = trades
        arm_rows[name] = rows
    log_rows = []
    for name, rows in arm_rows.items():
        for r in rows:
            log_rows.append(r)
    pmetrics.write_csv(str(out / 'setup_state_rows.csv'), log_rows)

    # ---- Experiment A: arrival and confirmation ----------------------------
    exp_a = {
        'question': 'How often does price reach a pre-defined zone, and how often '
                    'is the confirmation observed afterwards?',
        'by_family': funnel(arm_rows['SF_C1_S0']),
        'by_family_confirmation_C2': funnel(arm_rows['SF_C2_S0']),
        'note': 'a setup that never reaches its zone is EXPIRED; a setup whose '
                'price closed through the zone before arrival is INVALIDATED',
    }
    exp_a['totals'] = {}
    counters = ('identified', 'instrument_sessions', 'zone_reached', 'confirmed',
                'expired', 'invalidated', 'trade_eligible', 'no_trade',
                'no_trade_never_confirmed', 'missed')
    for fam, b in exp_a['by_family'].items():
        for k in counters:
            exp_a['totals'][k] = exp_a['totals'].get(k, 0) + b.get(k, 0)
    t = exp_a['totals']
    t['arrival_rate_pct'] = round(100 * t['zone_reached'] / t['identified'], 2) \
        if t['identified'] else None
    t['confirmation_rate_pct'] = round(100 * t['confirmed'] / t['identified'], 2) \
        if t['identified'] else None
    t['note'] = ('an identified setup can reach the zone and still end in EXPIRED '
                 'or INVALIDATED, so the rates are not additive')
    pmetrics.write_json(str(out / 'experiment_A_funnel.json'), exp_a)

    # ---- Experiment B: entry timing ---------------------------------------
    b_arms = {'SF_C1_S0': arms['SF_C1_S0'], 'SF_C2_S0': arms['SF_C2_S0']}
    exp_b = {'question': 'Does waiting for the zone and the confirmation change the '
                         'entry relative to the frozen production trigger?',
             'baseline_arm': 'BASELINE (production, unchanged)',
             'arms': {}, 'selection': {}}
    for name, recs in b_arms.items():
        exp_b['arms'][name] = {
            'by_period': {p: _agg(_period(recs, p)) for p in ('IS', 'VAL', 'OOS')},
            'by_instrument': {i: _agg([r for r in recs if r['instrument'] == i])
                              for i in config.INSTRUMENTS},
            'by_family': {f: _agg([r for r in recs if r['setup_family'] == f])
                          for f in sorted({r['setup_family'] for r in recs})},
        }
    exp_b['baseline'] = {
        'by_period': {p: _agg(_period(base_records, p)) for p in ('IS', 'VAL', 'OOS')},
        'by_instrument': {i: _agg([r for r in base_records if r['instrument'] == i])
                          for i in config.INSTRUMENTS},
    }
    selected_arm, b_sel = select_on_val(b_arms, 'VAL', primary='net_R_per_trade')
    exp_b['selection'] = b_sel
    if selected_arm is None:
        rule_selected = 'C1_CLOSE_BACK'
        b_sel['fallback'] = 'C1_CLOSE_BACK (pre-registered default; no arm reached ' \
                            'the minimum validation sample)'
    else:
        rule_selected = _rule_of_arm(selected_arm)
    exp_b['selected_rule'] = rule_selected
    exp_b['selected_arm'] = selected_arm
    exp_b['selection_metric'] = 'VAL net R per trade (both arms use the same 0.5 % ' \
                                'stop, so the R denominator is identical)'

    # ---- Experiment C: stop placement on the frozen entry policy ----------
    stop_arms = {_arm_name(rule_selected, sv): arms[_arm_name(rule_selected, sv)]
                 for sv in stops.STOP_VARIANTS}
    exp_c = {'question': 'With the entry policy frozen, which stop placement rule '
                         'behaves best?',
             'entry_policy': rule_selected,
             'arms': {}, 'selection': {}}
    for name, recs in stop_arms.items():
        exp_c['arms'][name] = {
            'by_period': {p: _agg(_period(recs, p)) for p in ('IS', 'VAL', 'OOS')},
            'availability': _stop_availability(arm_rows[name]),
            'mean_stop_distance_pct': _mean_stop_distance(recs),
        }
    selected_stop_arm, c_sel = select_on_val(stop_arms, 'VAL',
                                              primary='points_per_trade')
    exp_c['selection'] = c_sel
    exp_c['selection_metric'] = ('VAL index points per trade (denominator-free: '
                                 'comparing R per trade across different stop widths '
                                 'would reward a larger risk denominator)')
    if selected_stop_arm is None:
        stop_selected = 'S0'
        c_sel['fallback'] = 'S0 (pre-registered default; no stop arm reached the ' \
                            'minimum validation sample)'
    else:
        stop_selected = _stop_of_arm(selected_stop_arm)
    exp_c['selected_stop'] = stop_selected
    exp_c['selected_arm'] = selected_stop_arm

    # ---- the combined candidate ------------------------------------------
    candidate_arm = _arm_name(rule_selected, stop_selected)
    cand_records = arms[candidate_arm]
    exp_d = {'candidate_arm': candidate_arm,
             'entry_policy': rule_selected, 'stop_variant': stop_selected,
             'question': 'Does the combined entry+stop candidate pass the '
                         'pre-declared gates?'}

    # ---- validation pre-check --------------------------------------------
    pre = gates.val_precheck(cand_records, base_records,
                              dq_status=dq.get('status'),
                              dq_problems=dq.get('problems', []))
    exp_d['validation_precheck'] = pre
    pre_pass = pre['_verdict'] == 'PASS'
    exp_d['experiment_d_run'] = pre_pass
    exp_d['experiment_d_note'] = (
        'Experiment D runs only when the entry candidate passes the pre-declared '
        'gates on the validation split. The out-of-sample split is then read once.')

    # ---- out-of-sample evaluation ----------------------------------------
    cand_sessions = {(r['instrument'], r['session_date']) for r in cand_records}
    removed_oos = [r for r in base_records
                   if r['period'] == 'OOS'
                   and (r['instrument'], r['session_date']) not in cand_sessions]
    oos_days = sorted({r['session_date'] for r in base_records if r['period'] == 'OOS'})
    bootstrap = pmetrics.block_bootstrap(
        [r for r in base_records if r['period'] == 'OOS'],
        [r for r in cand_records if r['period'] == 'OOS'], oos_days)
    conflicts = {'sessions_with_conflict': len(candidates.detect_conflicts(
        univ_prod[config.INSTRUMENTS[0]], engine_mod))}
    arm_records = dict(neighbour_records)
    arm_records[candidate_arm] = cand_records
    selection = {candidate_arm: 'SF'}
    if pre_pass:
        oos_gates = gates.final_oos_gates(
            base_records=base_records, cand_records=cand_records, days=oos_days,
            arm_records=arm_records, selection=selection,
            removed_records=removed_oos, dq_status=dq.get('status'),
            dq_problems=dq.get('problems', []), conflicts=conflicts,
            bootstrap=bootstrap)
        exp_d['oos_gates'] = oos_gates
        verdict = 'PASS_EXPLORATORY' if oos_gates['ELIGIBLE_FOR_HUMAN_REVIEW'] \
            else 'INCONCLUSIVE'
        exp_d['verdict'] = verdict
    else:
        exp_d['oos_gates'] = None
        exp_d['oos_descriptive_only'] = {
            'note': ('the validation pre-check did not pass, so the out-of-sample '
                     'split is reported for description only and is NOT a '
                     'validation of the candidate'),
            'candidate_by_period': {p: _agg(_period(cand_records, p))
                                    for p in ('IS', 'VAL', 'OOS')},
            'baseline_by_period': {p: _agg(_period(base_records, p))
                                   for p in ('IS', 'VAL', 'OOS')},
            'bootstrap': bootstrap,
        }
        exp_d['verdict'] = 'INCONCLUSIVE'

    pmetrics.write_json(str(out / 'experiment_A_funnel.json'), exp_a)
    pmetrics.write_json(str(out / 'experiment_B.json'), exp_b)
    pmetrics.write_json(str(out / 'experiment_C.json'), exp_c)
    pmetrics.write_json(str(out / 'experiment_D.json'), exp_d)

    # ---- robustness --------------------------------------------------------
    opp_rows = _opportunity_accounting(base_records, cand_records,
                                     arm_rows[candidate_arm])
    rob = {
        'candidate': breakdown(cand_records, candidate_arm),
        'baseline': breakdown(base_records, 'BASELINE'),
        'cost_grid_candidate': pmetrics.cost_grid(cand_records),
        'cost_grid_baseline': pmetrics.cost_grid(base_records),
        'walk_forward_blocks': _walk_forward(cand_records, base_records, oos_days),
        'opportunity_accounting': opp_rows,
        'neighbour_arms': {k: {p: _agg(_period(v, p)) for p in ('IS', 'VAL', 'OOS')}
                            for k, v in neighbour_records.items()},
        'baseline_by_period': {p: _agg(_period(base_records, p))
                               for p in ('IS', 'VAL', 'OOS')},
        'candidate_by_period': {p: _agg(_period(cand_records, p))
                                for p in ('IS', 'VAL', 'OOS')},
    }
    pmetrics.write_json(str(out / 'robustness.json'), rob)
    pmetrics.write_csv(str(out / 'opportunity_accounting.csv'), opp_rows)
    pmetrics.write_csv(str(out / 'experiment_D_trades.csv'), cand_records)
    pmetrics.write_csv(str(out / 'experiment_B_trades_C1.csv'), arms['SF_C1_S0'])
    pmetrics.write_csv(str(out / 'experiment_B_trades_C2.csv'), arms['SF_C2_S0'])
    for sv in stops.STOP_VARIANTS:
        pmetrics.write_csv(str(out / f'experiment_C_trades_{sv}.csv'),
                            arms[_arm_name(rule_selected, sv)])

    # ---- stop-out forensics ----------------------------------------------
    forensics = _stop_out_forensics(base_records, cand_records, univ_prod,
                                     engine_mod)
    pmetrics.write_json(str(out / 'stop_out_forensics.json'), forensics)

    # ---- reports -----------------------------------------------------------
    reporting.write_all(reports=reports, out=out, run_dir=run_dir,
                         exp_a=exp_a, exp_b=exp_b, exp_c=exp_c, exp_d=exp_d,
                         rob=rob, forensics=forensics, pre=pre, dq=dq,
                         base_records=base_records, cand_records=cand_records,
                         candidate_arm=candidate_arm, rule_selected=rule_selected,
                         stop_selected=stop_selected,
                         all_setups=all_setups, arm_rows=arm_rows)
    return {'verdict': exp_d['verdict'], 'selected_entry_policy': rule_selected,
            'selected_stop': stop_selected, 'candidate_arm': candidate_arm,
            'candidate_trades': len(cand_records),
            'experiment_d_run': pre_pass}


def _stop_availability(rows):
    out = {}
    for r in rows:
        sv = r.get('stop_variant')
        if not sv:
            continue
        b = out.setdefault(sv, {'confirmed_setups': 0, 'stop_available': 0,
                                 'no_trade_stop_unavailable': 0, 'trade_eligible': 0,
                                 'other_no_trade': 0, 'missed': 0, 'reasons': {}})
        if r['state'] != config.STATE_CONFIRMED:
            continue
        b['confirmed_setups'] += 1
        reasons = r.get('decision_reasons') or []
        for reason in reasons:
            key = str(reason)
            b['reasons'][key] = b['reasons'].get(key, 0) + 1
        if any(str(x).startswith('stop_unavailable') for x in reasons):
            b['no_trade_stop_unavailable'] += 1
        elif r.get('decision') == config.STATE_TRADE_ELIGIBLE:
            b['stop_available'] += 1
            b['trade_eligible'] += 1
        elif r.get('decision') == config.STATE_MISSED:
            b['missed'] += 1
        else:
            b['other_no_trade'] += 1
    return out


def _mean_stop_distance(recs):
    vals = [r.get('stop_distance_pct') for r in recs if r.get('stop_distance_pct')]
    return round(sum(vals) / len(vals), 6) if vals else None


def _walk_forward(cand, base, days):
    blocks = pmetrics.session_blocks(days, 6)
    rows = []
    for i, b in enumerate(blocks):
        crr = [r for r in cand if r['session_date'] in b]
        brr = [r for r in base if r['session_date'] in b]
        ca, ba = _agg(crr), _agg(brr)
        rows.append({'block': i + 1, 'sessions': len(b), 'candidate_n': ca['n'],
                     'baseline_n': ba['n'],
                     'candidate_net_R_per_trade': ca['net_R_per_trade'],
                     'baseline_net_R_per_trade': ba['net_R_per_trade'],
                     'candidate_points_per_trade': ca['points_per_trade'],
                     'baseline_points_per_trade': ba['points_per_trade'],
                     'candidate_positive': bool(ca['net_R_per_trade'] is not None
                                                and ca['net_R_per_trade'] > 0)})
    return rows


def _opportunity_accounting(base_records, cand_records, rows):
    """For every baseline trigger: what did the setup-first engine do?"""
    by_session = {}
    for r in rows:
        key = (r['instrument'], r['session_date'])
        by_session.setdefault(key, []).append(r)
    cand_by_session = {}
    for r in cand_records:
        cand_by_session.setdefault((r['instrument'], r['session_date']), []).append(r)
    out = []
    for b in base_records:
        key = (b['instrument'], b['session_date'])
        srows = sorted(by_session.get(key, []),
                       key=lambda r: (r.get('minutes_to_confirmation') is None,
                                      r.get('minutes_to_confirmation') or 0))
        srow = srows[0] if srows else None
        ctr = cand_by_session.get(key, [])
        out.append({
            'instrument': b['instrument'],
            'session_date': b['session_date'],
            'baseline_level': b['setup'],
            'baseline_signal_time': b['signal_time'],
            'baseline_entry_time': b['entry_time'],
            'baseline_realized_r': b['realized_r'],
            'baseline_realized_pts': b['realized_pts'],
            'baseline_exit_reason': b['exit_reason'],
            'setup_first_family': srow['setup_family'] if srow else None,
            'setup_first_state': srow['state'] if srow else 'NO_SETUP_IDENTIFIED',
            'setup_first_arrival': srow.get('arrival_ts') if srow else None,
            'setup_first_confirm': srow.get('confirm_ts') if srow else None,
            'setup_first_decision': srow.get('decision') if srow else None,
            'setup_first_reasons': ';'.join(srow.get('decision_reasons') or []) if srow else None,
            'candidate_entry_time': ctr[0]['entry_time'] if ctr else None,
            'candidate_realized_r': ctr[0]['realized_r'] if ctr else None,
            'candidate_realized_pts': ctr[0]['realized_pts'] if ctr else None,
            'candidate_exit_reason': ctr[0]['exit_reason'] if ctr else None,
            'outcome': ('CANDIDATE_TRADED' if ctr else
                        ('CANDIDATE_NO_TRADE' if srow else 'NO_SETUP_IDENTIFIED')),
        })
    return out


def _stop_out_forensics(base_records, cand_records, univ_prod, engine_mod):
    """Classify every stop-out: the baseline and the candidate."""
    widths = []
    for inst in config.INSTRUMENTS:
        for ctx in univ_prod[inst]['sessions'].values():
            if ctx.get('cpr_width_pct') is not None:
                widths.append(ctx['cpr_width_pct'])
    widths.sort()

    def q(p):
        if not widths:
            return None
        k = max(0, min(len(widths) - 1, int(p * len(widths))))
        return widths[k]
    cpr_stats = {'q25': q(0.25), 'q75': q(0.75)}

    out = {'cpr_stats': cpr_stats, 'baseline': [], 'candidate': []}
    for inst in config.INSTRUMENTS:
        signals = univ_prod[inst]['signals']
        recs = [r for r in base_records if r['instrument'] == inst]
        for rec, sig in zip(recs, signals):
            if rec['exit_reason'] != 'STOP':
                continue
            flags = pforensics.classify(rec, sig, engine_mod, cpr_stats)
            cat = pforensics.missed_direction_category(rec, sig, engine_mod)
            out['baseline'].append({
                'instrument': inst, 'session_date': rec['session_date'],
                'entry_time': rec['entry_time'], 'exit_time': rec['exit_time'],
                'entry': rec['entry'], 'exit_price': rec['exit_price'],
                'level': rec['setup'], 'realized_r': rec['realized_r'],
                'realized_pts': rec['realized_pts'],
                'stop_overshoot_pts': rec['stop_overshoot_pts'],
                'flags': flags, 'missed_direction': cat,
            })
    for rec in cand_records:
        if rec['exit_reason'] != 'STOP':
            continue
        ctx = None
        out['candidate'].append({
            'instrument': rec['instrument'], 'session_date': rec['session_date'],
            'entry_time': rec['entry_time'], 'exit_time': rec['exit_time'],
            'entry': rec['entry'], 'exit_price': rec['exit_price'],
            'setup_family': rec.get('setup_family'),
            'stop_source': rec.get('stop_source'),
            'realized_r': rec['realized_r'], 'realized_pts': rec['realized_pts'],
            'stop_overshoot_pts': rec['stop_overshoot_pts'],
            'forward': stopped_forward(rec, _candles_for(univ_prod, rec)),
        })
    for key in ('baseline', 'candidate'):
        rows = out[key]
        cont = sum(1 for r in rows if r.get('forward', {}).get('remainder_pts') is not None
                   and r['forward']['remainder_pts'] < 0)
        rev = sum(1 for r in rows if r.get('forward', {}).get('remainder_pts') is not None
                  and r['forward']['remainder_pts'] > 0)
        out[key + '_summary'] = {
            'stop_outs': len(rows),
            'continued_against_after_stop': cont,
            'reversed_after_stop': rev,
            'note': ('a stop-out that keeps running is counted as a continuation; '
                     'index points only'),
        }
    return out


def _candles_for(univ_prod, rec):
    ctx = univ_prod[rec['instrument']]['sessions'].get(rec['session_date'])
    return ctx['scan'] if ctx else []
