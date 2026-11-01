"""Point-in-time structure helpers (confirmed swings, level bundles).

Nothing here reads a candle that was not fully closed at the decision bar.
A fractal pivot at bar ``i`` is only *known* at the close of bar ``i + m``;
every consumer therefore filters on ``confirm_idx <= decision_idx``.
"""
from __future__ import annotations

from . import config


def _strict_pivot(values, i, m, is_high):
    """Strict m-bar fractal at index i (m bars each side, no ties allowed)."""
    lo, hi = i - m, i + m
    if lo < 0 or hi >= len(values):
        return False
    v = values[i]
    for j in range(lo, hi + 1):
        if j == i:
            continue
        if is_high:
            if values[j] >= v:
                return False
        else:
            if values[j] <= v:
                return False
    return True


def confirmed_swings(candles, upto_idx=None, m=config.SWING_M,
                     lookback=config.SWING_LOOKBACK):
    """Confirmed swing highs/lows available at the close of bar ``upto_idx``.

    Returns ``{'highs': [...], 'lows': [...]}`` where each item is
    ``{'idx', 'confirm_idx', 'price', 'ts'}``; ``confirm_idx`` is the first bar
    at which the pivot was knowable (close of pivot+m).
    """
    end = len(candles) - 1 if upto_idx is None else min(upto_idx, len(candles) - 1)
    highs, lows = [], []
    highs_v = [float(c['high']) for c in candles]
    lows_v = [float(c['low']) for c in candles]
    for i in range(1, end):
        if i + m > end:
            break
        if _strict_pivot(highs_v, i, m, True):
            highs.append({'idx': i, 'confirm_idx': i + m,
                          'price': highs_v[i], 'ts': str(candles[i]['timestamp'])})
        if _strict_pivot(lows_v, i, m, False):
            lows.append({'idx': i, 'confirm_idx': i + m,
                         'price': lows_v[i], 'ts': str(candles[i]['timestamp'])})
    if lookback:
        highs = [h for h in highs if h['confirm_idx'] >= end - lookback]
        lows = [s for s in lows if s['confirm_idx'] >= end - lookback]
    return {'highs': highs, 'lows': lows}


def last_confirmed_swing(candles, upto_idx, kind, m=config.SWING_M,
                          lookback=config.SWING_LOOKBACK):
    """Most recent confirmed swing high/low knowable at bar ``upto_idx``."""
    sw = confirmed_swings(candles, upto_idx, m, lookback)
    series = sw['highs'] if kind == 'high' else sw['lows']
    if not series:
        return None
    return series[-1]


def confirmed_downtrend(candles, upto_idx, m=config.SWING_M,
                        lookback=config.SWING_LOOKBACK):
    """Point-in-time downtrend test.

    Requires two confirmed swing highs with descending prices and two confirmed
    swing lows with descending prices, all confirmed at or before ``upto_idx``.
    """
    sw = confirmed_swings(candles, upto_idx, m, lookback)
    highs, lows = sw['highs'], sw['lows']
    if len(highs) < 2 or len(lows) < 2:
        return None
    h1, h2 = highs[-2], highs[-1]
    l1, l2 = lows[-2], lows[-1]
    if not (h2['price'] < h1['price'] and l2['price'] < l1['price']):
        return None
    return {'swing_highs': [h1, h2], 'swing_lows': [l1, l2],
            'last_swing_high': h2, 'last_swing_low': l2}


def median_range(candles, upto_idx, bars=20, min_bars=config.VOL_MIN_BARS):
    """Median intrabar range over the last ``bars`` closed candles (point-in-time)."""
    lo = max(0, upto_idx - bars + 1)
    window = candles[lo:upto_idx + 1]
    if len(window) < min_bars:
        return None
    ranges = sorted(float(c['high']) - float(c['low']) for c in window)
    n = len(ranges)
    mid = n // 2
    med = ranges[mid] if n % 2 else (ranges[mid - 1] + ranges[mid]) / 2
    return med
