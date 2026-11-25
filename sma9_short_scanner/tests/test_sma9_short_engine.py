#!/usr/bin/env python3
"""Unit tests for the sma9_short paper SHORT engine."""

import os
import sys
import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for candidate in (os.path.join(ROOT, "app"), os.path.join(ROOT, "deploy", "app")):
    if os.path.isdir(candidate):
        sys.path.insert(0, candidate)
        break

from sma9_short_engine import (  # noqa: E402
    OptionStateMachine,
    evaluate_option,
)

IST = ZoneInfo("Asia/Kolkata")


def ts(h, m, s=0, day=25):
    return datetime(2026, 11, day, h, m, s, tzinfo=IST)


def candles(closes, open_price):
    """Nine completed closes then one forming bar."""
    assert len(closes) == 9
    start = ts(10, 0)
    rows = []
    prev = closes[0]
    for i, close in enumerate(closes):
        s = start + timedelta(minutes=5 * i)
        rows.append({
            "start": s, "open": prev, "high": max(prev, close) + 1,
            "low": min(prev, close) - 1, "close": close, "volume": 1000,
        })
        prev = close
    forming = start + timedelta(minutes=45)
    rows.append({
        "start": forming, "open": open_price, "high": open_price + 1,
        "low": open_price - 1, "close": open_price, "volume": 500,
    })
    return rows


class TestSma9ShortEngine(unittest.TestCase):
    def setUp(self):
        self.rows = candles([100] * 9, 100)
        self.sma = 100.0
        self.market_close = ts(15, 30)
        self.now = ts(10, 45, 5)

    def test_entry_only_below_sma(self):
        below = evaluate_option(self.rows, "CE", ltp=98)
        at = evaluate_option(self.rows, "CE", ltp=100)
        above = evaluate_option(self.rows, "CE", ltp=102)
        self.assertTrue(below.signal)
        self.assertFalse(at.signal)
        self.assertFalse(above.signal)

    def test_each_leg_can_open_independently(self):
        ce = OptionStateMachine("CE")
        pe = OptionStateMachine("PE")
        ce_ev = evaluate_option(self.rows, "CE", ltp=98)
        pe_ev = evaluate_option(self.rows, "PE", ltp=101)
        ce_pos = ce.try_entry(ce_ev, self.now, 25550, "2026-12-22", 1,
                              "NIFTY26D2225550CE", self.market_close)
        pe_pos = pe.try_entry(pe_ev, self.now, 25150, "2026-12-22", 2,
                              "NIFTY26D2225150PE", self.market_close)
        self.assertIsNotNone(ce_pos)
        self.assertIsNone(pe_pos)
        self.assertEqual(ce_pos.entry_price, 98.0)
        self.assertEqual(ce_pos.initial_stop, 107.8)

    def test_trailing_stop_ratchets_down_only(self):
        state = OptionStateMachine("PE")
        ev = evaluate_option(self.rows, "PE", ltp=99)
        pos = state.try_entry(ev, self.now, 25150, "2026-12-22", 2,
                              "NIFTY26D2225150PE", self.market_close)
        self.assertEqual(pos.stop, 108.9)

        state.update_trail(90)
        self.assertEqual(pos.lowest_ltp, 90)
        self.assertEqual(pos.stop, 99.0)

        state.update_trail(95)   # higher low: stop must not loosen
        self.assertEqual(pos.stop, 99.0)

        state.update_trail(80)
        self.assertEqual(pos.lowest_ltp, 80)
        self.assertEqual(pos.stop, 88.0)

        self.assertTrue(pos.trailing_active())
        self.assertEqual(state.check_stop_loss(88.5), 88.0)
        self.assertIsNone(state.check_stop_loss(87.5))

    def test_short_pnl_sign(self):
        state = OptionStateMachine("CE")
        ev = evaluate_option(self.rows, "CE", ltp=99)
        state.try_entry(ev, self.now, 25550, "2026-12-22", 1,
                        "NIFTY26D2225550CE", self.market_close)
        trade = state.close(ts(11, 0), 90, "TRAIL_STOP_EXIT")
        self.assertEqual(trade["pnl_points"], 9.0)
        trade = state.close(ts(11, 0), 110, "STOP_LOSS_10PCT")
        self.assertIsNone(trade)  # position already closed

    def test_one_entry_per_candle(self):
        state = OptionStateMachine("CE")
        ev = evaluate_option(self.rows, "CE", ltp=98)
        first = state.try_entry(ev, self.now, 25550, "2026-12-22", 1,
                                "NIFTY26D2225550CE", self.market_close)
        second = state.try_entry(ev, self.now, 25550, "2026-12-22", 1,
                                 "NIFTY26D2225550CE", self.market_close)
        self.assertIsNotNone(first)
        self.assertIsNone(second)


if __name__ == "__main__":
    unittest.main()
