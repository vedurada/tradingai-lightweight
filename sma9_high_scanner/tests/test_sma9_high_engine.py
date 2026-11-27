#!/usr/bin/env python3
"""Mandatory SMA9 HIGH BUY-only test scenarios (synthetic fixtures only)."""

import os
import sys
import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

CODE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if CODE_ROOT not in sys.path:
    sys.path.insert(0, CODE_ROOT)

from app.sma9_high_engine import (  # noqa: E402
    LEGACY_EXIT_POLICY,
    SMA_PERIOD,
    OptionStateMachine,
    Position,
    candle_end,
    evaluate_option,
)

IST = ZoneInfo("Asia/Kolkata")


def ts(h, m, s=0, day=6):
    return datetime(2026, 11, day, h, m, s, tzinfo=IST)


def make_candles(closes, current_open, prev_high=None, start=None):
    """Build SMA_PERIOD completed candles + one forming candle."""
    assert len(closes) == SMA_PERIOD
    start = start or ts(10, 0)
    rows = []
    prev = closes[0]
    for i, close in enumerate(closes):
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
    if prev_high is not None:
        rows[-1]["high"] = prev_high
    forming_start = start + timedelta(minutes=5 * SMA_PERIOD)
    rows.append({
        "start": forming_start,
        "open": current_open,
        "high": current_open + 50,
        "low": current_open - 50,
        "close": current_open,  # ignored
        "volume": 500,
    })
    return rows


def flat(value=100.0):
    return [value] * SMA_PERIOD


def rising(value=100.0):
    """Completed closes whose last close is above the SMA."""
    return [value - 1.0] + [value] * (SMA_PERIOD - 2) + [value + 1.0]


def sma_of(closes):
    return sum(closes) / float(SMA_PERIOD)


