"""Reproduction of the Phase 3 headline numbers and the comparison table.

Phase 3 is a historical research experiment with its own definitions. Every
number used for the comparison is re-read from the Phase 3 artifacts here and
checked against the published figures before it is used.

The comparison is mechanism based: for every Phase 3 refusal mechanism the
table states how many of the 600 identified Phase 3 setups it refused, and how
many live losses exhibit the same condition - i.e. trades the Phase 3 rule
set would have refused but the live engine took.
"""
import ast
import collections
import csv
import json
import os

from . import config


def _load_json(name):
    path = os.path.join(config.P3_DIR, 'outputs', name)
    if not os.path.exists(path):
        return None
    with open(path) as fh:
        return json.load(fh)


def reproduce():
    """Re-read the Phase 3 artifacts and rebuild the published headline figures."""
    funnel = _load_json('experiment_A_funnel.json')
    exp_b = _load_json('experiment_B.json')
    exp_c = _load_json('experiment_C.json')
    manifest = _load_json('run_manifest.json')
    forensics = _load_json('stop_out_forensics.json')
    robustness = _load_json('robustness.json')

    totals = funnel['totals']
    reproduced = {
        'identified': totals['identified'],
        'zone_reached': totals['zone_reached'],
        'confirmed': totals['confirmed'],
        'expired': totals['expired'],
        'invalidated': totals['invalidated'],
        'trade_eligible': totals['trade_eligible'],
        'missed': totals['missed'],
        'no_trade': totals['no_trade'],
        'no_trade_never_confirmed': totals['no_trade_never_confirmed'],
    }
    published = {
        'identified': 600, 'zone_reached': 374, 'confirmed': 305,
        'expired': 203, 'invalidated': 92, 'trade_eligible': 134,
        'missed': 31, 'no_trade': 140,
    }
    baseline = robustness.get('baseline') or {}
    candidate = robustness.get('candidate') or {}
    checks = {k: (reproduced[k] == published[k]) for k in published}
    checks['funnel_identity_identified'] = (
        totals['identified'] == totals['confirmed'] + totals['expired'] + totals['invalidated'])
    checks['funnel_identity_confirmed'] = (
        totals['confirmed'] == totals['trade_eligible'] + totals['missed'] + totals['no_trade'])
    checks['baseline_trades_129'] = baseline.get('n') == 129
    checks['candidate_trades_98'] = candidate.get('n') == 98
    checks['verdict_is_inconclusive'] = manifest.get('verdict') == 'INCONCLUSIVE'
    checks['experiment_d_not_run'] = manifest.get('experiment_d_run') is False

    out = {
        'reproduced': reproduced,
        'published': published,
        'checks': checks,
        'all_checks_pass': all(checks.values()),
        'verdict': manifest.get('verdict'),
        'candidate_arm': manifest.get('candidate_arm'),
        'candidate_trades': manifest.get('candidate_trades'),
        'candidate_trades_artifact': candidate.get('n'),
        'baseline_trades': baseline.get('n'),
        'selected_rule': manifest.get('selected_entry_policy'),
        'selected_stop': manifest.get('selected_stop'),
        'experiment_d_run': manifest.get('experiment_d_run'),
        'baseline_by_period': robustness.get('baseline_by_period'),
        'candidate_by_period': robustness.get('candidate_by_period'),
        'funnel_by_family': funnel.get('by_family'),
        'stop_out_forensics': {
            'baseline': forensics.get('baseline_summary'),
            'candidate': forensics.get('candidate_summary'),
        },
        'experiment_b_selection': (exp_b.get('selection') or {}),
        'experiment_c_selection': (exp_c.get('selection') or {}),
    }
    out['reasons'] = _decision_reasons()
    return out


