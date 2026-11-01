"""Price-path reconstruction: direction, window, forward path."""
from src import paths


def _bar(ts, o, h, l, c):
    return {'timestamp': ts, 'open': o, 'high': h, 'low': l, 'close': c}


def test_bull_excursion_uses_low_as_adverse():
    bars = [_bar('2026-07-07 09:15', 100.0, 101.0, 99.0, 100.5),
            _bar('2026-07-07 09:20', 100.5, 103.0, 98.0, 99.0)]
    exc = paths.excursion('BULL', 100.0, bars, 0, '2026-07-07 09:20')
    assert exc['mae_hl_pts'] == 2.0      # 100 - 98
    assert exc['mfe_hl_pts'] == 3.0      # 103 - 100
    assert exc['bars_held'] == 2


def test_bear_excursion_uses_high_as_adverse():
    bars = [_bar('2026-07-07 09:15', 100.0, 101.0, 99.0, 100.5),
            _bar('2026-07-07 09:20', 100.5, 103.0, 98.0, 99.0)]
    exc = paths.excursion('BEAR', 100.0, bars, 0, '2026-07-07 09:20')
    assert exc['mae_hl_pts'] == 3.0      # 103 - 100
    assert exc['mfe_hl_pts'] == 2.0      # 100 - 98


def test_excursion_window_stops_at_the_exit_bar():
    bars = [_bar('2026-07-07 09:15', 100.0, 101.0, 99.0, 100.5),
            _bar('2026-07-07 09:20', 100.5, 103.0, 98.0, 99.0),
            _bar('2026-07-07 09:25', 99.0, 120.0, 50.0, 60.0)]
    exc = paths.excursion('BULL', 100.0, bars, 0, '2026-07-07 09:20')
    assert exc['bars_held'] == 2
    assert exc['mfe_hl_pts'] == 3.0


def test_forward_path_is_signed_and_measures_the_excursion():
    bars = [_bar('2026-07-07 09:15', 100.0, 100.0, 100.0, 100.0),
            _bar('2026-07-07 09:20', 100.0, 100.0, 100.0, 100.0),
            _bar('2026-07-07 09:25', 100.0, 102.0, 96.0, 101.0),
            _bar('2026-07-07 09:30', 101.0, 101.0, 101.0, 101.0),
            _bar('2026-07-07 09:35', 101.0, 101.0, 101.0, 101.0)]
    fwd = paths.forward_path('BULL', 100.0, bars, 1, 2.0)
    assert fwd['fwd60_worst_r'] is None      # no 60-minute horizon in the data
    assert fwd['fwd15_r'] == 0.5              # close 101 vs exit 100, risk 2
    assert fwd['fwd15_worst_r'] == -2.0       # low 96 -> 4 points adverse / 2
    assert fwd['fwd15_best_r'] == 1.0         # high 102 -> 2 points / 2


def test_forward_path_of_a_bear_is_mirrored():
    bars = [_bar('2026-07-07 09:15', 100.0, 100.0, 100.0, 100.0),
            _bar('2026-07-07 09:20', 100.0, 100.0, 100.0, 100.0),
            _bar('2026-07-07 09:25', 100.0, 102.0, 96.0, 99.0),
            _bar('2026-07-07 09:30', 99.0, 99.0, 99.0, 99.0),
            _bar('2026-07-07 09:35', 99.0, 99.0, 99.0, 99.0)]
    fwd = paths.forward_path('BEAR', 100.0, bars, 1, 2.0)
    assert fwd['fwd15_r'] == 0.5              # close 99 -> 1 point in favour
    assert fwd['fwd15_worst_r'] == -1.0       # high 102 -> 2 points adverse
    assert fwd['fwd15_best_r'] == 2.0         # low 96 -> 4 points favourable


def test_post_exit_category_is_mutually_exclusive():
    forward = {'fwd60_worst_r': -1.2, 'fwd60_best_r': 0.9}
    assert paths.post_exit_category(forward, 10.0) == 'CONTINUATION_AGAINST'
    forward = {'fwd60_worst_r': -0.1, 'fwd60_best_r': 0.9}
    assert paths.post_exit_category(forward, 10.0) == 'REVERSAL_TOWARD_TARGET'
    forward = {'fwd60_worst_r': -0.1, 'fwd60_best_r': 0.2}
    assert paths.post_exit_category(forward, 10.0) == 'CHOP'
    forward = {'fwd60_worst_r': None, 'fwd60_best_r': None}
    assert paths.post_exit_category(forward, 10.0) == 'NOT_ASSESSABLE'


def test_first_touch_reports_the_earlier_level():
    bars = [_bar('2026-07-07 09:15', 100.0, 100.0, 94.0, 99.0),
            _bar('2026-07-07 09:20', 99.0, 111.0, 99.0, 110.0)]
    res = paths.first_touch('BULL', 95.0, 110.0, bars, 0, 1)
    assert res['first_touch_hl'] == 'STOP'
    assert res['both_levels_same_bar_hl'] is False
    bars = [_bar('2026-07-07 09:15', 100.0, 111.0, 100.0, 110.0),
            _bar('2026-07-07 09:20', 110.0, 110.0, 94.0, 95.0)]
    res = paths.first_touch('BULL', 95.0, 110.0, bars, 0, 1)
    assert res['first_touch_hl'] == 'TARGET'


def test_reconstructed_paths_are_consistent(book_rows):
    checked = 0
    for r in book_rows:
        if r.get('path_status') != 'OK' or r.get('risk_pts') in (None, 0):
            continue
        checked += 1
        assert r['mae_hl_r'] >= -0.001
        assert r['mfe_hl_r'] >= -0.001
        if r['exit_kind'] == 'STOP':
            # a stop exit is booked at or beyond the stop price
            assert r['stop_overshoot_r'] >= -0.01
    assert checked > 0
