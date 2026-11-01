"""Stop-placement tests: availability rules and price arithmetic."""
from __future__ import annotations

try:  # the tests are imported as a package by pytest
    from .conftest import series, make_setup, config, stops
except ImportError:  # flat import fallback
    from conftest import series, make_setup, config, stops


def _bundle(pdh=105.0, tc=102.0, pp=100.0, r1=106.0, r2=108.0):
    return {'pdh': pdh, 'tc': tc, 'pp': pp, 'r1': r1, 'r2': r2,
            's1': 99.0, 's2': 98.0, 'bc': 98.5}


def test_s0_is_the_frozen_baseline_stop():
    px, src = stops.stop_price_for('S0', None, [], 100.0, 5)
    assert px == 100.0 * (1 + config.STOP_PCT)
    assert 'baseline' in src


def test_s1_requires_a_confirmed_swing_high_above_the_entry():
    candles = series([(99.0, 99.1, 98.9, 99.0) for _ in range(30)])
    setup = make_setup(level=100.0, candles=candles)
    px, src = stops.stop_price_for('S1', setup, candles, 99.0, 10)
    assert px is None
    assert 'swing' in src


def test_s1_uses_the_last_confirmed_swing_high():
    rows = [(99.0, 99.1, 98.9, 99.0) for _ in range(30)]
    rows[5] = (99.0, 100.5, 98.9, 99.5)
    candles = series(rows)
    setup = make_setup(level=100.0, candles=candles)
    px, src = stops.stop_price_for('S1', setup, candles, 99.0, 10)
    assert px is not None
    assert px == 100.5 * (1 + config.EPS_PCT)


def test_s2_requires_a_break_beyond_the_level():
    candles = series([(99.0, 99.1, 98.9, 99.0) for _ in range(30)])
    setup = make_setup(level=100.0, candles=candles)
    setup['arrival_idx'] = 5
    px, src = stops.stop_price_for('S2', setup, candles, 99.0, 10)
    assert px is None
    assert 'break' in src


def test_s2_uses_the_failed_breakout_extreme():
    rows = [(99.0, 99.1, 98.9, 99.0) for _ in range(10)]
    rows[5] = (99.0, 100.4, 98.9, 99.5)
    candles = series(rows)
    setup = make_setup(level=100.0, candles=candles)
    setup['arrival_idx'] = 5
    px, src = stops.stop_price_for('S2', setup, candles, 99.0, 10)
    assert px == 100.4 * (1 + config.EPS_PCT)


def test_s3_is_the_level_plus_a_buffer():
    setup = make_setup(level=100.0)
    px, src = stops.stop_price_for('S3', setup, [], 99.0, 10)
    assert px == 100.0 * (1 + config.EPS_PCT)


def test_s4_uses_the_nearest_pre_existing_level_above_the_entry():
    setup = make_setup(level=100.0)
    px, src = stops.stop_price_for('S4', setup, [], 99.0, 10, levels=_bundle())
    assert px == 100.0 * (1 + config.EPS_PCT)      # pivot is the nearest above 99
    assert 'pivot' in src or 'pp' in src


def test_s4_returns_nothing_when_no_level_is_above_the_entry():
    setup = make_setup(level=100.0)
    px, src = stops.stop_price_for('S4', setup, [], 120.0, 10, levels=_bundle())
    assert px is None
    assert 'no_pre_existing_level_above_entry' in src


def test_s5_adds_a_volatility_buffer_to_a_structural_base():
    rows = [(99.0, 100.0, 98.0, 99.0) for _ in range(30)]
    candles = series(rows)
    setup = make_setup(level=100.0, candles=candles)
    px, src = stops.stop_price_for('S5', setup, candles, 99.0, 10, levels=_bundle())
    assert px is None or px > setup['level_price'] * (1 + config.EPS_PCT)


def test_a_stop_is_never_invented():
    candles = series([(99.0, 99.1, 98.9, 99.0) for _ in range(30)])
    setup = make_setup(level=100.0, candles=candles)
    for variant in stops.STOP_VARIANTS:
        px, src = stops.stop_price_for(variant, setup, candles, 99.0, 10,
                                       levels=_bundle())
        assert src, f'{variant} must explain itself'
        if px is None:
            assert 'no_' in str(src), f'{variant} invented a stop'
        else:
            assert px > 99.0


def test_stop_set_reports_every_variant():
    candles = series([(99.0, 99.1, 98.9, 99.0) for _ in range(30)])
    setup = make_setup(level=100.0, candles=candles)
    out = stops.stop_setups(setup, candles, 99.0, 10, levels=_bundle())
    assert set(out) == set(stops.STOP_VARIANTS)
    for k, v in out.items():
        assert 'available' in v and 'source' in v
