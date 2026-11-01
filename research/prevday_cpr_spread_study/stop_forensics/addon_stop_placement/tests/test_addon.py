"""Unit tests for the add-on: structures, execution models, records, gates.

These tests use synthetic candles only; they never touch the database or `app.*`.
Run with PYTHONPATH pointing at the parent study's src and this study's src.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ADD_SRC = os.path.normpath(os.path.join(HERE, '..', 'src'))
PARENT_SRC = os.path.normpath(os.path.join(HERE, '..', '..', 'src'))
for p in (ADD_SRC, PARENT_SRC):
    if p not in sys.path:
        sys.path.insert(0, p)

import execution_ext as ex
import metrics_ext as mx
import records as rc
import structures as st


def mk(rows):
    out = []
    h, m = 9, 20
    for o, hi, lo, c in rows:
        out.append({'timestamp': f'2026-09-01T{h:02d}:{m:02d}:00+05:30',
                    'open': o, 'high': hi, 'low': lo, 'close': c, 'volume': 0})
        m += 5
        if m >= 60:
            h, m = h + 1, m - 60
    return out


def pit_signal(scan, trig, entry_idx, direction='BEAR', level='PDH',
               level_price=100.0, break_side='above'):
    return {'instrument': 'NIFTY', 'session_date': '2026-09-01',
            'direction': direction, 'level': level, 'trigger_idx': trig,
            'entry_idx': entry_idx, 'entry': float(scan[entry_idx]['open']),
            'entry_time': str(scan[entry_idx]['timestamp'])[:16].replace('T', ' '),
            'signal_time': str(scan[trig]['timestamp']), 'level_price': level_price,
            'break_side': break_side, 'period': 'VAL',
            'ctx': {'scan': scan, 'levels': {'pp': 98.0, 'tc': 99.0, 'bc': 97.0,
                                             'r1': 101.0, 'r2': 103.0, 's1': 95.0,
                                             's2': 93.0, 'pdh': 100.0, 'pdl': 90.0},
                    'gap_pct': 0.0, 'cpr_width_pct': 0.02}}


def test_eps_is_fraction_of_entry():
    assert abs(st.eps(10000) - 2.0) < 1e-9
    assert abs(st.eps(50000) - 10.0) < 1e-9


def test_swing_requires_strict_fractal_and_right_confirmation():
    scan = mk([(100, 101, 99, 100)] * 3 + [(100, 110, 99, 104),
                                           (104, 106, 101, 102),
                                           (102, 103, 100, 101)] +
              [(101, 102, 99, 100)] * 3)
    sw = st.swings(scan, m=2)
    highs = [s for s in sw if s['kind'] == 'HIGH']
    assert highs and highs[0]['idx'] == 3
    assert highs[0]['confirm_idx'] == 5


def test_swing_not_usable_before_confirmation():
    scan = mk([(100, 101, 99, 100)] * 3 + [(100, 110, 99, 104)])
    assert st.usable_swing(scan, 3, 'BEAR', 104) [0] is None
    assert st.usable_swing(scan, 4, 'BEAR', 104)[0] is None


def test_validate_rejects_wrong_side_and_out_of_bounds():
    assert st.validate('BEAR', 100, 99) is not None
    assert st.validate('BEAR', 100, 100.1) is not None
    assert st.validate('BEAR', 100, 101.6) is not None
    assert st.validate('BEAR', 100, 101.0) is None


def test_failed_break_detects_failed_upside_break():
    scan = mk([(99, 100, 98, 99), (99, 101, 99, 100), (100, 102, 100, 101),
               (101, 101.5, 99, 100)])
    fb = st.failed_break(scan, 3, {'pdh': 100.0}, 99.9, 'BEAR')
    assert fb is not None
    assert fb['extreme'] >= 101.0
    assert fb['fail_idx'] <= 3


def test_derive_b0_and_no_trade_rows():
    scan = mk([(100, 101, 99, 100)] * 6)
    s = pit_signal(scan, 2, 3)
    b0 = st.derive(s, 100.0, 'B0')
    assert b0['stop_price'] == 100.5
    assert b0['inputs_max_idx'] <= s['trigger_idx']
    s4 = pit_signal(scan, 2, 3, level='R1')
    bad = st.derive(s4, 100.0, 'S4')
    assert bad['stop_price'] is None
    assert bad['rejection_reason']


def test_opens_model_books_gap_through_beyond_minus_one():
    scan = mk([(100, 101, 99, 100),
               (99, 99.5, 98, 98.5),
               (104, 105, 103, 104)])
    sim = ex.simulate('BEAR', 100.0, scan, 0, 101.0, 98.0, 'opens')
    assert sim['exit_reason'] == 'STOP'
    assert sim['realized_r'] < -1.0
    assert sim['stop_overshoot_pts'] > 0


def test_intrabar_model_is_conservative_on_ambiguous_bar():
    scan = mk([(100, 101, 99, 100),
               (100, 102, 101.0, 101.5)])
    sim = ex.simulate('BEAR', 100.0, scan, 0, 101.0, 98.0, 'intrabar')
    assert sim['exit_reason'] == 'STOP'
    assert sim['intrabar_ambiguous_bars'] >= 0
    assert sim['realized_r'] <= -1.0


def test_intrabar_stop_fill_does_not_invent_target_win():
    scan = mk([(100, 101, 99, 100),
               (100, 101.2, 99.9, 101.0),
               (101, 101.5, 100.5, 100.8)])
    sim = ex.simulate('BEAR', 100.0, scan, 0, 101.0, 98.0, 'intrabar')
    assert sim['exit_reason'] in ('STOP', 'EOD-1520')


def test_mae_before_first_profit():
    scan = mk([(100, 101, 98, 99), (99, 100, 97, 99.5)])
    out = ex.mae_before_first_profit('BEAR', 100.0, scan, 0, None)
    assert out['mae_before_first_profit_pts'] == 1.0
    assert out['bars_to_first_profit'] == 1
    scan2 = mk([(100, 100.5, 99, 100.5), (100.5, 100.8, 99.5, 99.8)])
    out2 = ex.mae_before_first_profit('BEAR', 100.0, scan2, 0, None)
    assert out2['mae_before_first_profit_pts'] == 0.8
    assert out2['bars_to_first_profit'] == 2


def test_records_build_marks_no_trade_and_keeps_schema():
    scan = mk([(100, 101, 99, 100)] * 6)
    s = pit_signal(scan, 2, 3, level='ABOVE_CPR')
    row = rc.build(s, 'S4')
    assert row['variant'] == 'S4'
    assert row['position_sizing'] is None
    assert 'not computed' in row['position_sizing_reason']
    assert row['no_trade'] is True
    assert row['rejection_reason']
    assert row['direction_label'] == 'NO TRADE'
    assert row['data_limitations'] and row['execution_limitations']


def test_records_build_valid_trade_has_two_models_and_target():
    scan = mk([(100, 101, 99, 100), (100, 101, 99, 100),
               (100, 101, 99, 100), (100.5, 101.5, 100, 101),
               (101, 102, 100.5, 101.5), (101.5, 102, 101, 101.5)] +
              [(101.5, 102, 101, 101.5)] * 4)
    s = pit_signal(scan, 2, 3)
    row = rc.build(s, 'B0')
    assert row['no_trade'] is False
    assert row['target_price'] == round(100.5 * 0.98, 4)
    assert row['realized_r'] is not None
    assert row['intrabar_realized_r'] is not None
    assert row['stop_distance_pts'] > 0
    assert row['no_lookahead_ok'] is True


def test_b0_versus_b0_fails_the_gates():
    scan = mk([(100, 101, 99, 100), (100, 101, 99, 100),
               (100, 101, 99, 100), (100.5, 101.5, 100, 101),
               (101, 102, 100.5, 101.5), (101.5, 102, 101, 101.5)] +
              [(101.5, 102, 101, 101.5)] * 4)
    s = pit_signal(scan, 2, 3)
    recs = []
    for d in ('2026-09-01', '2026-09-02', '2026-09-03'):
        sig = pit_signal(scan, 2, 3)
        sig['session_date'] = d
        r = rc.build(sig, 'B0')
        r = {**r, 'model': 'opens'}
        recs.append(r)
    ib = [{**r, 'model': 'intrabar', 'realized_r': r['intrabar_realized_r']}
          for r in recs]
    g = mx.evaluate('B0', {'B0': recs}, {'B0': ib},
                    ['2026-09-01', '2026-09-02', '2026-09-03'],
                    {'status': 'PASS', 'problems': []}, True, [])
    assert g['G-A_oos_improvement']['pass'] is False
    assert g['OVERALL'] in ('FAIL', 'INCONCLUSIVE')
    assert g['ELIGIBLE_FOR_HUMAN_REVIEW'] is False


def test_paired_helper_restricts_to_shared_signals():
    a = [{'signal_key': 'x', 'realized_r': 1.0}, {'signal_key': 'y', 'realized_r': 2.0}]
    b = [{'signal_key': 'x', 'realized_r': 0.5}]
    assert mx.paired(a, b) == [a[0]]
