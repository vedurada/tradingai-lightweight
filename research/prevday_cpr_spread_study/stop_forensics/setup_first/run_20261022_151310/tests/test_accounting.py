"""The candidate accounting must be identical to the parent's accounting."""
from __future__ import annotations

try:  # the tests are imported as a package by pytest
    from .conftest import series, make_setup, records
except ImportError:  # flat import fallback
    from conftest import series, make_setup, records
from research.prevday_cpr_spread_study.stop_forensics.src import accounting


def _ctx(candles):
    return {'scan': candles, 'gap_pct': 0.1, 'cpr_width_pct': 0.5,
            'candles': candles, 'levels': None, 'period': 'VAL'}


def _session(level=100.0):
    """A full session: 09:15 .. 15:20 (74 bars), so the EOD exit exists."""
    rows = []
    for i in range(74):
        if i < 5:
            rows.append((level - 0.4, level - 0.3, level - 0.5, level - 0.4))
        elif i < 12:
            rows.append((level - 0.4, level - 0.1, level - 0.5, level - 0.3))
        else:
            rows.append((level - 0.3, level - 0.2, level - 0.6, level - 0.4))
    return series(rows)


def test_candidate_record_matches_the_parent_accounting():
    candles = _session()
    ctx = _ctx(candles)
    setup = make_setup(level=100.0, candles=candles)
    entry = 99.5
    entry_idx = 6
    stop = 100.0
    target = 98.0
    rec = records.build_trade(setup, ctx, entry, entry_idx, stop, target,
                              arm='TEST', stop_source='test', stop_variant='S3')
    assert rec is not None

    signal = {
        'instrument': setup['instrument'], 'session_date': setup['session_date'],
        'direction': 'BEAR', 'level': 'TEST', 'level_price': setup['level_price'],
        'trigger_idx': 5, 'entry_idx': entry_idx, 'entry': entry,
        'entry_time': str(candles[entry_idx]['timestamp'])[:16].replace('T', ' '),
        'signal_time': candles[0]['timestamp'], 'ctx': ctx, 'period': 'VAL',
    }
    parent = accounting.account(signal, 'TEST', entry=entry, entry_idx=entry_idx,
                                 entry_source='setup_first_next_bar_open',
                                 stop_pct=(stop - entry) / entry,
                                 target_pct=(entry - target) / entry)
    assert parent is not None
    assert rec['exit_reason'] == parent['exit_reason']
    assert rec['exit_price'] == parent['exit_price']
    assert rec['exit_time'] == parent['exit_time']
    assert rec['realized_r'] == parent['realized_r']
    assert rec['realized_pts'] == parent['realized_pts']
    assert rec['risk_pts'] == parent['risk_pts']


def test_a_gap_through_the_stop_is_filled_at_the_open():
    rows = [(99.5, 99.6, 99.4, 99.5) for _ in range(3)]
    rows.append((99.5, 101.5, 99.4, 101.0))       # a gap above the stop
    rows += [(101.0, 101.2, 100.8, 101.0) for _ in range(10)]
    candles = series(rows)
    ctx = _ctx(candles)
    setup = make_setup(level=100.0, candles=candles)
    rec = records.build_trade(setup, ctx, 99.5, 2, 100.0, 97.0, arm='TEST',
                              stop_source='test', stop_variant='S3')
    assert rec is not None
    assert rec['exit_reason'] == 'STOP'
    assert rec['exit_price'] == 101.0          # the open, not the stop price
    assert rec['stop_overshoot_pts'] > 0


def test_a_missing_end_of_session_candle_produces_no_trade():
    rows = [(99.5, 99.6, 99.4, 99.5) for _ in range(5)]
    candles = series(rows)                      # no 15:20 bar in this list
    ctx = _ctx(candles)
    setup = make_setup(level=100.0, candles=candles)
    rec = records.build_trade(setup, ctx, 99.5, 1, 100.0, 97.0, arm='TEST',
                              stop_source='test', stop_variant='S3')
    assert rec is None
