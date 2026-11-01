"""Setup state machine and entry-gate tests."""
from __future__ import annotations

try:  # the tests are imported as a package by pytest
    from .conftest import series, make_setup, config, engine
except ImportError:  # flat import fallback
    from conftest import series, make_setup, config, engine


def _rally_then_reject(level=100.0, n=40):
    """Flat below the level, then a rally into the zone, then a close back below."""
    rows = []
    for i in range(n):
        if i < 10:
            rows.append((99.5, 99.6, 99.4, 99.5))
        elif i < 14:
            rows.append((99.6, level + 0.05, 99.5, level + 0.02))   # arrival
        elif i == 14:
            rows.append((level + 0.02, level + 0.03, level - 0.40, level - 0.30))
        else:
            rows.append((level - 0.25, level - 0.24, level - 0.26, level - 0.25))
    return series(rows)


def test_zone_is_fixed_at_identification():
    candles = _rally_then_reject()
    setup = make_setup(level=100.0, candles=candles)
    lo, hi = setup['zone_low'], setup['zone_high']
    engine.SetupTracker(setup, candles).run()
    assert setup['zone_low'] == lo and setup['zone_high'] == hi


def test_arrival_requires_the_zone_to_be_reached():
    candles = series([(99.0, 99.1, 98.9, 99.0) for _ in range(40)])
    setup = make_setup(level=100.0, candles=candles)
    engine.SetupTracker(setup, candles).run()
    assert setup['state'] == config.STATE_EXPIRED
    assert setup['rejection_reason'] == 'no_arrival_in_window'


def test_confirmation_is_a_close_back_below_the_level():
    candles = _rally_then_reject()
    setup = make_setup(level=100.0, candles=candles)
    engine.SetupTracker(setup, candles).run()
    assert setup['state'] == config.STATE_CONFIRMED
    assert setup['confirm_idx'] == 14
    assert setup['confirm_ts'] == candles[14]['timestamp']
    # the confirming bar is closed below the level
    assert float(candles[14]['close']) < 100.0


def test_entry_is_the_open_of_the_bar_after_the_confirmation():
    candles = _rally_then_reject()
    setup = make_setup(level=100.0, candles=candles)
    engine.SetupTracker(setup, candles).run()
    core = engine.plan_entry_core(setup, candles)
    assert core['entry_idx'] == setup['confirm_idx'] + 1
    assert core['entry'] == float(candles[core['entry_idx']]['open'])
    assert core['entry_ts'] == candles[core['entry_idx']]['timestamp']


def test_an_entry_at_or_after_the_window_close_is_a_no_trade():
    rows = [(99.5, 99.6, 99.4, 99.5) for _ in range(71)]   # 09:15 .. 15:05
    rows.append((99.6, 100.05, 99.5, 99.98))              # 15:10 arrival
    rows.append((99.98, 100.0, 99.6, 99.7))               # 15:15 confirmation
    rows.append((99.7, 99.8, 99.6, 99.7))                 # 15:20 entry bar
    candles = series(rows)
    setup = make_setup(level=100.0, candles=candles, id_idx=70)
    engine.SetupTracker(setup, candles).run()
    core = engine.plan_entry_core(setup, candles)
    assert core['decision'] == config.STATE_NO_TRADE
    assert 'entry_after_window' in core['reasons']


def test_too_extended_entry_is_missed_not_taken():
    candles = _rally_then_reject()
    # the confirming close is far below the level -> the next open is too far away
    rows = []
    for i in range(40):
        if i < 10:
            rows.append((99.5, 99.6, 99.4, 99.5))
        elif i < 14:
            rows.append((99.6, 100.05, 99.5, 99.98))
        elif i == 14:
            rows.append((99.98, 99.99, 98.0, 98.2))     # a big drop
        else:
            rows.append((98.2, 98.3, 98.1, 98.2))
    candles = series(rows)
    setup = make_setup(level=100.0, candles=candles)
    engine.SetupTracker(setup, candles).run()
    core = engine.plan_entry_core(setup, candles)
    assert core['decision'] == config.STATE_MISSED
    assert 'too_extended_to_chase' in core['reasons']


def test_stop_gates_reject_a_reward_risk_below_the_minimum():
    core = {'decision': 'PENDING_STOP_GATES', 'entry': 100.0, 'reasons': []}
    out = engine.apply_stop_gates(core, 101.4, 98.0)   # risk 1.4 %, reward 2 %
    assert out['decision'] == config.STATE_NO_TRADE
    assert 'reward_risk_below_minimum' in out['reasons']


def test_stop_gates_reject_a_stop_that_is_too_tight_or_too_wide():
    core = {'decision': 'PENDING_STOP_GATES', 'entry': 100.0, 'reasons': []}
    tight = engine.apply_stop_gates(core, 100.1, 98.0)
    assert 'risk_distance_too_small' in tight['reasons']
    wide = engine.apply_stop_gates(core, 102.0, 98.0)
    assert 'risk_distance_too_large' in wide['reasons']


def test_stop_gates_accept_a_valid_stop():
    core = {'decision': 'PENDING_STOP_GATES', 'entry': 100.0, 'reasons': []}
    out = engine.apply_stop_gates(core, 100.5, 98.0)
    assert out['decision'] == config.STATE_TRADE_ELIGIBLE
    assert out['rr'] == 4.0


def test_setup_expires_after_the_pre_declared_window():
    candles = series([(99.5, 99.6, 99.4, 99.5) for _ in range(40)])
    setup = make_setup(level=100.0, candles=candles, expiry=5)
    engine.SetupTracker(setup, candles).run()
    assert setup['state'] == config.STATE_EXPIRED
    assert setup['transitions'][-1]['bar_idx'] == 5


def test_setup_is_invalidated_when_price_closed_through_the_zone():
    rows = [(99.5, 99.6, 99.4, 99.5) for _ in range(10)]
    rows.append((99.6, 101.5, 99.5, 101.0))     # a close above the zone
    rows += [(101.0, 101.2, 100.8, 101.0)] * 20
    candles = series(rows)
    setup = make_setup(level=100.0, candles=candles)
    engine.SetupTracker(setup, candles).run()
    assert setup['state'] == config.STATE_INVALIDATED
    assert setup['rejection_reason'] == 'closed_above_zone_before_arrival'


def test_transitions_are_timestamped_and_ordered():
    candles = _rally_then_reject()
    setup = make_setup(level=100.0, candles=candles)
    engine.SetupTracker(setup, candles).run()
    trans = setup['transitions']
    assert trans[0]['to_state'] == config.STATE_ZONE_REACHED
    assert trans[-1]['to_state'] == config.STATE_CONFIRMED
    idx = [t['bar_idx'] for t in trans]
    assert idx == sorted(idx)
    assert all(t['ts'] == candles[t['bar_idx']]['timestamp'] for t in trans)


def test_no_confirmation_without_arrival():
    candles = series([(99.0, 99.1, 98.9, 99.0) for _ in range(40)])
    setup = make_setup(level=100.0, candles=candles)
    engine.SetupTracker(setup, candles).run()
    assert setup['confirm_idx'] is None
    assert setup['state'] != config.STATE_CONFIRMED
