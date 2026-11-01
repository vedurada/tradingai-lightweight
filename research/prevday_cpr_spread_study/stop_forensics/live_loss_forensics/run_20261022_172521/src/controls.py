"""Winner-versus-loser control comparison inside the same live-engine sample.

The control group is taken from the same population, the same instruments and
the same period as the loss group, so that the comparison isolates the
features that separate the two groups rather than the features that are
common to the market.
"""
import statistics

from . import config


def _stats(values):
    vals = [v for v in values if v is not None]
    if not vals:
        return {'n': 0, 'mean': None, 'median': None, 'min': None, 'max': None}
    return {'n': len(vals), 'mean': round(statistics.fmean(vals), 4),
            'median': round(statistics.median(vals), 4),
            'min': round(min(vals), 4), 'max': round(max(vals), 4)}


def build(rows):
    """`rows` are classified trades of one population."""
    losses = [r for r in rows if r['outcome_class'] == 'LOSS']
    wins = [r for r in rows if r['outcome_class'] == 'WIN']

    metrics = [
        ('entry_extension_pct', 'Entry extension from the entry-time level (%)'),
        ('entry_to_stop_pct', 'Entry-to-stop distance (% of entry)'),
        ('entry_to_target_pct', 'Entry-to-target distance (% of entry)'),
        ('risk_pts', 'Entry-to-stop distance (index points)'),
        ('mae_hl_r', 'MAE (R, high/low)'),
        ('mfe_hl_r', 'MFE (R, high/low)'),
        ('mae_open_r', 'MAE (R, opens only)'),
        ('mfe_open_r', 'MFE (R, opens only)'),
        ('rr_vs_frozen_target', 'Reward/risk against the frozen 2 % target'),
        ('pre_entry_move_pct', 'Pre-entry 12-bar move in the trade direction (%)'),
        ('pre_entry_range_pct', 'Pre-entry 12-bar range (%)'),
        ('minutes_to_entry', 'Entry time (minutes after 09:15)'),
        ('distance_to_nearest_level_pct', 'Distance to the nearest opposing known level (%)'),
        ('bars_held', 'Bars held'),
        ('stop_overshoot_r', 'Stop overshoot at the exit (R, stop exits only)'),
        ('level_crossings_after_entry', 'Level crossings after the entry'),
    ]
    comparison = []
    for key, label in metrics:
        # the stop overshoot only exists for trades that actually ended at the
        # stop; for every other exit the number is meaningless
        if key == 'stop_overshoot_r':
            l_vals = [r.get(key) for r in losses if r.get('exit_kind') == 'STOP']
            w_vals = [r.get(key) for r in wins if r.get('exit_kind') == 'STOP']
        else:
            l_vals = [r.get(key) for r in losses]
            w_vals = [r.get(key) for r in wins]
        l_stats = _stats(l_vals)
        w_stats = _stats(w_vals)
        diff = None
        if l_stats['mean'] is not None and w_stats['mean'] is not None:
            diff = round(l_stats['mean'] - w_stats['mean'], 4)
        comparison.append({
            'metric': key, 'label': label,
            'losers_n': l_stats['n'], 'losers_mean': l_stats['mean'],
            'losers_median': l_stats['median'],
            'winners_n': w_stats['n'], 'winners_mean': w_stats['mean'],
            'winners_median': w_stats['median'],
            'difference_mean_loser_minus_winner': diff,
        })

    categorical = []
    for key, label in (('A_primary', 'A - entry timing'),
                       ('B_primary', 'B - market structure'),
                       ('C_primary', 'C - stop behaviour'),
                       ('D_primary', 'D - setup-first discipline'),
                       ('level', 'Recorded setup level'),
                       ('exit_kind', 'Exit type'),
                       ('direction', 'Direction'),
                       ('instrument', 'Instrument')):
        l_counts = {}
        w_counts = {}
        for r in losses:
            l_counts[str(r.get(key))] = l_counts.get(str(r.get(key)), 0) + 1
        for r in wins:
            w_counts[str(r.get(key))] = w_counts.get(str(r.get(key)), 0) + 1
        for label_value in sorted(set(l_counts) | set(w_counts)):
            l_n = l_counts.get(label_value, 0)
            w_n = w_counts.get(label_value, 0)
            categorical.append({
                'dimension': label, 'value': label_value,
                'losses_n': l_n, 'losses_denominator': len(losses),
                'losses_pct': round(100.0 * l_n / len(losses), 2) if losses else None,
                'winners_n': w_n, 'winners_denominator': len(wins),
                'winners_pct': round(100.0 * w_n / len(wins), 2) if wins else None,
            })

    # session clustering: how concentrated are the losses in single sessions?
    by_session = {}
    for r in losses:
        key = (r['session_date'], r['instrument'])
        by_session[key] = by_session.get(key, 0) + 1
    clustering = {
        'loss_sessions': len(by_session),
        'max_losses_in_one_session': max(by_session.values()) if by_session else 0,
        'sessions_with_more_than_one_loss': sum(1 for v in by_session.values() if v > 1),
    }
    return {'comparison': comparison, 'categorical': categorical,
            'clustering': clustering,
            'losers': len(losses), 'winners': len(wins)}


def per_trade_rows(rows):
    """One row per trade for the winner/control deliverable."""
    out = []
    for r in rows:
        out.append({
            'trade_id': r['source_row_id'],
            'population': r['population'],
            'instrument': r['instrument'],
            'session_date': r['session_date'],
            'direction': r['direction'],
            'level': r['level'],
            'entry_time': r['entry_time'],
            'entry_price': r['entry_price'],
            'stop_price': r['stop_price'],
            'target_price': r['target_price'],
            'exit_time': r['exit_time'],
            'exit_price': r['exit_price'],
            'exit_reason': r['exit_reason'],
            'recorded_result': r['recorded_result'],
            'recomputed_r': r.get('recomputed_r'),
            'outcome_class': r['outcome_class'],
            'group': 'LOSS' if r['outcome_class'] == 'LOSS' else
                     ('WIN' if r['outcome_class'] == 'WIN' else
                      ('FLAT' if r['outcome_class'] == 'FLAT' else 'OTHER')),
            'entry_extension_pct': r.get('entry_extension_pct'),
            'level_price_source': r.get('level_price_source'),
            'entry_to_stop_pct': r.get('entry_to_stop_pct'),
            'entry_to_target_pct': r.get('entry_to_target_pct'),
            'mae_hl_r': r.get('mae_hl_r'),
            'mfe_hl_r': r.get('mfe_hl_r'),
            'mae_open_r': r.get('mae_open_r'),
            'mfe_open_r': r.get('mfe_open_r'),
            'rr_vs_frozen_target': r.get('rr_vs_frozen_target'),
            'pre_entry_move_pct': r.get('pre_entry_move_pct'),
            'pre_entry_range_pct': r.get('pre_entry_range_pct'),
            'minutes_to_entry': r.get('minutes_to_entry'),
            'post_exit_category': r.get('post_exit_category'),
            'A_primary': r.get('A_primary'), 'B_primary': r.get('B_primary'),
            'C_primary': r.get('C_primary'), 'D_primary': r.get('D_primary'),
            'flags': ';'.join(r.get('flags') or []),
        })
    return out
