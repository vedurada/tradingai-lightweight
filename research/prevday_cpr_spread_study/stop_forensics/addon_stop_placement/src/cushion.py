"""Entry-cushion measurement (spec_addon.md §3)."""
from __future__ import annotations

try:  # package import when run as part of the study
    from . import execution_ext, structures
except ImportError:  # pragma: no cover - direct module import in tests
    import execution_ext
    import structures

ALL_LEVEL_KEYS = ('r1', 'r2', 'pdh', 'tc', 'pp', 'bc', 's1', 's2', 'pdl')
LEVEL_LABELS = {
    'pp': 'pivot', 'tc': 'CPR top', 'bc': 'CPR bottom', 'r1': 'R1', 'r2': 'R2',
    's1': 'S1', 's2': 'S2', 'pdh': 'prior day high', 'pdl': 'prior day low',
}


def nearest_opposing(levels: dict, entry: float, direction: str):
    """Nearest level on the profitable side: below for BEAR, above for BULL."""
    if not levels:
        return None, None
    vals = [(k, float(levels[k])) for k in ALL_LEVEL_KEYS if levels.get(k) is not None]
    if direction == 'BEAR':
        vals = [(k, v) for k, v in vals if v < entry]
        return (max(vals, key=lambda kv: kv[1]) if vals else (None, None))
    vals = [(k, v) for k, v in vals if v > entry]
    return (min(vals, key=lambda kv: kv[1]) if vals else (None, None))


def measure(direction: str, entry: float, stop_px: float, target_px: float,
            candles: list, entry_idx: int, exit_ts: str | None,
            levels: dict, median_range_pts, target_pct: float = 0.02) -> dict:
    risk = abs(entry - stop_px)
    stop_pts = round(risk, 4)
    stop_pct = round(risk / entry, 6)
    name, price = nearest_opposing(levels, entry, direction)
    if price is None:
        opp_pts = opp_pct = None
    else:
        opp_pts = round(abs(entry - price), 4)
        opp_pct = round(abs(entry - price) / entry, 6)
    target_pts = round(abs(target_px - entry), 4)
    mae = execution_ext.mae_before_first_profit(direction, entry, candles, entry_idx, exit_ts)
    pullback = (median_range_pts is not None
                and stop_pts < structures.PULLBACK_MULT * median_range_pts)
    return {
        'stop_distance_pts': stop_pts,
        'stop_distance_pct': stop_pct,
        'nearest_opposing_name': LEVEL_LABELS.get(name, name) if name else None,
        'nearest_opposing_price': None if price is None else round(price, 4),
        'nearest_opposing_pts': opp_pts,
        'nearest_opposing_pct': opp_pct,
        'reward_to_target_pts': target_pts,
        'rr_to_target': round(target_pts / stop_pts, 4) if stop_pts else None,
        'rr_to_nearest_level': (round(opp_pts / stop_pts, 4)
                                if opp_pts is not None and stop_pts else None),
        'mae_before_first_profit_pts': mae['mae_before_first_profit_pts'],
        'mae_before_first_profit_r': (round(mae['mae_before_first_profit_pts'] / stop_pts, 4)
                                      if stop_pts else None),
        'bars_to_first_profit': mae['bars_to_first_profit'],
        'pullback_would_hit': bool(pullback),
        'risk_excessive': bool(stop_pct > structures.MAX_STOP_PCT),
        'wider_than_production': bool(stop_pts > 0.005 * entry + 0.01),
        'cushion_note': ('the cushion is context only; a wider cushion is not a '
                         'better trade and is not scored as one'),
    }
