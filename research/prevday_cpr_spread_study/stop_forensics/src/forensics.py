"""Forensic classification of stopped trades.

Every flag is computed point-in-time: only information available at the moment of
the trade (or explicitly labelled as "after the fact") is used.
"""
from __future__ import annotations

from . import data

EXTENSION_THRESHOLD = 0.0025       # 0.25 % beyond the trigger level
GAP_THRESHOLD = 0.25               # 0.25 % session gap
RANGE_VS_STOP = True               # session median bar range wider than the stop distance
FOLLOWTHROUGH_BARS = 3


def _dir_sign(direction: str) -> int:
    return 1 if direction == 'BULL' else -1


def opposite_triggers(ctx: dict, engine, direction: str) -> list:
    """All candles of the session where the *opposite* direction qualified.

    Uses the production trigger functions unchanged. Under `SHORT_ONLY=True` the
    production engine never *acts* on a BULL trigger, but the information is still
    observable at the time; the classification reports availability, not a
    deployable signal.
    """
    out = []
    for i, c in enumerate(ctx['scan']):
        if direction == 'BEAR':
            other = engine.bull_trigger(c, ctx['levels'])
        else:
            other = engine.bear_trigger(c, ctx['levels'])
        if other:
            out.append({'idx': i, 'time': str(c['timestamp']), 'level': other})
    return out


def same_direction_crosses(ctx: dict, engine, direction: str, from_idx: int = 0) -> list:
    """Fresh close-crosses in `direction` (production breakout semantics)."""
    out = []
    prev = None
    for i, c in enumerate(ctx['scan']):
        close = float(c['close'])
        if prev is not None:
            r = engine.breakout_trigger(c, prev, ctx['levels'])
            if r and r[0] == direction and i > from_idx:
                out.append({'idx': i, 'time': str(c['timestamp']), 'level': r[1]})
        prev = close
    return out


def cpr_crossings(ctx: dict, entry_idx: int) -> int:
    """Number of close-crossings of the CPR boundaries after the entry."""
    if not ctx['levels']:
        return 0
    bc, tc = float(ctx['levels']['bc']), float(ctx['levels']['tc'])
    crossings = 0
    zone = None
    for c in ctx['scan'][entry_idx:]:
        close = float(c['close'])
        new_zone = 'below' if close < bc else ('above' if close > tc else 'inside')
        if zone is not None and new_zone != zone and new_zone in ('below', 'above'):
            crossings += 1
        zone = new_zone
    return crossings


def followthrough(ctx: dict, entry_idx: int, direction: str, entry: float) -> float:
    """Best favourable open/close move (points) over the first bars after the entry."""
    best = 0.0
    for c in ctx['scan'][entry_idx + 1: entry_idx + 1 + FOLLOWTHROUGH_BARS]:
        o = float(c['open'])
        cl = float(c['close'])
        for px in (o, cl):
            move = (px - entry) if direction == 'BULL' else (entry - px)
            best = max(best, move)
    return best


def median_range_to_trigger(ctx: dict, trigger_idx: int | None) -> float | None:
    if trigger_idx is None:
        return None
    vals = [float(c['high']) - float(c['low'])
            for c in ctx['scan'][: trigger_idx + 1]]
    if len(vals) < 10:
        return None
    vals.sort()
    mid = len(vals) // 2
    return vals[mid] if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2


def classify(record: dict, signal: dict, engine, cpr_stats: dict) -> dict:
    """Point-in-time flags for one trade."""
    ctx = signal['ctx']
    entry = record['entry']
    direction = record['direction']
    flags = {}

    lvl = record.get('level_price')
    if lvl:
        ext = ((entry - lvl) if direction == 'BEAR' else (lvl - entry)) / lvl
        flags['extension_pct'] = round(ext * 100, 4)
        flags['extended_entry'] = bool(ext > EXTENSION_THRESHOLD)
    else:
        flags['extension_pct'] = None
        flags['extended_entry'] = False

    gap = ctx.get('gap_pct')
    flags['gap_pct'] = gap
    flags['large_gap'] = bool(gap is not None and abs(gap) > GAP_THRESHOLD)

    width = ctx.get('cpr_width_pct')
    flags['cpr_width_pct'] = width
    flags['narrow_cpr'] = bool(width is not None and cpr_stats.get('q25') is not None
                               and width < cpr_stats['q25'])
    flags['wide_cpr'] = bool(width is not None and cpr_stats.get('q75') is not None
                             and width > cpr_stats['q75'])

    med = median_range_to_trigger(ctx, signal['trigger_idx'])
    flags['median_range_to_trigger'] = None if med is None else round(med, 3)
    stop_distance = abs(entry * 0.005)
    flags['stop_distance_pts'] = round(stop_distance, 2)
    flags['range_vs_stop'] = bool(med is not None and med > stop_distance)

    ft = followthrough(ctx, signal['entry_idx'], direction, entry)
    flags['followthrough_best_pts'] = round(ft, 2)
    flags['weak_followthrough'] = bool(ft <= 0)

    flags['cpr_crossings_after_entry'] = cpr_crossings(ctx, signal['entry_idx'])
    flags['conflicting_triggers'] = bool(opposite_triggers(ctx, engine, direction))

    flags['stop_overshoot_pts'] = record['stop_overshoot_pts']
    flags['stop_overshoot_r'] = record['stop_overshoot_r']
    flags['fwd60_r'] = record.get('fwd60_r')
    flags['stop_then_continued'] = bool(record.get('fwd60_worst_r') is not None
                                        and record['fwd60_worst_r'] < 0)
    flags['stop_then_reversed'] = bool(record.get('fwd60_best_r') is not None
                                       and record['fwd60_best_r'] > 0)
    return flags


def missed_direction_category(record: dict, signal: dict, engine) -> dict:
    """Category A / B / C for the opposite direction of a stopped trade."""
    ctx = signal['ctx']
    entry_idx = signal['entry_idx']
    opp = opposite_triggers(ctx, engine, record['direction'])
    if not opp:
        return {'missed_direction_category': 'C',
                'missed_direction_level': None,
                'missed_direction_time': None,
                'missed_direction_detail': 'no opposite-direction trigger in the session'}
    at_or_before = [o for o in opp if o['idx'] <= entry_idx]
    after = [o for o in opp if o['idx'] > entry_idx]
    if at_or_before:
        first = at_or_before[0]
        return {'missed_direction_category': 'A',
                'missed_direction_level': first['level'],
                'missed_direction_time': first['time'],
                'missed_direction_detail': 'opposite trigger observable at or before the entry'}
    first = after[0]
    return {'missed_direction_category': 'B',
            'missed_direction_level': first['level'],
            'missed_direction_time': first['time'],
            'missed_direction_detail': 'opposite trigger only after the entry'}


def group_key(record: dict) -> str:
    return (f"{record['instrument']}|{record['direction']}|{record['setup']}|"
            f"{record['session_date']}|{record['entry_time'][:5]}")
