"""Point-in-time structure tests: swings, trends, volatility."""
from __future__ import annotations

try:  # the tests are imported as a package by pytest
    from .conftest import series, config, structures
except ImportError:  # flat import fallback
    from conftest import series, config, structures


def _pivot_high_at(i, base=100.0):
    """A series whose only strict fractal high is at bar `i`."""
    rows = [(base, base + 0.1, base - 0.1, base) for _ in range(20)]
    rows[i] = (base, base + 2.0, base - 0.1, base + 0.5)
    return series(rows)


def test_swing_is_only_confirmed_after_m_bars():
    candles = _pivot_high_at(8)
    before = structures.confirmed_swings(candles, upto_idx=9)
    assert all(s['confirm_idx'] > 9 for s in before['highs'])
    after = structures.confirmed_swings(candles, upto_idx=10)
    highs = [s for s in after['highs'] if s['idx'] == 8]
    assert len(highs) == 1
    assert highs[0]['confirm_idx'] == 8 + config.SWING_M
    assert highs[0]['price'] == 102.0


def test_strict_fractal_rejects_equal_neighbour():
    rows = [(100.0, 101.0, 99.0, 100.0) for _ in range(20)]
    rows[8] = (100.0, 102.0, 99.0, 101.0)
    rows[9] = (101.0, 102.0, 100.0, 101.0)   # equal high next to the pivot
    candles = series(rows)
    sw = structures.confirmed_swings(candles, upto_idx=15)
    assert all(s['idx'] != 8 for s in sw['highs'])


def test_last_confirmed_swing_respects_the_decision_bar():
    candles = _pivot_high_at(8)
    assert structures.last_confirmed_swing(candles, 9, 'high') is None
    sw = structures.last_confirmed_swing(candles, 10, 'high')
    assert sw is not None and sw['idx'] == 8


def _zigzag():
    """A clean zigzag with two descending swing highs and two descending lows."""
    highs = {5: 105.0, 15: 103.0}
    lows = {10: 95.0, 20: 93.0}
    rows = []
    for i in range(30):
        h = highs.get(i, 100.0)
        low = lows.get(i, 99.0)
        rows.append((100.0, h, low, 100.0))
    return series(rows)


def test_confirmed_downtrend_needs_two_descending_highs_and_lows():
    candles = _zigzag()
    # at bar 21 the swing low at 20 is not confirmed yet (confirm_idx = 22)
    assert structures.confirmed_downtrend(candles, 21) is None
    dt = structures.confirmed_downtrend(candles, 25)
    assert dt is not None
    assert dt['last_swing_high']['price'] == 103.0
    assert dt['last_swing_low']['price'] == 93.0
    assert dt['last_swing_high']['price'] < 105.0
    assert dt['last_swing_low']['price'] < 95.0


def test_uptrend_is_not_a_downtrend():
    highs = {5: 95.0, 15: 97.0}
    lows = {10: 105.0, 20: 107.0}
    rows = []
    for i in range(30):
        rows.append((100.0, highs.get(i, 100.0), lows.get(i, 99.0), 100.0))
    assert structures.confirmed_downtrend(series(rows), 25) is None


def test_median_range_is_point_in_time():
    candles = series([(100.0, 101.0, 99.0, 100.0) for _ in range(10)])
    med = structures.median_range(candles, 9)
    assert med == 2.0
    assert structures.median_range(candles, 1, min_bars=3) is None
