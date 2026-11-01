"""Unit tests for the wait-for-setup entry variants."""
import copy
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src'))

import variants as V  # noqa: E402

LV = {'r1': 100.0, 'r2': 105.0, 'pdh': 98.0, 'bc': 95.0, 'tc': 110.0,
      's1': 90.0, 's2': 85.0, 'pdl': 80.0}


def bar(ts, o, h, l, c):
    return {'timestamp': ts, 'open': o, 'high': h, 'low': l, 'close': c}


def session():
    return [
        bar('2026-07-07T09:15:00+05:30', 99.0, 100.5, 98.5, 100.0),   # trigger bar (i=0)
        bar('2026-07-07T09:20:00+05:30', 100.0, 100.2, 99.0, 99.5),
        bar('2026-07-07T09:25:00+05:30', 99.0, 99.2, 98.0, 98.2),     # tags R1=100? no: below
        bar('2026-07-07T15:20:00+05:30', 98.0, 98.1, 97.9, 98.0),
    ]


def test_v1_fills_at_the_level_when_the_range_covers_it():
    cs = session()
    got = V.v1_wait_setup(cs, 0, LV, 'BEAR', 'R1')
    assert got['status'] == 'ENTERED'
    assert got['entry'] == 100.0
    assert got['entry_idx'] == 2 or got['entry_idx'] == 1


def test_v1_expires_when_the_level_is_never_retested():
    cs = [bar('2026-07-07T09:15:00+05:30', 99.0, 99.5, 98.5, 99.0),
          bar('2026-07-07T09:20:00+05:30', 97.0, 97.5, 96.0, 96.5)]
    got = V.v1_wait_setup(cs, 0, LV, 'BEAR', 'R1')
    assert got['status'] == 'EXPIRED'


def test_v1_no_level_price_is_refused():
    got = V.v1_wait_setup(session(), 0, LV, 'BEAR', 'UNKNOWN_LEVEL')
    assert got['status'] == 'NO_LEVEL'


def test_v1x_has_no_expiry_but_still_respects_the_entry_window():
    cs = session()
    got = V.v1x_wait_setup_no_expiry(cs, 0, LV, 'BEAR', 'R1')
    assert got['status'] in ('ENTERED', 'NO_SETUP')


def test_v2_waits_for_a_rejection_close_then_enters_at_the_next_open():
    cs = [
        bar('2026-07-07T09:15:00+05:30', 99.0, 100.5, 98.5, 100.0),   # trigger (R1 touched)
        bar('2026-07-07T09:20:00+05:30', 100.0, 100.3, 99.5, 99.6),   # tags R1, closes below -> reject
        bar('2026-07-07T09:25:00+05:30', 99.0, 99.4, 98.8, 99.2),    # the fill bar (next open)
        bar('2026-07-07T15:20:00+05:30', 98.0, 98.1, 97.9, 98.0),
    ]
    got = V.v2_wait_confirm(cs, 0, LV, 'BEAR', 'R1')
    assert got['status'] == 'ENTERED'
    assert got['entry_idx'] == 2
    assert got['entry'] == 99.0


def test_v2_breakdown_needs_a_close_back_above_the_band():
    cs = [
        bar('2026-07-07T09:15:00+05:30', 96.0, 96.2, 94.0, 94.5),   # trigger: close < bc(95)
        bar('2026-07-07T09:20:00+05:30', 94.0, 95.4, 93.8, 95.2),   # traded below, closed back above
        bar('2026-07-07T09:25:00+05:30', 95.0, 95.3, 94.9, 95.1),
        bar('2026-07-07T15:20:00+05:30', 94.0, 94.2, 93.9, 94.0),
    ]
    got = V.v2_wait_confirm(cs, 0, LV, 'BEAR', 'BELOW_CPR')
    assert got['status'] == 'ENTERED'
    assert got['entry_idx'] == 2


def test_v3_needs_a_retest_after_the_confirmation():
    cs = [
        bar('2026-07-07T09:15:00+05:30', 99.0, 100.5, 98.5, 100.0),
        bar('2026-07-07T09:20:00+05:30', 100.0, 100.3, 99.5, 99.6),   # rejection close
        bar('2026-07-07T09:25:00+05:30', 99.6, 100.1, 99.5, 100.0),   # retest: the range covers R1
        bar('2026-07-07T15:20:00+05:30', 98.0, 98.1, 97.9, 98.0),
    ]
    got = V.v3_wait_confirm_retest(cs, 0, LV, 'BEAR', 'R1')
    assert got['status'] == 'ENTERED'
    assert got['entry'] == 100.0


def test_v3_reports_no_retest():
    cs = [
        bar('2026-07-07T09:15:00+05:30', 99.0, 100.5, 98.5, 100.0),
        bar('2026-07-07T09:20:00+05:30', 100.0, 100.3, 99.5, 99.6),
        bar('2026-07-07T09:25:00+05:30', 99.0, 99.2, 98.0, 98.2),     # never back to R1
        bar('2026-07-07T15:20:00+05:30', 98.0, 98.1, 97.9, 98.0),
    ]
    got = V.v3_wait_confirm_retest(cs, 0, LV, 'BEAR', 'R1')
    assert got['status'] == 'NO_RETEST'


def test_v4_no_chase_flip_can_flip_the_direction():
    cs = [
        bar('2026-07-07T09:15:00+05:30', 99.0, 100.5, 98.5, 100.0),
        bar('2026-07-07T09:20:00+05:30', 90.5, 91.0, 90.0, 90.5),     # opens at S1=90
        bar('2026-07-07T15:20:00+05:30', 89.0, 89.2, 88.9, 89.0),
    ]
    got = V.v4_no_chase_flip(cs, 0, LV, 'BEAR', 'R1')
    assert got['status'] == 'ENTERED'
    assert got['direction'] == 'BULL'


def test_variants_do_not_look_ahead():
    """Mutating the candles after the fill must not change the entry."""
    cs = [
        bar('2026-07-07T09:15:00+05:30', 99.0, 100.5, 98.5, 100.0),
        bar('2026-07-07T09:20:00+05:30', 100.0, 100.3, 99.5, 99.6),
        bar('2026-07-07T09:25:00+05:30', 99.6, 100.1, 99.5, 100.0),
        bar('2026-07-07T15:20:00+05:30', 98.0, 98.1, 97.9, 98.0),
    ]
    a = V.v3_wait_confirm_retest(cs, 0, LV, 'BEAR', 'R1')
    mutated = copy.deepcopy(cs)
    mutated[3]['open'] = 1.0
    mutated[3]['high'] = 2.0
    mutated[3]['low'] = 0.5
    mutated[3]['close'] = 1.5
    b = V.v3_wait_confirm_retest(mutated, 0, LV, 'BEAR', 'R1')
    assert a['entry_idx'] == b['entry_idx'] and a['entry'] == b['entry']