class TestSma9HighBuyOnly(unittest.TestCase):
    def setUp(self):
        self.market_close = ts(15, 30)

    def test_01_entry_prev_close_above_sma_and_ltp_above_prev_high(self):
        candles = make_candles(rising(), current_open=105, prev_high=101)
        ev = evaluate_option(candles, "CE", ltp=102)
        self.assertTrue(ev.condition_a)
        self.assertTrue(ev.condition_b)
        self.assertTrue(ev.condition_c)
        self.assertTrue(ev.qualified)
        self.assertTrue(ev.confirmation)
        self.assertTrue(ev.signal)
        self.assertEqual(ev.sma, 100.0)
        self.assertEqual(ev.prev_high, 101.0)

    def test_02_no_entry_when_prev_close_not_above_sma(self):
        # A huge forming open must not qualify; only the previous close counts.
        closes = [100.0] * (SMA_PERIOD - 1) + [99.0]
        candles = make_candles(closes, current_open=200)
        ev = evaluate_option(candles, "CE", ltp=102)
        self.assertFalse(ev.condition_a)
        self.assertTrue(ev.condition_c)
        self.assertFalse(ev.signal)
        self.assertIn("prev_close", ev.reason)

    def test_03_wait_when_prev_close_above_sma_but_ltp_below_prev_high(self):
        candles = make_candles(rising(), current_open=105, prev_high=101)
        ev = evaluate_option(candles, "CE", ltp=100.5)
        self.assertTrue(ev.condition_a)
        self.assertTrue(ev.condition_c)
        self.assertFalse(ev.condition_b)
        self.assertFalse(ev.signal)
        self.assertIn("waiting", ev.reason)

    def test_04_entry_anytime_when_ltp_crosses_prev_high(self):
        candles = make_candles(rising(), current_open=105, prev_high=101)
        state = OptionStateMachine("CE")
        now = candles[-1]["start"] + timedelta(seconds=10)
        ev_wait = evaluate_option(candles, "CE", ltp=100.5)
        self.assertIsNone(state.try_entry(ev_wait, now, 25000, "2026-11-09",
                                          1, "CE-SYM", self.market_close))
        ev_hit = evaluate_option(candles, "CE", ltp=101.5)
        pos = state.try_entry(ev_hit, now + timedelta(seconds=60), 25000,
                              "2026-11-09", 1, "CE-SYM", self.market_close)
        self.assertIsNotNone(pos)
        self.assertEqual(pos.entry_price, 101.5)
        self.assertEqual(pos.prev_high, 101.0)

    def test_05_entry_when_ltp_below_sma_but_above_prev_high(self):
        # The LTP>SMA gate is intentionally gone: only prev close, forming
        # open and the previous candle high matter.
        candles = make_candles(rising(), current_open=105, prev_high=95)
        ev = evaluate_option(candles, "CE", ltp=97)
        self.assertTrue(ev.condition_a)
        self.assertTrue(ev.condition_b)
        self.assertTrue(ev.condition_c)
        self.assertTrue(ev.signal)
        self.assertLess(ev.ltp, ev.sma)

    def test_05b_no_entry_when_forming_open_below_sma(self):
        candles = make_candles(rising(), current_open=99, prev_high=95)
        ev = evaluate_option(candles, "CE", ltp=101)
        self.assertTrue(ev.condition_a)
        self.assertFalse(ev.condition_c)
        self.assertTrue(ev.condition_b)
        self.assertFalse(ev.signal)
        self.assertIn("current_open", ev.reason)

    def test_06_ce_and_pe_can_both_enter(self):
        ce = make_candles(rising(), current_open=105, prev_high=101)
        pe = make_candles(rising(), current_open=105, prev_high=101)
        ce_ev = evaluate_option(ce, "CE", ltp=102)
        pe_ev = evaluate_option(pe, "PE", ltp=102)
        now = ce_ev.candle_start + timedelta(seconds=10)
        ce_state, pe_state = OptionStateMachine("CE"), OptionStateMachine("PE")
        self.assertIsNotNone(ce_state.try_entry(ce_ev, now, 25000,
                                                "2026-11-09", 1, "CE-SYM",
                                                self.market_close))
        self.assertIsNotNone(pe_state.try_entry(pe_ev, now, 25000,
                                                "2026-11-09", 2, "PE-SYM",
                                                self.market_close))

    def test_07_prev_high_uses_completed_candle_not_forming(self):
        candles = make_candles(rising(), current_open=105, prev_high=101)
        ev = evaluate_option(candles, "CE", ltp=102)
        self.assertEqual(ev.prev_high, 101.0)
        # Forming candle's high is 155; it must not be used.
        self.assertGreater(candles[-1]["high"], ev.prev_high)

    def test_08_forming_close_is_ignored_for_sma(self):
        candles = make_candles(rising(), current_open=105, prev_high=101)
        candles[-1]["close"] = 999.0
        ev = evaluate_option(candles, "CE", ltp=102)
        self.assertEqual(ev.sma, 100.0)

    def test_09_one_entry_per_candle(self):
        candles = make_candles(rising(), current_open=105, prev_high=101)
        ev = evaluate_option(candles, "CE", ltp=102)
        state = OptionStateMachine("CE")
        now = ev.candle_start + timedelta(seconds=10)
        pos = state.try_entry(ev, now, 25000, "2026-11-09", 1, "CE-SYM",
                              self.market_close)
        self.assertIsNotNone(pos)
        state.close(pos.entry_candle_end, 103)
        self.assertIsNone(state.try_entry(ev, pos.entry_candle_end, 25000,
                                          "2026-11-09", 1, "CE-SYM",
                                          self.market_close))

    def test_10_exit_at_candle_end(self):
        candles = make_candles(rising(), current_open=105, prev_high=101)
        ev = evaluate_option(candles, "CE", ltp=102)
        state = OptionStateMachine("CE")
        now = ev.candle_start + timedelta(seconds=10)
        pos = state.try_entry(ev, now, 25000, "2026-11-09", 1, "CE-SYM",
                              self.market_close)
        pos = Position.from_dict(dict(
            pos.as_dict(), exit_policy=LEGACY_EXIT_POLICY))
        state.restore(pos)
        self.assertFalse(state.needs_exit(pos.entry_candle_end - timedelta(seconds=1)))
        self.assertTrue(state.needs_exit(pos.entry_candle_end))
        trade = state.close(pos.entry_candle_end, 103.5)
        self.assertEqual(trade["exit_reason"], "SAME_CANDLE_EXIT")
        self.assertEqual(trade["pnl_points"], 1.5)

    def test_11_restart_restore(self):
        candles = make_candles(rising(), current_open=105, prev_high=101)
        ev = evaluate_option(candles, "CE", ltp=102)
        state = OptionStateMachine("CE")
        now = ev.candle_start + timedelta(seconds=10)
        pos = state.try_entry(ev, now, 25000, "2026-11-09", 1, "CE-SYM",
                              self.market_close)
        pos = Position.from_dict(dict(
            pos.as_dict(), exit_policy=LEGACY_EXIT_POLICY))
        other = OptionStateMachine("CE")
        other.restore(pos)
        self.assertEqual(other.position.trade_id, pos.trade_id)
        self.assertTrue(other.needs_exit(pos.entry_candle_end))

    def test_12_insufficient_candles(self):
        candles = make_candles(rising(), current_open=105, prev_high=101)[:SMA_PERIOD]
        ev = evaluate_option(candles, "CE", ltp=102)
        self.assertFalse(ev.ready)
        self.assertFalse(ev.signal)

    def test_13_trade_id_prefix_and_fields(self):
        candles = make_candles(rising(), current_open=105, prev_high=101)
        ev = evaluate_option(candles, "CE", ltp=102)
        self.assertTrue(ev.condition_c)
        state = OptionStateMachine("CE")
        now = ev.candle_start + timedelta(seconds=10)
        pos = state.try_entry(ev, now, 25000, "2026-11-09", 1, "CE-SYM",
                              self.market_close)
        self.assertTrue(pos.trade_id.startswith("S9H-"))
        trade = state.close(pos.entry_candle_end, 103)
        self.assertEqual(trade["sma_value"], 100.0)
        self.assertEqual(trade["prev_high"], 101.0)
        self.assertEqual(trade["condition_a"], 1)
        self.assertEqual(trade["condition_b"], 1)

    def test_14_no_entry_when_candle_ends_after_market_close(self):
        candles = make_candles(rising(), current_open=105, prev_high=101, start=ts(15, 25))
        ev = evaluate_option(candles, "CE", ltp=102)
        state = OptionStateMachine("CE")
        now = ev.candle_start + timedelta(seconds=10)
        self.assertIsNone(state.try_entry(ev, now, 25000, "2026-11-09", 1,
                                          "CE-SYM", self.market_close))

    def test_15_pe_pnl_is_buy_only(self):
        candles = make_candles(rising(), current_open=105, prev_high=101)
        ev = evaluate_option(candles, "PE", ltp=102)
        state = OptionStateMachine("PE")
        now = ev.candle_start + timedelta(seconds=10)
        pos = state.try_entry(ev, now, 25000, "2026-11-09", 2, "PE-SYM",
                              self.market_close)
        trade = state.close(pos.entry_candle_end, 99.5)
        self.assertEqual(trade["pnl_points"], -2.5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
