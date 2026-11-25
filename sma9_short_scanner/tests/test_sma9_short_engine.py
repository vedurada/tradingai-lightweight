#!/usr/bin/env python3
"""Unit tests for the sma9_short paper SHORT engine."""

import os
import sys
import unittest
from datetime import datetime, time as dtime, timedelta
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for candidate in (os.path.join(ROOT, "app"), os.path.join(ROOT, "deploy", "app")):
    if os.path.isdir(candidate):
        sys.path.insert(0, candidate)
        break

from sma9_short_engine import (  # noqa: E402
    ATR_MULTIPLIER,
    ATR_PERIOD,
    EOD_EXIT_TIME,
    STOP_LOSS_REASON,
    OptionStateMachine,
    eod_bar_open,
    evaluate_option,
    premium_atr,
)

IST = ZoneInfo("Asia/Kolkata")


def ts(h, m, s=0, day=25):
    return datetime(2026, 11, day, h, m, s, tzinfo=IST)


def candles(closes, open_price):
    """Completed 5m bars followed by one forming bar."""
    assert len(closes) >= 9
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
    forming = start + timedelta(minutes=5 * len(closes))
    rows.append({
        "start": forming, "open": open_price, "high": open_price + 1,
        "low": open_price - 1, "close": open_price, "volume": 500,
    })
    return rows


class TestSma9ShortEngine(unittest.TestCase):
    def setUp(self):
        self.rows = candles([100] * 15, 100)
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
        self.assertEqual(ce_pos.atr_distance, 1.4)
        self.assertEqual(ce_pos.initial_stop, 99.4)

    def test_atr_distance_has_no_percentage_floor_or_cap(self):
        self.assertEqual(ATR_PERIOD, 14)
        self.assertEqual(ATR_MULTIPLIER, 0.70)
        self.assertEqual(STOP_LOSS_REASON, "STOP_LOSS_ATR")
        self.assertEqual(premium_atr(self.rows), 2.0)
        ev = evaluate_option(self.rows, "CE", ltp=98)
        self.assertEqual(ev.atr, 2.0)
        self.assertEqual(ev.atr_distance, 1.4)

    def test_no_atr_blocks_entry(self):
        short_history = candles([100] * 9, 100)
        self.assertIsNone(premium_atr(short_history))
        ev = evaluate_option(short_history, "CE", ltp=98)
        self.assertFalse(ev.signal)
        self.assertIsNone(ev.atr_distance)
        self.assertIn("ATR", ev.reason)
        state = OptionStateMachine("CE")
        pos = state.try_entry(ev, self.now, 25550, "2026-12-22", 1,
                              "NIFTY26D2225550CE", self.market_close)
        self.assertIsNone(pos)

    def test_trailing_stop_uses_frozen_atr_distance(self):
        state = OptionStateMachine("PE")
        ev = evaluate_option(self.rows, "PE", ltp=99)
        pos = state.try_entry(ev, self.now, 25150, "2026-12-22", 2,
                              "NIFTY26D2225150PE", self.market_close)
        self.assertEqual(pos.stop, 100.4)

        state.update_trail(90)
        self.assertEqual(pos.lowest_ltp, 90)
        self.assertEqual(pos.stop, 91.4)

        state.update_trail(95)   # higher low: stop must not loosen
        self.assertEqual(pos.stop, 91.4)

        state.update_trail(80)
        self.assertEqual(pos.lowest_ltp, 80)
        self.assertEqual(pos.stop, 81.4)

        self.assertTrue(pos.trailing_active())
        self.assertEqual(state.check_stop_loss(81.5), 81.4)
        self.assertIsNone(state.check_stop_loss(81.3))

    def test_short_pnl_sign(self):
        state = OptionStateMachine("CE")
        ev = evaluate_option(self.rows, "CE", ltp=99)
        state.try_entry(ev, self.now, 25550, "2026-12-22", 1,
                        "NIFTY26D2225550CE", self.market_close)
        trade = state.close(ts(11, 0), 90, "TRAIL_STOP_EXIT")
        self.assertEqual(trade["pnl_points"], 9.0)
        trade = state.close(ts(11, 0), 110, STOP_LOSS_REASON)
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

    def test_eod_exit_due_at_1520(self):
        state = OptionStateMachine("CE")
        self.assertFalse(state.needs_exit(ts(15, 19, 59)))
        self.assertTrue(state.needs_exit(ts(15, 20, 0)))
        self.assertTrue(state.needs_exit(ts(15, 30, 0)))
        self.assertEqual(EOD_EXIT_TIME, dtime(15, 20))

    def test_eod_flat_close(self):
        state = OptionStateMachine("PE")
        ev = evaluate_option(self.rows, "PE", ltp=99)
        state.try_entry(ev, self.now, 25150, "2026-12-22", 2,
                        "NIFTY26D2225150PE", self.market_close)
        trade = state.close(ts(15, 20), 96.5, "EOD_15_20_FLAT")
        self.assertEqual(trade["exit_reason"], "EOD_15_20_FLAT")
        self.assertEqual(trade["exit_price"], 96.5)
        self.assertEqual(trade["pnl_points"], 2.5)

    def test_eod_bar_open_fallback(self):
        rows = self.rows + [
            {"start": ts(15, 15), "open": 101, "high": 102, "low": 100,
             "close": 101, "volume": 1},
            {"start": ts(15, 20), "open": 97.5, "high": 99, "low": 96,
             "close": 97, "volume": 1},
        ]
        self.assertEqual(eod_bar_open(rows, ts(15, 20)), 97.5)
        self.assertIsNone(eod_bar_open(self.rows, ts(15, 20)))


if __name__ == "__main__":
    unittest.main()
