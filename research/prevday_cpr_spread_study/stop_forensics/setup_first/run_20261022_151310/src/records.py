"""Trade records for the setup-first study.

The accounting is NOT re-implemented here: the parent's
``stop_forensics/src/accounting.account`` is used unchanged, so the exit model,
the excursion model, the forward-path model, the intrabar bounds and the decay
label are identical to the frozen baseline. The only difference is that the
entry price and the stop/target prices come from the setup-first plan; they are
handed to the parent module as the equivalent stop/target percentages.
"""
from __future__ import annotations

from research.prevday_cpr_spread_study.stop_forensics.src import accounting


def build_trade(setup, ctx, entry, entry_idx, stop_price, target_price,
                arm='SF', stop_source='', stop_variant='S0', confirm_rule='C1_CLOSE_BACK'):
    """Simulate one hypothetical setup-first trade (parent accounting)."""
    signal = {
        'instrument': setup['instrument'],
        'session_date': setup['session_date'],
        'direction': 'BEAR',
        'level': setup.get('level_name') or setup['setup_family'],
        'level_price': setup['level_price'],
        'trigger_idx': setup.get('arrival_idx'),
        'entry_idx': entry_idx,
        'entry': entry,
        'entry_time': str(ctx['scan'][entry_idx]['timestamp'])[:16].replace('T', ' '),
        'signal_time': setup.get('identification_ts'),
        'ctx': ctx,
        'period': setup.get('period'),
    }
    stop_pct = (stop_price - entry) / entry if entry else 0.0
    target_pct = (entry - target_price) / entry if entry else 0.0
    rec = accounting.account(signal, arm, entry=entry, entry_idx=entry_idx,
                             entry_source='setup_first_next_bar_open',
                             stop_pct=stop_pct, target_pct=target_pct)
    if rec is None:
        return None
    rec['setup_id'] = setup['setup_id']
    rec['setup_family'] = setup['setup_family']
    rec['setup_level'] = setup.get('level_name')
    rec['arrival_time'] = setup.get('arrival_ts')
    rec['confirm_time'] = setup.get('confirm_ts')
    rec['confirmation_rule'] = confirm_rule
    rec['stop_variant'] = stop_variant
    rec['stop_source'] = stop_source
    rec['stop_distance_pct'] = round(abs(stop_price - entry) / entry, 6)
    rec['setup_minutes_to_arrival'] = setup.get('minutes_to_arrival')
    rec['setup_minutes_to_confirmation'] = setup.get('minutes_to_confirmation')
    return rec


def setup_rows(setups):
    """Machine-readable per-setup state records (one row per setup)."""
    rows = []
    for s in setups:
        row = {k: v for k, v in s.items()
               if k not in ('transitions', 'ctx', 'bundle', 'baseline_trigger')}
        row['state_transitions'] = s.get('transitions', [])
        rows.append(row)
    return rows
