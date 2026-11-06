#!/usr/bin/env python3
"""12 mandatory SMA9 BUY-only test scenarios (synthetic fixtures only)."""

import os
import sys
import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

CODE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if CODE_ROOT not in sys.path:
    sys.path.insert(0, CODE_ROOT)

from app.sma9_engine import (  # noqa: E402
    OptionStateMachine,
    Position,
    evaluate_option,
    candle_end,
)

IST = ZoneInfo("Asia/Kolkata")


def ts(h, m, s=0, day=6):
    return datetime(2026, 11, day, h, m, s, tzinfo=IST)


def make_candles(completed_closes, current_open, start=None):
    """Build 9 completed candles + one forming candle.

    ``completed_closes`` must be exactly 9 closes.  Each candle opens at the
    prior close (or at the first close for the first candle).
    """
    assert len(completed_closes) == 9
    start = start or ts(10, 0)
    rows = []
    prev = completed_closes[0]
    for i, close in enumerate(completed_closes):
        cstart = start + timedelta(minutes=5 * i)
        rows.append({
            "start": cstart,
            "open": prev,
            "high": max(prev, close) + 1,
            "low": min(prev, close) - 1,
            "close": close,
            "volume": 1000,
        })
        prev = close
    forming_start = start + timedelta(minutes=45)
    rows.append({
        "start": forming_start,
        "open": current_open,
        "high": current_open + 1,
        "low": current_open - 1,
        "close": current_open,  # ignored by SMA9
        "volume": 500,
    })
    return rows


def sma9_of(closes):
    return sum(closes) / 9.0