def _decision_reasons():
    """Decision reasons of the Phase 3 C1 rule, one row per identified setup."""
    path = os.path.join(config.P3_DIR, 'outputs', 'setup_state_rows.csv')
    if not os.path.exists(path):
        return {}
    counter = collections.Counter()
    states = collections.Counter()
    decisions = collections.Counter()
    setups = set()
    with open(path) as fh:
        for row in csv.DictReader(fh):
            if row.get('arm') != 'SF_C1_S0' or row.get('stop_variant') != 'S0':
                continue
            if row['setup_id'] in setups:
                continue
            setups.add(row['setup_id'])
            states[row.get('state')] += 1
            decisions[row.get('decision')] += 1
            raw = (row.get('decision_reasons') or '').strip()
            try:
                reasons = ast.literal_eval(raw) if raw else []
            except (ValueError, SyntaxError):
                reasons = [raw]
            if isinstance(reasons, str):
                reasons = [reasons]
            for reason in reasons:
                if reason:
                    counter[str(reason)] += 1
    return {'setups': len(setups), 'states': dict(states), 'decisions': dict(decisions),
            'reasons': dict(counter.most_common())}


def _match(rows, dim, label):
    """Number of rows whose primary or secondary category carries `label`."""
    n = 0
    for r in rows:
        primary = r.get(f'{dim}_primary')
        secondary = r.get(f'{dim}_secondary') or []
        if primary == label or label in secondary:
            n += 1
    return n


