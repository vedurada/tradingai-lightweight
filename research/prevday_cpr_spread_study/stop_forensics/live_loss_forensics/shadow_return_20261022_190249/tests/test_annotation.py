"""Unit tests for the shadow annotation engine.

The important one is test_annotation_is_causal(): the annotation of a setup
must not change when later bars are appended to the session, because the
annotation may only use information that was available at the time.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                '..', 'src'))

import annotation as A  # noqa: E402
import wconfig as C  # noqa: E402


def mk_bar(ts, o, h, l, c):
    return {'timestamp': ts, 'open': o, 'high': h, 'low': l, 'close': c}


def ts(i, start=9 * 60 + 15):
    """The timestamp of the i-th 5-minute bar of a session."""
    m = start + 5 * i
    return '2026-10-22T%02d:%02d:00+05:30' % (m // 60, m % 60)


def session(pattern):
    """Build a session from a list of (open, high, low, close) tuples."""
    return [mk_bar(ts(i), *p) for i, p in enumerate(pattern)]


def flat_session(n=40, price=100.0, drift=0.0):
    out = []
    p = price
    for i in range(n):
        o = p
        c = p + drift
        out.append(mk_bar(ts(i), o, max(o, c), min(o, c), c))
        p = c
    return out


LV = {'pp': 100.0, 'tc': 101.0, 'bc': 99.0, 'r1': 102.0, 's1': 98.0,
      'r2': 104.0, 's2': 96.0, 'pdh': 103.0, 'pdl': 97.0,
      'prev_close': 100.0}


# --------------------------------------------------------- family split ---
def test_family_classification():
    assert A.family_of('R1') == 'TOUCH'
    assert A.family_of('PDH') == 'TOUCH'
    assert A.family_of('S2') == 'TOUCH'
    assert A.family_of('BELOW_CPR') == 'BREAK'
    assert A.family_of('ABOVE_CPR') == 'BREAK'
    assert A.family_of('BRK_R1') == 'BREAKOUT'


# ---------------------------------------------------------- return test ---
def test_return_detected_in_the_first_touching_bar():
    bars = flat_session(5, 100.0)
    # bar 3 trades through R1 = 102
    bars[3] = mk_bar(ts(3), 101.0, 102.5, 100.8, 101.2)
    ann = A.annotate(bars, 0, LV, 'BEAR', 'R1', 'NIFTY')
    assert ann['return_observed'] is True
    assert ann['return_bars'] == 3
    assert ann['return_bar_ts'] == ts(3)
    assert ann['return_price'] == 102.0
    # the bar stamped 09:30 is only known at 09:35 (5 minutes later)
    assert ann['return_known_at'].startswith('2026-10-22T09:35')


def test_no_return_when_the_level_is_never_traded():
    bars = flat_session(20, 100.0)
    ann = A.annotate(bars, 0, LV, 'BEAR', 'R1', 'NIFTY')
    assert ann['return_observed'] is False
    assert ann['return_status'] == 'NOT_RETURNED'
    assert ann['filter_return_retained'] is False
    assert ann['filter_return_skip_reason'] == 'NO_RETURN_IN_12_BARS'


def test_return_window_is_twelve_completed_bars():
    # the level is touched for the first time in bar 13 -> outside the window
    bars = flat_session(30, 100.0)
    bars[13] = mk_bar(ts(13), 101.0, 102.5, 100.8, 101.2)
    ann = A.annotate(bars, 0, LV, 'BEAR', 'R1', 'NIFTY')
    assert ann['return_observed'] is False
    # the same touch in bar 12 (the 12th bar after the signal) is inside
    bars[12] = mk_bar(ts(12), 101.0, 102.5, 100.8, 101.2)
    ann = A.annotate(bars, 0, LV, 'BEAR', 'R1', 'NIFTY')
    assert ann['return_observed'] is True
    assert ann['return_bars'] == 12


def test_session_end_censors_a_negative_observation():
    bars = flat_session(6, 100.0)          # only 5 bars after the signal
    ann = A.annotate(bars, 0, LV, 'BEAR', 'R1', 'NIFTY')
    assert ann['window_complete'] is False
    assert ann['observation_status'] == 'CENSORED_SESSION_END'
    assert ann['return_status'] == 'CENSORED'
    assert ann['filter_return_skip_reason'] == 'CENSORED_SESSION_END'


def test_a_positive_observation_is_never_censored():
    bars = flat_session(6, 100.0)
    bars[2] = mk_bar(ts(2), 101.0, 102.5, 100.8, 101.2)
    ann = A.annotate(bars, 0, LV, 'BEAR', 'R1', 'NIFTY')
    assert ann['return_observed'] is True
    assert ann['observation_status'] == 'OK'


# ------------------------------------------------------ rejection rules ---
def test_rejection_rules():
    bear_tag = mk_bar(ts(1), 101.0, 102.5, 100.8, 101.2)   # tagged R1, closed below
    bear_hold = mk_bar(ts(1), 101.0, 102.5, 100.8, 102.4)  # closed above
    assert A.rejection_close(bear_tag, 102.0, 'BEAR') is True
    assert A.rejection_close(bear_hold, 102.0, 'BEAR') is False
    bull_tag = mk_bar(ts(1), 99.0, 99.2, 97.5, 98.8)        # tagged S1, closed above
    bull_break = mk_bar(ts(1), 99.0, 99.2, 97.5, 97.2)
    assert A.rejection_close(bull_tag, 98.0, 'BULL') is True
    assert A.rejection_close(bull_break, 98.0, 'BULL') is False


def test_below_cpr_rejection_is_the_retest_of_the_band_edge():
    # a BEAR below the CPR: the price comes back up to bc = 99 and closes below
    retest = mk_bar(ts(1), 98.5, 99.4, 98.4, 98.8)
    assert A.rejection_close(retest, 99.0, 'BEAR') is True
    # the V2-style rule fires on a failed breakdown instead
    failed = mk_bar(ts(1), 98.0, 98.4, 97.5, 99.4)
    assert A.rejection_close(failed, 99.0, 'BEAR') is False
    assert A.rejection_v2_style(failed, 99.0, 'BEAR', 'BELOW_CPR') is True
    assert A.rejection_v2_style(retest, 99.0, 'BEAR', 'BELOW_CPR') is False


def test_confirmation_is_found_after_the_return():
    bars = flat_session(20, 100.0)
    # the return bar closes back above the level -> it is not itself a rejection
    bars[2] = mk_bar(ts(2), 101.0, 102.5, 100.8, 102.4)
    bars[5] = mk_bar(ts(5), 101.0, 102.5, 100.8, 101.2)     # the rejection
    ann = A.annotate(bars, 0, LV, 'BEAR', 'R1', 'NIFTY')
    assert ann['return_bars'] == 2
    assert ann['rejection_at_or_after_return'] is True
    assert ann['rejection_at_return_bar'] is False
    assert ann['rejection_after_return'] is True
    assert ann['confirm_bars'] == 5
    assert ann['confirm_status'] == 'OBSERVED'
    assert ann['filter_confirm_retained'] is True


def test_confirmation_at_the_return_bar_counts():
    bars = flat_session(20, 100.0)
    bars[2] = mk_bar(ts(2), 101.0, 102.5, 100.8, 101.2)
    ann = A.annotate(bars, 0, LV, 'BEAR', 'R1', 'NIFTY')
    assert ann['rejection_at_return_bar'] is True
    assert ann['rejection_at_or_after_return'] is True
    assert ann['confirm_bars'] == 2


# ------------------------------------------------------------ causality ---
def test_annotation_is_causal():
    """Appending later bars must not change the annotation."""
    bars = flat_session(40, 100.0)
    bars[3] = mk_bar(ts(3), 101.0, 102.5, 100.8, 101.2)
    bars[7] = mk_bar(ts(7), 101.0, 102.5, 100.8, 101.2)
    full = A.annotate(bars, 0, LV, 'BEAR', 'R1', 'NIFTY')
    for cut in (13, 20, 30, 40):
        part = A.annotate(bars[:cut], 0, LV, 'BEAR', 'R1', 'NIFTY')
        assert part['return_observed'] == full['return_observed']
        assert part['return_bars'] == full['return_bars']
        assert part['rejection_at_or_after_return'] == \
            full['rejection_at_or_after_return']
        assert part['confirm_bars'] == full['confirm_bars']
        assert part['filter_return_retained'] == full['filter_return_retained']
        assert part['filter_confirm_retained'] == full['filter_confirm_retained']


def test_the_baseline_entry_is_the_next_open():
    bars = flat_session(75, 100.0)      # a full session (09:15..15:25)
    bars[0] = mk_bar(ts(0), 100.0, 100.5, 99.5, 100.2)
    bars[1] = mk_bar(ts(1), 100.3, 100.9, 100.1, 100.4)
    ann = A.annotate(bars, 0, LV, 'BEAR', 'R1', 'NIFTY')
    assert ann['baseline_entry'] == 100.3
    assert ann['baseline_entry_ts'].startswith('2026-10-22 09:20')


def test_entry_price_difference_sign_convention():
    """A positive difference means a better entry for the trade's direction.

    The counterfactual entry is the level itself (the wait-until-return
    entry); the reference is the immediate entry at the next open.
    """
    bars = flat_session(75, 100.0)
    bars[0] = mk_bar(ts(0), 103.0, 103.5, 102.5, 103.0)   # the trigger bar
    bars[1] = mk_bar(ts(1), 100.0, 100.5, 99.5, 100.0)    # the next open
    bear = A.annotate(bars, 0, LV, 'BEAR', 'R1', 'NIFTY')
    # a short entered at the level 102 is 2 points better than at 100
    assert bear['cf_entry_diff_pts'] == 2.0
    assert bear['cf_entry_diff_pts_raw'] == 2.0
    bull = A.annotate(bars, 0, LV, 'BULL', 'R1', 'NIFTY')
    # a long entered at 102 is 2 points worse than at 100
    assert bull['cf_entry_diff_pts'] == -2.0


def test_excursion_is_direction_aware():
    bars = flat_session(10, 100.0)
    bars[3] = mk_bar(ts(3), 100.0, 110.0, 99.0, 109.0)
    bear = A.annotate(bars, 0, LV, 'BEAR', 'R1', 'NIFTY')
    assert bear['mae_pts_from_signal'] == 10.0    # the high is adverse for a short
    assert bear['mfe_pts_from_signal'] == 1.0    # the low is favourable
    bull = A.annotate(bars, 0, LV, 'BULL', 'S1', 'NIFTY')
    assert bull['mae_pts_from_signal'] == 1.0
    assert bull['mfe_pts_from_signal'] == 10.0


def test_window_length_constant():
    assert C.RETURN_WINDOW_BARS == 12
    assert C.TOUCH_LEVELS == ('R1', 'R2', 'PDH', 'S1', 'S2', 'PDL')
    assert C.BREAK_LEVELS == ('BELOW_CPR', 'ABOVE_CPR')
