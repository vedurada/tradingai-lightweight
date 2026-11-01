"""Hypothetical trade records for every (signal, variant).

One row per (baseline signal x variant B0/S1-S5), including NO TRADE rows with the
rejection reason. Rows are historical research outputs: not alerts, not
recommendations, not orders. The target is the unchanged production 2% target in
every variant; only the stop price differs.
"""
from __future__ import annotations

import json

try:
    from . import cushion, execution_ext, structures
except ImportError:  # pragma: no cover
    import cushion
    import execution_ext
    import structures

VARIANTS = ('B0', 'S1', 'S2', 'S3', 'S4', 'S5')
TARGET_PCT = 0.02
TARGET_RULE = 'production 2% target of entry, unchanged in every variant'

DATA_LIMITATIONS = (
    'index/spot only; 5-minute candles; no volume; no historical option prices, '
    'bid/ask or contract details, so no option or rupee P&L is claimed'
)
EXECUTION_LIMITATIONS = (
    'modelled fills only (candle open or stop/target touch), never guaranteed; '
    'intrabar stop/target order unknowable and resolved conservatively (stop first); '
    'gap-through losses are modelled, not booked as exactly -1R'
)
POSITION_SIZING = None
POSITION_SIZING_REASON = (
    'not computed: the deployment has no production-verified capital base / risk '
    'budget, so a position size would be invented'
)


def target_price(direction: str, entry: float) -> float:
    return entry * (1 - TARGET_PCT) if direction == 'BEAR' else entry * (1 + TARGET_PCT)


def build(signal: dict, variant: str, models=('opens', 'intrabar')) -> dict:
    ctx = signal['ctx']
    candles = ctx['scan']
    entry_idx = signal['entry_idx']
    entry = float(signal['entry'])
    direction = signal['direction']
    trig = signal['trigger_idx']
    med = structures.pit_median_range(candles, trig)

    d = structures.derive(signal, entry, variant)
    row = {
        'variant': variant,
        'signal_key': f"{signal['instrument']}|{signal['session_date']}|{signal['level']}|{signal['entry_time']}",
        'instrument': signal['instrument'],
        'session_date': signal['session_date'],
        'period': signal['period'],
        'signal_time': signal['signal_time'],
        'setup': signal['level'],
        'level_price': signal['level_price'],
        'break_side': signal.get('break_side'),
        'entry_time': str(candles[entry_idx]['timestamp'])[:16].replace('T', ' '),
        'entry_available_ts': str(candles[entry_idx]['timestamp']),
        'entry': round(entry, 2),
        'target_price': round(target_price(direction, entry), 4),
        'target_rule': TARGET_RULE,
        'stop_price': d['stop_price'],
        'stop_rule': d['stop_rule'],
        'stop_evidence': json.dumps(d['evidence'], sort_keys=True),
        'rejection_reason': d['rejection_reason'],
        'inputs_max_idx': d['inputs_max_idx'],
        'trigger_idx': trig,
        'no_trade': d['stop_price'] is None,
        'direction': direction,
        'direction_label': ('BEARISH' if direction == 'BEAR' else 'BULLISH'),
        'data_limitations': DATA_LIMITATIONS,
        'execution_limitations': EXECUTION_LIMITATIONS,
        'position_sizing': POSITION_SIZING,
        'position_sizing_reason': POSITION_SIZING_REASON,
        'median_range_pts': None if med is None else round(med, 4),
    }
    if direction == 'BEAR':
        row['direction_label'] = 'BEARISH' if not row['no_trade'] else 'NO TRADE'
    else:
        row['direction_label'] = 'BULLISH' if not row['no_trade'] else 'NO TRADE'

    row['no_lookahead_ok'] = bool(d['inputs_max_idx'] is not None
                                  and entry_idx is not None
                                  and d['inputs_max_idx'] < entry_idx)
    if row['no_trade']:
        # document the missed opportunity: what B0 did on the same signal
        return row

    stop_px = float(d['stop_price'])
    tgt_px = row['target_price']
    for model in models:
        sim = execution_ext.simulate(direction, entry, candles, entry_idx,
                                     stop_px, tgt_px, model)
        if sim is None:
            row[f'{model}_missing_eod'] = True
            continue
        prefix = '' if model == 'opens' else f'{model}_'
        exc = execution_ext.excursion(direction, entry, candles, entry_idx, sim['exit_ts'])
        risk = sim['risk_pts']
        row.update({
            f'{prefix}exit_reason': sim['exit_reason'],
            f'{prefix}exit_price': sim['exit_price'],
            f'{prefix}exit_time': str(sim['exit_ts'])[:16].replace('T', ' '),
            f'{prefix}booked_r': sim['booked_r'],
            f'{prefix}realized_r': sim['realized_r'],
            f'{prefix}realized_pts': sim['realized_pts'],
            f'{prefix}stop_overshoot_pts': sim['stop_overshoot_pts'],
            f'{prefix}stop_overshoot_r': sim['stop_overshoot_r'],
            f'{prefix}target_truncation_pts': sim['target_truncation_pts'],
            f'{prefix}target_truncation_r': sim['target_truncation_r'],
            f'{prefix}intrabar_ambiguous_bars': sim['intrabar_ambiguous_bars'],
            f'{prefix}mae_hl_pts': exc['mae_hl_pts'],
            f'{prefix}mae_hl_r': round(exc['mae_hl_pts'] / risk, 4),
            f'{prefix}mfe_hl_pts': exc['mfe_hl_pts'],
            f'{prefix}mfe_hl_r': round(exc['mfe_hl_pts'] / risk, 4),
            f'{prefix}bars_held': exc['bars_held'],
            f'{prefix}risk_pts': round(risk, 4),
        })
    sim = execution_ext.simulate(direction, entry, candles, entry_idx, stop_px,
                                 tgt_px, 'opens')
    if sim is not None:
        c = cushion.measure(direction, entry, stop_px, tgt_px, candles, entry_idx,
                            sim['exit_ts'], ctx['levels'] or {}, med)
        row.update(c)
        row['stop_breached_before_target'] = sim['exit_reason'] == 'STOP'
        row['target_reached_before_stop'] = sim['exit_reason'] == 'TARGET'
    # canonical fields for the shared aggregation helpers
    row['realized_r'] = row.get('realized_r')
    row['realized_pts'] = row.get('realized_pts')
    row['mae_hl_r'] = row.get('mae_hl_r')
    row['risk_pts'] = row.get('risk_pts')
    return row
