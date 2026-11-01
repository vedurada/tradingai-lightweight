"""Unit tests for the production replica (prodlib)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src'))

import prodlib as P  # noqa: E402
import wconfig as C  # noqa: E402


def test_calculate_cpr_matches_production_math():
    cpr = P.calculate_cpr(24500.0, 24000.0, 24200.0)
    assert cpr['pp'] == round((24500.0 + 24000.0 + 24200.0) / 3, 4)
    # production swaps tc/bc when tc < bc: here tc(24216.67) < bc(24250) -> swapped
    assert abs(cpr['bc'] - round((24500.0 + 24000.0 + 24200.0) / 3 * 2 - 24250.0, 4)) < 1e-3
    assert cpr['tc'] == 24250.0


def test_day_levels_bundle():
    lv = P.day_levels(24500.0, 24000.0, 24200.0)
    assert set(['pp', 'tc', 'bc', 'r1', 's1', 'r2', 's2', 'pdh', 'pdl']) <= set(lv)
    assert lv['pdh'] == 24500.0 and lv['pdl'] == 24000.0


def test_bear_trigger_priority():
    lv = {'r2': 25000.0, 'r1': 24600.0, 'pdh': 24500.0, 'bc': 24000.0}
    assert P.bear_trigger({'high': 25010.0, 'close': 24900.0}, lv) == 'R2'
    assert P.bear_trigger({'high': 24610.0, 'close': 24500.0}, lv) == 'R1'
    assert P.bear_trigger({'high': 24510.0, 'close': 24400.0}, lv) == 'PDH'
    assert P.bear_trigger({'high': 24400.0, 'close': 23900.0}, lv) == 'BELOW_CPR'
    assert P.bear_trigger({'high': 24400.0, 'close': 24400.0}, lv) is None


def test_exits_opens_stop_before_target_and_gap():
    stop_bear = 24500.0 * 1.005      # 24622.5
    target_bear = 24500.0 * 0.98     # 24010.0
    r, px, how, ts = P.exits_opens('BEAR', 24500.0, 0.005, 0.02,
                                   [('t1', 24400.0), ('t2', stop_bear)])
    assert (r, px, how) == (-1.0, round(stop_bear, 2), 'STOP')   # an open exactly on the stop
    r, px, how, _ = P.exits_opens('BEAR', 24500.0, 0.005, 0.02, [('t1', 23900.0)])
    assert (r, px, how) == (4.0, 23900.0, 'TARGET')     # the target R = 0.02/0.005
    r, px, how, _ = P.exits_opens('BEAR', 24500.0, 0.005, 0.02, [('t1', target_bear)])
    assert (r, px, how) == (4.0, round(target_bear, 2), 'TARGET')
    assert P.exits_opens('BEAR', 24500.0, 0.005, 0.02, [('t1', 24400.0)]) is None


def test_exits_opens_bull_direction():
    stop_bull = 24500.0 * 0.995      # 24377.5
    target_bull = 24500.0 * 1.02     # 24990.0
    r, px, how, _ = P.exits_opens('BULL', 24500.0, 0.005, 0.02, [('t1', stop_bull)])
    assert (r, px, how) == (-1.0, round(stop_bull, 2), 'STOP')
    r, px, how, _ = P.exits_opens('BULL', 24500.0, 0.005, 0.02, [('t1', target_bull)])
    assert (r, px, how) == (4.0, round(target_bull, 2), 'TARGET')


def test_decay_win_tolerance_boundary():
    assert P.decay_win('BEAR', 24500.0, 24510.0, -0.1, 'NIFTY') == 'WIN'
    assert P.decay_win('BEAR', 24500.0, 24530.0, -1.0, 'NIFTY') == 'LOSS'
    assert P.decay_win('BEAR', 24500.0, 24530.0, 0.0, 'NIFTY') == 'FLAT'
    assert P.decay_win('BEAR', 24500.0, 24400.0, 0.5, 'NIFTY') == 'WIN'


def test_friday_skip_only_beer():
    assert P.friday_skip('BEAR', '2026-10-16') is True    # a Friday
    assert P.friday_skip('BULL', '2026-10-16') is False
    assert P.friday_skip('BEAR', '2026-10-15') is False


def test_level_price_mapping():
    lv = {'r1': 101.0, 'r2': 102.0, 'pdh': 103.0, 'bc': 99.0, 'tc': 105.0}
    assert P.level_price('R1', lv) == 101.0
    assert P.level_price('BELOW_CPR', lv) == 99.0
    assert P.level_price('BRK_TC', lv) == 105.0
    assert P.level_price('NOPE', lv) is None


def test_evaluate_outcome_flat_at_eod():
    candles = [
        {'timestamp': '2026-07-07T09:15:00+05:30', 'open': 100.0, 'high': 100.5, 'low': 99.5, 'close': 100.0},
        {'timestamp': '2026-07-07T15:20:00+05:30', 'open': 100.2, 'high': 100.4, 'low': 100.1, 'close': 100.3},
    ]
    out = P.evaluate_outcome('BEAR', 100.0, 0, candles, 'NIFTY')
    assert out['exit_reason'] == 'EOD-1520'
    assert out['r_multiple'] == round(-0.2 / 0.5, 3)   # a BEAR closed higher = a loss in R
    assert out['win_loss'] == 'WIN'