class TestSma9BuyOnly(unittest.TestCase):
    def setUp(self):
        self.market_close = ts(15, 30)

    # 1 -----------------------------------------------------------------
    def test_01_ce_only(self):
        # CE qualifies: prev close 110 > SMA9, forming open 111 > SMA9.
        ce = make_candles([100] * 8 + [110], 111)
        # PE does not: prev close 90 < SMA9, forming open 89 < SMA9.
        pe = make_candles([100] * 8 + [90], 89)
        ce_ev = evaluate_option(ce, "CE", ltp=112)
        pe_ev = evaluate_option(pe, "PE", ltp=88)
        self.assertTrue(ce_ev.signal)
        self.assertFalse(pe_ev.signal)
        self.assertEqual(ce_ev.option_type, "CE")

    # 2 -----------------------------------------------------------------
    def test_02_pe_only(self):
        pe = make_candles([100] * 8 + [110], 111)
        ce = make_candles([100] * 8 + [90], 89)
        pe_ev = evaluate_option(pe, "PE", ltp=112)
        ce_ev = evaluate_option(ce, "CE", ltp=88)
        self.assertTrue(pe_ev.signal)
        self.assertFalse(ce_ev.signal)

    # 3 -----------------------------------------------------------------
    def test_03_both_simultaneously(self):
        ce = make_candles([100] * 8 + [110], 111)
        pe = make_candles([100] * 8 + [110], 111)
        ce_ev = evaluate_option(ce, "CE", ltp=112)
        pe_ev = evaluate_option(pe, "PE", ltp=112)
        self.assertTrue(ce_ev.signal)
        self.assertTrue(pe_ev.signal)
        ce_state = OptionStateMachine("CE")
        pe_state = OptionStateMachine("PE")
        now = ts(10, 46)
        ce_pos = ce_state.try_entry(ce_ev, now, 24850, "2026-11-09", 1,
                                    "CE-SYM", self.market_close)
        pe_pos = pe_state.try_entry(pe_ev, now, 24850, "2026-11-09", 2,
                                    "PE-SYM", self.market_close)
        self.assertIsNotNone(ce_pos)
        self.assertIsNotNone(pe_pos)
        self.assertEqual(ce_state.position.option_type, "CE")
        self.assertEqual(pe_state.position.option_type, "PE")

    # 4 -----------------------------------------------------------------
    def test_04_prev_close_above_current_open_below(self):
        closes = [100] * 8 + [110]
        sma = sma9_of(closes)
        candles = make_candles(closes, current_open=sma - 5)
        ev = evaluate_option(candles, "CE", ltp=sma + 1)
        self.assertTrue(ev.condition_a)
        self.assertFalse(ev.condition_b)
        self.assertTrue(ev.qualified)
        self.assertTrue(ev.signal)

    # 5 -----------------------------------------------------------------
    def test_05_prev_close_below_current_open_above(self):
        closes = [100] * 8 + [99]
        sma = sma9_of(closes)
        candles = make_candles(closes, current_open=sma + 5)
        ev = evaluate_option(candles, "PE", ltp=sma + 6)
        self.assertFalse(ev.condition_a)
        self.assertTrue(ev.condition_b)
        self.assertTrue(ev.qualified)
        self.assertTrue(ev.signal)

    # 6 -----------------------------------------------------------------
    def test_06_both_false(self):
        closes = [100] * 8 + [99]
        sma = sma9_of(closes)
        candles = make_candles(closes, current_open=sma - 1)
        ev = evaluate_option(candles, "CE", ltp=sma + 10)
        self.assertFalse(ev.condition_a)
        self.assertFalse(ev.condition_b)
        self.assertFalse(ev.qualified)
        self.assertFalse(ev.signal)

    # 7 -----------------------------------------------------------------
    def test_07_qualified_but_ltp_below_sma9(self):
        closes = [100] * 8 + [110]
        sma = sma9_of(closes)
        candles = make_candles(closes, current_open=sma + 1)
        ev = evaluate_option(candles, "CE", ltp=sma - 0.5)
        self.assertTrue(ev.qualified)
        self.assertFalse(ev.confirmation)
        self.assertFalse(ev.signal)

    # 8 -----------------------------------------------------------------
    def test_08_qualified_and_ltp_above_sma9(self):
        closes = [100] * 8 + [110]
        sma = sma9_of(closes)
        candles = make_candles(closes, current_open=sma + 1)
        ev = evaluate_option(candles, "CE", ltp=sma + 0.5)
        self.assertTrue(ev.qualified)
        self.assertTrue(ev.confirmation)
        self.assertTrue(ev.signal)

    # 9 -----------------------------------------------------------------
    def test_09_duplicate_polling_one_entry_per_candle(self):
        closes = [100] * 8 + [110]
        candles = make_candles(closes, 111)
        ev = evaluate_option(candles, "CE", ltp=112)
        state = OptionStateMachine("CE")
        now = ts(10, 46)
        p1 = state.try_entry(ev, now, 24850, "2026-11-09", 1, "CE-SYM",
                             self.market_close)
        p2 = state.try_entry(ev, now + timedelta(seconds=5), 24850, "2026-11-09",
                             1, "CE-SYM", self.market_close)
        self.assertIsNotNone(p1)
        self.assertIsNone(p2)  # already in position
        # After closing, a repeated poll in the SAME candle must not re-enter.
        state.close(candle_end(ev.candle_start), 115)
        p3 = state.try_entry(ev, now + timedelta(seconds=10), 24850,
                             "2026-11-09", 1, "CE-SYM", self.market_close)
        self.assertIsNone(p3)

    # 10 ----------------------------------------------------------------
    def test_10_entry_in_final_minute(self):
        closes = [100] * 8 + [110]
        # 15:25 candle ends exactly at 15:30 -> allowed.
        candles = make_candles(closes, 111, start=ts(14, 40))
        ev = evaluate_option(candles, "CE", ltp=112)
        self.assertEqual(ev.candle_end.time().strftime("%H:%M"), "15:30")
        state = OptionStateMachine("CE")
        pos = state.try_entry(ev, ts(15, 29, 30), 24850, "2026-11-09", 1,
                              "CE-SYM", self.market_close)
        self.assertIsNotNone(pos)
        # 15:30 candle ends at 15:35 -> rejected.
        candles2 = make_candles(closes, 111, start=ts(14, 45))
        ev2 = evaluate_option(candles2, "CE", ltp=112)
        self.assertEqual(ev2.candle_end.time().strftime("%H:%M"), "15:35")
        state2 = OptionStateMachine("CE")
        pos2 = state2.try_entry(ev2, ts(15, 30), 24850, "2026-11-09", 1,
                                "CE-SYM", self.market_close)
        self.assertIsNone(pos2)

    # 11 ----------------------------------------------------------------
    def test_11_exit_at_candle_boundary(self):
        closes = [100] * 8 + [110]
        candles = make_candles(closes, 111, start=ts(10, 0))
        ev = evaluate_option(candles, "CE", ltp=112)
        state = OptionStateMachine("CE")
        pos = state.try_entry(ev, ts(10, 46), 24850, "2026-11-09", 1,
                              "CE-SYM", self.market_close)
        self.assertFalse(state.needs_exit(ts(10, 49, 59)))
        self.assertTrue(state.needs_exit(ts(10, 50, 0)))
        trade = state.close(pos.entry_candle_end, 120.0)
        self.assertEqual(trade["exit_timestamp"], pos.entry_candle_end.isoformat())
        self.assertEqual(trade["exit_price"], 120.0)
        self.assertEqual(trade["pnl_points"], round(120.0 - pos.entry_price, 2))
        self.assertEqual(trade["exit_reason"], "SAME_CANDLE_EXIT")
        self.assertIsNone(state.position)

    # 12 ----------------------------------------------------------------
    def test_12_restart_with_open_position(self):
        closes = [100] * 8 + [110]
        candles = make_candles(closes, 111, start=ts(10, 0))
        ev = evaluate_option(candles, "CE", ltp=112)
        state = OptionStateMachine("CE")
        pos = state.try_entry(ev, ts(10, 46), 24850, "2026-11-09", 1,
                              "CE-SYM", self.market_close)
        payload = pos.as_dict()
        restored = Position.from_dict(payload)
        new_state = OptionStateMachine("CE")
        new_state.restore(restored)
        self.assertIsNotNone(new_state.position)
        self.assertFalse(new_state.needs_exit(ts(10, 49, 0)))
        self.assertTrue(new_state.needs_exit(ts(10, 50, 0)))
        trade = new_state.close(restored.entry_candle_end, 118.0)
        self.assertEqual(trade["trade_id"], pos.trade_id)
        self.assertEqual(trade["pnl_points"], round(118.0 - pos.entry_price, 2))

    # Extra: no look-ahead from the forming candle's close -------------
    def test_13_forming_candle_close_is_ignored(self):
        closes = [100] * 9
        candles = make_candles(closes, current_open=101)
        ev1 = evaluate_option(candles, "CE", ltp=102)
        # Change only the forming candle close; SMA9 must not change.
        candles[-1]["close"] = 9999
        ev2 = evaluate_option(candles, "CE", ltp=102)
        self.assertEqual(ev1.sma9, ev2.sma9)
        self.assertAlmostEqual(ev1.sma9, 100.0)

    # Extra: PE uses BUY arithmetic, never short arithmetic -------------
    def test_14_pe_pnl_is_buy_only(self):
        closes = [100] * 8 + [110]
        candles = make_candles(closes, 111)
        ev = evaluate_option(candles, "PE", ltp=112)
        state = OptionStateMachine("PE")
        pos = state.try_entry(ev, ts(10, 46), 24850, "2026-11-09", 2,
                              "PE-SYM", self.market_close)
        trade = state.close(pos.entry_candle_end, 120.0)
        # BUY: +8, not short -8
        self.assertEqual(trade["pnl_points"], round(120.0 - 112.0, 2))


if __name__ == "__main__":
    unittest.main(verbosity=2)
