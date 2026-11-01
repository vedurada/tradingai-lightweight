"""Stop placement variants (S0..S5).

Every stop is derived from the setup's invalidation logic and is only computed
from information that exists at the entry timestamp. When the required
information does not exist the variant returns ``None`` and the candidate is
recorded as NO_TRADE - a stop is never invented to keep a trade alive.
"""
from __future__ import annotations

from . import config, structures

STOP_VARIANTS = ('S0', 'S1', 'S2', 'S3', 'S4', 'S5')


def _buffer(price):
    return price * (1 + config.EPS_PCT)


def stop_price_for(variant, setup, candles, entry, entry_idx, levels=None):
    """Return ``(stop_price, source)`` or ``(None, reason)``."""
    if variant == 'S0':
        return entry * (1 + config.STOP_PCT), 'frozen baseline stop (0.5 % of entry)'

    if variant == 'S1':
        sw = structures.last_confirmed_swing(candles, entry_idx - 1, 'high')
        if sw is None:
            return None, 'no_confirmed_swing_high_at_entry'
        if sw['price'] <= entry:
            return None, 'confirmed_swing_high_not_above_entry'
        return _buffer(sw['price']), f"beyond confirmed swing high {sw['price']:.2f}"

    if variant == 'S2':
        arr = setup.get('arrival_idx')
        if arr is None or arr >= entry_idx:
            return None, 'no_failed_breakout_extreme_observable'
        highs = [float(c['high']) for c in candles[arr:entry_idx]]
        if not highs:
            return None, 'no_failed_breakout_extreme_observable'
        ext = max(highs)
        if ext <= setup['level_price']:
            return None, 'no_break_beyond_level'
        return _buffer(ext), f"beyond failed-breakout extreme {ext:.2f}"

    if variant == 'S3':
        return _buffer(setup['level_price']), f"beyond retest level {setup['level_price']:.2f}"

    if variant == 'S4':
        if not levels:
            return None, 'no_level_bundle'
        cands = []
        for key in ('pdh', 'tc', 'pp', 'r1', 'r2'):
            v = levels.get(key)
            if v is not None and v > entry:
                cands.append((float(v), key))
        if not cands:
            return None, 'no_pre_existing_level_above_entry'
        price, key = min(cands)
        return _buffer(price), f"beyond pre-existing level {key} {price:.2f}"

    if variant == 'S5':
        base = stop_price_for('S1', setup, candles, entry, entry_idx, levels)[0]
        if base is None:
            base = stop_price_for('S3', setup, candles, entry, entry_idx, levels)[0]
        if base is None:
            return None, 'no_structural_base_for_volatility_buffer'
        med = structures.median_range(candles, entry_idx - 1)
        if med is None:
            return None, 'no_median_range'
        return base + config.K_VOL * med, 'structural level + 0.5 x median bar range'

    raise ValueError(f'unknown stop variant {variant}')


def stop_setups(setup, candles, entry, entry_idx, levels=None):
    """All stop variants for one entry, with availability and reasons."""
    out = {}
    for v in STOP_VARIANTS:
        px, src = stop_price_for(v, setup, candles, entry, entry_idx, levels)
        out[v] = {'stop_price': round(px, 4) if px is not None else None,
                  'source': src,
                  'available': px is not None}
    return out