def comparison_table(phase3, loss_rows, stop_loss_rows, win_rows=None):
    """Build the Phase 3 <-> live-engine mechanism comparison.

    `loss_rows` are the classified losses of the engine signal book.
    `stop_loss_rows` are the subset of those losses that ended at the stop; the
    post-stop rows are measured against that denominator.
    `win_rows` are the classified winners of the same book; they are the
    control group and show whether a pattern discriminates losses.

    Counting convention: the Phase 3 decision reasons are not mutually
    exclusive (one setup can carry several refusal reasons), so the live side
    is counted the same way - a loss row counts for a pattern when the label is
    its primary or one of its secondary categories.  The primary-only counts
    are in LOSS_PATTERN_CLASSIFICATION.csv.

    Row verdicts are directional statements about the presence of a construct
    in the two populations; the aggregate verdict is computed separately by
    the pre-declared rule in config.VERDICT_RULES.
    """
    p3 = phase3['reproduced']
    p3_reasons = phase3.get('reasons', {}).get('reasons', {})
    p3_setups = phase3.get('reasons', {}).get('setups') or p3['identified']
    baseline_stop = phase3['stop_out_forensics'].get('baseline') or {}
    candidate_stop = phase3['stop_out_forensics'].get('candidate') or {}
    n_losses = len(loss_rows)
    n_stop_losses = len(stop_loss_rows)
    win_rows = win_rows or []
    n_wins = len(win_rows)
    n_win_stop = len([r for r in win_rows if r.get('exit_kind') == 'STOP'])

    rows = []

    def add(row_type, mechanism, phase3_count, phase3_denominator, phase3_note,
            live_label, live_count, live_denominator, evidence, limitation,
            live_dimension=None, live_basis='primary_or_secondary',
            win_count=None, win_denominator=None):
        if live_count is None:
            verdict = 'NOT_COMPARABLE'
        elif live_count == 0 and (phase3_count is None or phase3_count == 0):
            verdict = 'NOT_COMPARABLE'
        elif phase3_count is None or phase3_count == 0:
            verdict = 'LIVE_ONLY'
        elif live_count == 0:
            verdict = 'PHASE3_ONLY'
        else:
            verdict = 'SUPPORTED'
        live_pct = round(100.0 * live_count / live_denominator, 2) \
            if live_denominator and live_count is not None else None
        p3_pct = round(100.0 * phase3_count / phase3_denominator, 2) \
            if phase3_denominator and phase3_count is not None else None
        if win_denominator is None:
            win_denominator = n_win_stop if live_denominator == n_stop_losses \
                else n_wins
        if win_count is None:
            win_count = _match(win_rows, live_dimension or '', live_label) \
                if (live_dimension and live_label) else None
        win_pct = round(100.0 * win_count / win_denominator, 2) \
            if win_denominator and win_count is not None else None
        gap = round(live_pct - win_pct, 2) \
            if (live_pct is not None and win_pct is not None) else None
        discriminates = 'YES' if (gap is not None and gap >= 10.0) else (
            'NO' if gap is not None else 'n/a')
        rows.append({
            'row_type': row_type,
            'phase3_mechanism': mechanism,
            'phase3_refusal_count': phase3_count,
            'phase3_denominator': phase3_denominator,
            'phase3_pct': p3_pct,
            'phase3_note': phase3_note,
            'live_pattern': live_label,
            'live_dimension': live_dimension,
            'live_count_basis': live_basis,
            'live_loss_count': live_count,
            'live_denominator': live_denominator,
            'live_pct': live_pct,
            'live_win_count': win_count,
            'live_win_denominator': win_denominator,
            'live_win_pct': win_pct,
            'loss_minus_win_pct': gap,
            'discriminates_losses': discriminates,
            'verdict': verdict,
            'evidence': evidence,
            'limitation': limitation,
        })

    def reason(*names):
        return sum(p3_reasons.get(n, 0) for n in names)

    # --- Phase 3 decision mechanisms ----------------------------------------
    add('MECHANISM',
        'Setup refused: the price never arrived in the zone',
        reason('no_arrival_in_window'), p3_setups,
        'Phase 3 C1/S0 refusal reason no_arrival_in_window',
        'the live engine enters on the touch of the level, so a zone can never '
        'be missed',
        None, n_losses,
        'not comparable: the live engine has no planned zone',
        'not a comparable construct', 'D')
    add('MECHANISM',
        'Setup refused: no breakout attempt inside the window',
        reason('no_breakout_attempt_in_window'), p3_setups,
        'Phase 3 C1/S0 refusal reason no_breakout_attempt_in_window',
        'the live engine triggers on the touch, so a breakout attempt has no '
        'counterpart',
        None, n_losses,
        'not comparable: the live engine has no breakout-attempt state',
        'not a comparable construct', 'D')
    add('MECHANISM',
        'Setup refused: no confirmation close inside the window',
        reason('no_confirmation_in_window'), p3_setups,
        'Phase 3 C1/S0 refusal reason no_confirmation_in_window',
        'ENTRY_BEFORE_CONFIRMATION',
        _match(loss_rows, 'A', 'ENTRY_BEFORE_CONFIRMATION'), n_losses,
        'direct: the live engine enters without requiring a confirmation close',
        'the Phase 3 rule refused only a few setups for this reason because '
        'its other refusal reasons dominated; the construct, not the '
        'frequency, is comparable', 'A')
    add('MECHANISM',
        'Setup invalidated: the price closed back through the zone',
        reason('closed_above_zone', 'closed_above_zone_before_arrival'), p3_setups,
        'Phase 3 C1/S0 invalidation reasons closed_above_zone and '
        'closed_above_zone_before_arrival',
        'FAILED_BREAKOUT_OR_BREAKDOWN',
        _match(loss_rows, 'B', 'FAILED_BREAKOUT_OR_BREAKDOWN'), n_losses,
        'direct: the level was crossed favourably after the entry and the price '
        'closed back beyond it',
        'Phase 3 invalidates on the setup zone, the live test uses the entry '
        'level', 'B')
    add('MECHANISM',
        'Setup refused: the entry would have been too extended to chase '
        '(more than 0.25 % beyond the level)',
        reason('too_extended_to_chase'), p3_setups,
        'Phase 3 C1/S0 refusal reason too_extended_to_chase',
        'ENTRY_AFTER_EXCESSIVE_EXTENSION',
        _match(loss_rows, 'A', 'ENTRY_AFTER_EXCESSIVE_EXTENSION'), n_losses,
        'direct: extension from the reconstructed entry-time level',
        'for the CPR boundary levels the level is only a partial CPR', 'A')
    add('MECHANISM',
        'Setup refused: one trade per session',
        reason('one_trade_per_session'), p3_setups,
        'Phase 3 C1/S0 refusal reason one_trade_per_session',
        'the live engine applies its own position limit; the loss '
        'concentration per session is in the control comparison',
        None, n_losses,
        'not comparable: the position limit is a different construct',
        'not a comparable construct', 'D')
    add('MECHANISM',
        'Setup refused: no usable entry window or exit after the confirmation',
        reason('entry_after_window', 'missing_eod_exit',
               'no_next_bar_after_confirmation'), p3_setups,
        'Phase 3 C1/S0 refusal reasons entry_after_window, missing_eod_exit, '
        'no_next_bar_after_confirmation',
        'the live engine always has a session exit and trades the touch',
        None, n_losses,
        'not comparable: the live engine has no confirmation-window state',
        'not a comparable construct', 'D')
    add('MECHANISM',
        'Setup family: rejection at a pre-existing (prior day / pivot) level',
        (phase3.get('funnel_by_family', {}) or {}).get(
            'F1_PREV_DAY_LEVEL_REJECTION', {}).get('identified'),
        p3['identified'],
        'Phase 3 family F1_PREV_DAY_LEVEL_REJECTION identified setups',
        'REJECTION_AT_PRE_EXISTING_LEVEL',
        _match(loss_rows, 'B', 'REJECTION_AT_PRE_EXISTING_LEVEL'), n_losses,
        'direct: the recorded level of the live trade is a prior-day or pivot '
        'level',
        'the Phase 3 number is a family size, not a refusal count', 'B')

    # --- Phase 3 funnel -----------------------------------------------------
    add('FUNNEL',
        'Funnel: setups that reached the planned zone',
        p3['zone_reached'], p3['identified'],
        'published Phase 3 funnel',
        'the live level was reached (a confirmation close was present or not)',
        _match(loss_rows, 'D', 'ENTRY_FOLLOWED_VALID_ZONE_ARRIVAL_AND_CONFIRMATION')
        + _match(loss_rows, 'D', 'ZONE_REACHED_BUT_CONFIRMATION_ABSENT'),
        n_losses,
        'direct: the same entry-time structure was reconstructed for the live '
        'trades',
        'tautological for the live engine: it enters on the touch of the level, '
        'so the level is always reached', 'D',
        win_count=len(win_rows), win_denominator=n_wins)
    add('FUNNEL',
        'Funnel: setups confirmed inside the window',
        p3['confirmed'], p3['identified'],
        'published Phase 3 funnel',
        'ENTRY_FOLLOWED_VALID_ZONE_ARRIVAL_AND_CONFIRMATION',
        _match(loss_rows, 'D', 'ENTRY_FOLLOWED_VALID_ZONE_ARRIVAL_AND_CONFIRMATION'),
        n_losses,
        'direct: a rejection close on a closed candle before the entry',
        'assessable only where the intraday level could be reconstructed', 'D')
    add('FUNNEL',
        'Funnel: trade-eligible setups',
        p3['trade_eligible'], p3['identified'],
        'published Phase 3 funnel',
        'ENTRY_FOLLOWED_VALID_ZONE_ARRIVAL_AND_CONFIRMATION',
        _match(loss_rows, 'D', 'ENTRY_FOLLOWED_VALID_ZONE_ARRIVAL_AND_CONFIRMATION'),
        n_losses,
        'direct: arrival plus confirmation plus an admissible risk distance',
        'the live engine does not test the risk distance the same way', 'D')

    # --- post stop behaviour ------------------------------------------------
    add('STOP_OUT',
        'Stop-out: the price continued against the position after the stop',
        candidate_stop.get('continued_against_after_stop'),
        candidate_stop.get('stop_outs'),
        'Phase 3 candidate (SF_C2_S0) stop-outs, fwd60 worst excursion < 0',
        'STOP_HIT_THEN_PRICE_CONTINUED_AGAINST',
        _match(stop_loss_rows, 'C', 'STOP_HIT_THEN_PRICE_CONTINUED_AGAINST'),
        n_stop_losses,
        'direct: identical forward-path definition (60 minutes, worst '
        'excursion in R)',
        'the Phase 3 flags are not mutually exclusive, the live categories are',
        'C')
    add('STOP_OUT',
        'Stop-out: the price moved back in the trade direction after the stop',
        candidate_stop.get('reversed_after_stop'),
        candidate_stop.get('stop_outs'),
        'Phase 3 candidate (SF_C2_S0) stop-outs, fwd60 best excursion > 0',
        'STOP_HIT_THEN_PRICE_REVERSED_TOWARD_TARGET',
        _match(stop_loss_rows, 'C', 'STOP_HIT_THEN_PRICE_REVERSED_TOWARD_TARGET'),
        n_stop_losses,
        'direct: identical forward-path definition',
        'the Phase 3 flags are not mutually exclusive, the live categories are',
        'C')
    contained = n_stop_losses \
        - _match(stop_loss_rows, 'C', 'STOP_HIT_THEN_PRICE_CONTINUED_AGAINST') \
        - _match(stop_loss_rows, 'C', 'STOP_HIT_THEN_PRICE_REVERSED_TOWARD_TARGET')
    add('STOP_OUT',
        'Stop-out: the adverse move stayed inside the stop zone (ordinary '
        'adverse movement)',
        (baseline_stop.get('stop_outs', 0)
         - baseline_stop.get('continued_against_after_stop', 0)
         - baseline_stop.get('reversed_after_stop', 0)),
        baseline_stop.get('stop_outs'),
        'Phase 3 baseline (no-filter) stop-outs that neither continued nor '
        'reversed',
        'stop exits where the 60-minute forward path neither continued '
        'against the position nor reversed toward the target',
        contained, n_stop_losses,
        'like-for-like: the Phase 3 baseline is the no-filter rule, the closest '
        'analogue of the live engine',
        'one live stop exit was not assessable and is counted as contained',
        'C')

    # --- live only patterns -------------------------------------------------
    add('LIVE_PATTERN',
        'The market had already completed most of the move before the entry',
        None, None,
        'no Phase 3 counterpart',
        'ENTRY_AFTER_MARKET_COMPLETED_MOST_OF_MOVE',
        _match(loss_rows, 'A', 'ENTRY_AFTER_MARKET_COMPLETED_MOST_OF_MOVE'),
        n_losses,
        'direct: the 12-bar pre-entry move in the trade direction',
        'Phase 3 has no counterpart construct', 'A')
    add('LIVE_PATTERN',
        'Directional continuation against the position after the entry',
        None, None,
        'no Phase 3 counterpart',
        'DIRECTIONAL_CONTINUATION_AGAINST_POSITION',
        _match(loss_rows, 'B', 'DIRECTIONAL_CONTINUATION_AGAINST_POSITION'),
        n_losses,
        'direct: MAE at or above 1R with the adverse extreme after the '
        'favourable one',
        'Phase 3 has no counterpart construct', 'B')
    add('LIVE_PATTERN',
        'Range / chop around the level',
        None, None,
        'no Phase 3 counterpart',
        'RANGE_CHOP_OR_REPEATED_LEVEL_CROSSINGS',
        _match(loss_rows, 'B', 'RANGE_CHOP_OR_REPEATED_LEVEL_CROSSINGS'),
        n_losses,
        'direct: a 12-bar pre-entry range below 0.25 % or repeated level '
        'crossings',
        'Phase 3 has no explicit chop construct; its expiries are '
        'no_arrival (119) and no_breakout_attempt (81), which are different '
        'conditions', 'B')
    add('LIVE_PATTERN',
        'The stop lay beyond the nearest available structural invalidation '
        'level',
        None, None,
        'no Phase 3 counterpart',
        'STOP_WAS_BEYOND_THE_AVAILABLE_STRUCTURAL_INVALIDATION_POINT',
        _match(stop_loss_rows, 'C',
               'STOP_WAS_BEYOND_THE_AVAILABLE_STRUCTURAL_INVALIDATION_POINT'),
        n_stop_losses,
        'direct: the recorded stop distance against the nearest known level',
        'Phase 3 has no counterpart construct', 'C')
    add('LIVE_PATTERN',
        'Reward/risk below the 1.5 minimum',
        reason('reward_risk_below_minimum'), p3_setups,
        'Phase 3 C1/S0 refusal reason reward_risk_below_minimum',
        'VALID_ENTRY_PLAN_EXISTED_BUT_RISK_REWARD_FAILED',
        _match(loss_rows, 'D', 'VALID_ENTRY_PLAN_EXISTED_BUT_RISK_REWARD_FAILED'),
        n_losses,
        'structural: the live engine always uses a 0.5 % stop against a 2 % '
        'target, so the ratio is fixed at 4.0 and the test cannot fail',
        'the live test cannot fail by construction', 'D')
    return rows
