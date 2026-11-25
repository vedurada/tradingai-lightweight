"""Unit tests for the isolated sma9_5pct_trail scanner.

The scanner must have exactly two exits: a fixed 5% initial stop and a simple
5% trailing stop. No activation threshold, points trail, breakeven lock,
candle-close exit, target, time exit or restart-recovery exit is allowed.
"""
from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from sma9_5pct_trail_engine import (  # noqa: E402
    EXIT_REASONS,
    EXIT_STOP_LOSS,
    EXIT_TRAIL,
    STRATEGY_ID,
    STRATEGY_TYPE,
    STRATEGY_VERSION,
    STOP_LOSS_PCT,
    TRAIL_PCT,
    Evaluation,
    OptionStateMachine,
)


def _signal(candle_start: datetime, ltp: float) -> Evaluation:
    return Evaluation(
        option_type="CE",
        candle_start=candle_start,
        candle_end=candle_start + timedelta(minutes=5),
        sma=10.0,
        prev_close=12.0,
        prev_high=12.5,
        current_open=13.0,
        ltp=ltp,
        condition_a=True,
        condition_b=True,
        qualified=True,
        confirmation=True,
        signal=True,
        ready=True,
        reason="BUY signal: prev_close>SMA and current_open>SMA",
    )


class Sma95PctTrailEngineTest(unittest.TestCase):
    def setUp(self):
        self.start = datetime(2026, 11, 25, 10, 0, tzinfo=timezone.utc)
        self.state = OptionStateMachine("CE")
        pos = self.state.try_entry(
            _signal(self.start, 100.0),
            self.start + timedelta(seconds=1),
            strike=25000,
            expiry="2026-11-26",
            token=12345,
            tradingsymbol="NIFTY26D0125000CE",
            market_close=self.start + timedelta(minutes=10),
        )
        self.assertIsNotNone(pos)
        self.pos = pos

    def test_identity_and_only_two_exit_reasons(self):
        self.assertEqual(STRATEGY_ID, "sma9_5pct_trail")
        self.assertEqual(STRATEGY_VERSION, "3.0.0")
        self.assertEqual(STRATEGY_TYPE, "SMA9_5PCT_TRAIL_BUY_ONLY")
        self.assertEqual(STOP_LOSS_PCT, 0.05)
        self.assertEqual(TRAIL_PCT, 0.05)
        self.assertEqual(
            EXIT_REASONS, frozenset({"STOP_LOSS_5PCT", "TRAIL_STOP_EXIT"})
        )

    def test_entry_sets_initial_stop_at_five_percent(self):
        self.assertEqual(self.pos.entry_price, 100.0)
        self.assertEqual(self.pos.hwm, 100.0)
        self.assertEqual(self.pos.stop, 95.0)

    def test_stop_loss_fills_at_stop_level(self):
        self.assertEqual(self.state.check_stop_loss(95.01), None)
        self.assertEqual(self.state.check_stop_loss(95.0), 95.0)
        trade = self.state.close(
            self.start + timedelta(minutes=1), 95.0, EXIT_STOP_LOSS
        )
        self.assertEqual(trade["exit_reason"], "STOP_LOSS_5PCT")
        self.assertEqual(trade["exit_price"], 95.0)
        self.assertEqual(trade["pnl_points"], -5.0)
        self.assertIsNone(self.state.position)

    def test_trail_ratchets_up_only_and_fills_at_stop_level(self):
        self.assertIsNone(self.state.update_trail(103.0))
        self.assertEqual(self.pos.stop, 97.85)
        self.assertIsNone(self.state.update_trail(106.0))
        self.assertEqual(self.pos.hwm, 106.0)
        self.assertEqual(self.pos.stop, 100.7)

        # A lower LTP must not roll the stop back or trigger an early exit.
        self.assertIsNone(self.state.update_trail(104.0))
        self.assertEqual(self.pos.stop, 100.7)

        hit = self.state.update_trail(100.7)
        self.assertEqual(hit, 100.7)
        trade = self.state.close(
            self.start + timedelta(minutes=2), hit, EXIT_TRAIL
        )
        self.assertEqual(trade["exit_reason"], "TRAIL_STOP_EXIT")
        self.assertEqual(trade["exit_price"], 100.7)
        self.assertEqual(trade["pnl_points"], 0.7)

    def test_no_points_trail_or_breakeven_lock(self):
        # With a +6-point high-water mark the old rule locked at entry +2;
        # this engine uses only HWM x 0.95 = 100.70 for entry 100.
        self.assertIsNone(self.state.update_trail(106.0))
        self.assertEqual(self.pos.stop, 100.7)
        self.assertNotEqual(self.pos.stop, 102.0)

    def test_no_candle_close_or_time_exit_method(self):
        self.assertFalse(hasattr(self.state, "needs_exit"))

    def test_unsupported_exit_reasons_are_rejected(self):
        for reason in ("SAME_CANDLE_EXIT", "SAME_CANDLE_EXIT_LTP_FALLBACK",
                       "TARGET", "TIME_EXIT"):
            with self.assertRaises(ValueError):
                self.state.close(
                    self.start + timedelta(minutes=1), 100.0, reason
                )
        self.assertIsNotNone(self.state.position)


class RemovedExitRulesSourceGuardTest(unittest.TestCase):
    def test_engine_and_runner_have_no_removed_exit_logic(self):
        forbidden = (
            "be_locked",
            "BE_LOCK",
            "ACTIVATE",
            "SAME_CANDLE_EXIT",
            "needs_exit",
            "sma9_trail_engine",
            "SMA9_TRAIL_DB_PATH",
        )
        for rel in ("app/sma9_5pct_trail_engine.py",
                    "app/live_sma9_5pct_trail_scanner.py"):
            text = (ROOT / rel).read_text()
            for token in forbidden:
                self.assertNotIn(token, text, f"{token} found in {rel}")
            self.assertNotIn("\nTRAIL = ", text, f"points TRAIL found in {rel}")
            self.assertNotIn("\nACTIVATE = ", text, f"activation found in {rel}")


if __name__ == "__main__":
    unittest.main()
