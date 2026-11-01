"""Point-in-time and prefix-invariance tests.

If any part of the study used information that was not available at the
decision bar, truncating the session after the decision would change the
result. These tests truncate the data and compare.
"""
from __future__ import annotations

try:  # the tests are imported as a package by pytest
    from .conftest import series, make_setup, config, engine, setups
except ImportError:  # flat import fallback
    from conftest import series, make_setup, config, engine, setups


def _session(n=40):
    rows = []
    for i in range(n):
        if i < 10:
            rows.append((99.5, 99.6, 99.4, 99.5))
        elif i < 14:
            rows.append((99.6, 100.05, 99.5, 99.98))
        elif i == 14:
            rows.append((99.98, 99.99, 99.2, 99.3))
        else:
            rows.append((99.3, 99.4, 99.2, 99.3))
    return series(rows)


def test_the_state_machine_is_prefix_invariant():
    candles = _session()
    setup = make_setup(level=100.0, candles=candles)
    engine.SetupTracker(setup, candles).run()
    assert setup['state'] == config.STATE_CONFIRMED
    cut = setup['confirm_idx'] + 1

    prefix = make_setup(level=100.0, candles=candles[:cut])
    engine.SetupTracker(prefix, candles[:cut]).run()
    assert prefix['state'] == setup['state']
    assert prefix['confirm_idx'] == setup['confirm_idx']
    assert prefix['confirm_ts'] == setup['confirm_ts']
    assert prefix['arrival_idx'] == setup['arrival_idx']


def test_the_entry_plan_is_prefix_invariant():
    candles = _session()
    setup = make_setup(level=100.0, candles=candles)
    engine.SetupTracker(setup, candles).run()
    core = engine.plan_entry_core(setup, candles)
    cut = core['entry_idx'] + 1

    prefix_setup = make_setup(level=100.0, candles=candles[:cut])
    engine.SetupTracker(prefix_setup, candles[:cut]).run()
    core_prefix = engine.plan_entry_core(prefix_setup, candles[:cut])
    assert core_prefix['entry'] == core['entry']
    assert core_prefix['entry_ts'] == core['entry_ts']
    assert core_prefix['decision'] == core['decision']


def test_setups_identified_early_do_not_change_when_more_candles_arrive():
    candles = _session()
    bundle = {'pdh': 105.0, 'pdl': 95.0, 'pp': 100.0, 'tc': 101.0, 'bc': 99.0,
              'r1': 103.0, 'r2': 106.0, 's1': 97.0, 's2': 95.5}
    full = setups.build_session_setups('NIFTY', '2026-09-01', candles, bundle, 'VAL')
    cut = 20
    part = setups.build_session_setups('NIFTY', '2026-09-01', candles[:cut],
                                       bundle, 'VAL')
    keys_full = {(s['setup_family'], s['level_price'], s['identification_idx'])
                 for s in full}
    for s in part:
        key = (s['setup_family'], s['level_price'], s['identification_idx'])
        assert key in keys_full


def test_a_setup_is_never_identified_before_its_data_exists():
    candles = _session()
    bundle = {'pdh': 105.0, 'pdl': 95.0, 'pp': 100.0, 'tc': 101.0, 'bc': 99.0,
              'r1': 103.0, 'r2': 106.0, 's1': 97.0, 's2': 95.5}
    found = setups.build_session_setups('NIFTY', '2026-09-01', candles, bundle, 'VAL')
    for s in found:
        assert s['identification_idx'] < len(candles)
        assert s['identification_ts'] == candles[s['identification_idx']]['timestamp']


def test_confirmation_cannot_be_the_same_bar_as_the_arrival():
    candles = _session()
    setup = make_setup(level=100.0, candles=candles)
    engine.SetupTracker(setup, candles).run()
    if setup['confirm_idx'] is not None:
        assert setup['confirm_idx'] > setup['arrival_idx']
