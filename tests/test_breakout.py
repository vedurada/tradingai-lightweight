"""Unit tests for the breakout add-on (fresh close-cross) — pure, no DB I/O."""
import sys
sys.path.insert(0, '/opt/tradingai')

from app.research.cpr_trigger_engine import (
    day_levels, BREAKOUT_ADDON, breakout_trigger, breakout_signal, book_scan)
from app.live.engine import _frozen_trade_passes_gate


def lv():
    # prev H=100, L=90, C=92 -> pp=94, tc=95, bc=93, r1=98, s1=88, r2=104,
    # s2=84, pdh=100, pdl=90
    return day_levels(100, 90, 92)


def C(o, h, l, cl, ts='t'):
    return {'timestamp': ts, 'open': o, 'high': h, 'low': l, 'close': cl}


def test_addon_enabled():
    assert BREAKOUT_ADDON is True


def test_up_break_is_bull():
    # close crosses up through r1=98 (prev close 97 -> 99)
    assert breakout_trigger(C(98, 99.5, 97.9, 99.0), 97.0, lv()) == ('BULL', 'BRK_R1')


def test_down_break_is_bear():
    # close crosses down through s1=88 (prev close 89 -> 87)
    assert breakout_trigger(C(88.5, 88.6, 86.9, 87.0), 89.0, lv()) == ('BEAR', 'BRK_S1')


def test_touch_without_break_does_not_fire():
    # high pokes r1 but the close stays below -> no breakout (that is the base
    # bear reject, not a breakout).
    assert breakout_trigger(C(96, 98.5, 95.5, 97.0), 96.0, lv()) is None


def test_no_prev_close_none():
    assert breakout_trigger(C(98, 99.5, 97.9, 99.0), None, lv()) is None
    assert breakout_trigger(C(98, 99.5, 97.9, 99.0), 97.0, {}) is None


def test_breakout_signal_first_cross_wins():
    cs = [C(95, 96, 94, 95.5, 't1'),      # no cross
          C(96, 97, 95, 96.5, 't2'),      # no cross
          C(97, 99, 96, 98.5, 't3'),      # crosses r1=98 -> BULL BRK_R1
          C(99, 105, 99, 104.5, 't4')]    # would cross r2 but later
    assert breakout_signal(cs, lv(), None, 'plain') == ('BULL', 'BRK_R1', 2)


def test_book_scan_falls_back_to_breakout_on_flat_session():
    # A TC break (CPR top) with high below R1: no base bear reject, no CPR
    # close-break -> book_scan falls back to the breakout (BULL BRK_TC).
    cs = [C(94, 94.8, 93.5, 94.5, '2026-10-14T09:15:00+05:30'),
          C(94.5, 95.5, 94.3, 95.5, '2026-10-14T09:20:00+05:30')]
    sig = book_scan(cs, lv(), None, 'plain')
    assert sig is not None and sig[0] == 'BULL' and sig[1] == 'BRK_TC'


def test_book_scan_base_trigger_wins_over_breakout():
    # A base BEAR touch (R1 reject) fires before any breakout fallback.
    cs = [C(97, 98.5, 96.5, 96.8, '2026-10-14T09:15:00+05:30')]
    sig = book_scan(cs, lv(), None, 'plain')
    assert sig is not None and sig[0] == 'BEAR' and sig[1] == 'R1'


FRI = '2026-10-16'   # a Friday


def test_friday_base_bear_falls_through_to_breakout_bull():
    # Friday: base hits R1 (a BEAR that SKIP_FRIDAY drops), so the session is
    # flat. The up-break through R1 later that day fires as a BULL add-on.
    cs = [C(97, 98.5, 96.5, 97.5, FRI + 'T09:15:00+05:30'),
          C(98, 99.5, 97.8, 99.0, FRI + 'T09:20:00+05:30')]
    sig = book_scan(cs, lv(), None, 'plain')
    assert sig is not None and sig[0] == 'BULL' and sig[1] == 'BRK_R1'


def test_friday_breakout_bear_still_skipped():
    # Friday: base BELOW_CPR is skipped AND the fresh down-cross is a BEAR
    # breakout, which SKIP_FRIDAY also drops -> no signal.
    cs = [C(92.6, 92.7, 92.3, 92.5, FRI + 'T09:15:00+05:30'),
          C(92.5, 92.6, 86.8, 87.0, FRI + 'T09:20:00+05:30')]
    assert book_scan(cs, lv(), None, 'plain') is None


def test_frozen_gate_allows_breakout_bull():
    MON = '2026-10-19'
    brk = {'direction': 'BULL', 'scenario': 'BRK_R1'}
    assert _frozen_trade_passes_gate(brk, MON) is True
    # Confirmed support BULL passes; CPR continuation BULL stays gated.
    assert _frozen_trade_passes_gate({'direction': 'BULL', 'scenario': 'S1'}, MON) is True
    assert _frozen_trade_passes_gate({'direction': 'BULL', 'scenario': 'ABOVE_CPR'}, MON) is False
