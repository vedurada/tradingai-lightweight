"""Unit tests for the isolated sma9_5pct_trail scanner.

LEGACY rows keep the fixed 5% initial stop and the simple 5% trailing stop.
New entries use only the persisted 5% initial stop and the 1:2 target. No
activation threshold, points trail, breakeven lock, candle-close, time exit or
restart-recovery exit is allowed under either policy.
"""
from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from sma9_5pct_trail_engine import (  # noqa: E402
    DI_PERIOD,
    EXIT_POLICY_SL_TARGET,
    EXIT_REASONS,
    EXIT_STOP_LOSS,
    EXIT_STOP_LOSS_INITIAL,
    EXIT_TARGET_1_2,
    EXIT_TRAIL,
    LEGACY_EXIT_REASONS,
    NEW_POLICY_EXIT_REASONS,
    STRATEGY_ID,
    STRATEGY_TYPE,
    STRATEGY_VERSION,
    STOP_LOSS_PCT,
    TRAIL_PCT,
    Evaluation,
    OptionStateMachine,
    Position,
    compute_di_components,
    compute_target_price,
    evaluate_option,
    initial_stop_price,
)


def _di_candles(closes, forming_open):
    """Completed bars followed by one forming bar; up/down bars are directional."""
    start = datetime(2026, 11, 25, 9, 15, tzinfo=timezone.utc)
    rows = []
    for i, close in enumerate(closes):
        prev = closes[i - 1] if i else close - 1
        rows.append({
            "start": start + timedelta(minutes=5 * i),
            "open": prev,
            "high": max(prev, close) + 1,
            "low": min(prev, close) - 1,
            "close": close,
            "volume": 1,
        })
    rows.append({
        "start": start + timedelta(minutes=5 * len(closes)),
        "open": forming_open,
        "high": forming_open + 1,
        "low": forming_open - 1,
        "close": forming_open,
        "volume": 1,
    })
    return rows


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
        # These checks describe LEGACY behavior for pre-existing rows; new
        # entries are covered separately in NewPolicyEngineTest.
        pos.exit_policy = "LEGACY"
        pos.initial_stop = None
        pos.target_price = None
        self.pos = pos

    def test_identity_and_exit_reasons(self):
        self.assertEqual(STRATEGY_ID, "sma9_5pct_trail")
        self.assertEqual(STRATEGY_VERSION, "3.0.0")
        self.assertEqual(STRATEGY_TYPE, "SMA9_5PCT_TRAIL_BUY_ONLY")
        self.assertEqual(STOP_LOSS_PCT, 0.05)
        self.assertEqual(TRAIL_PCT, 0.05)
        # TARGET_1_2 is now valid for new entries; the two legacy reasons
        # remain accepted for restored LEGACY rows.
        self.assertEqual(LEGACY_EXIT_REASONS,
                         frozenset({"STOP_LOSS_5PCT", "TRAIL_STOP_EXIT"}))
        self.assertEqual(NEW_POLICY_EXIT_REASONS,
                         frozenset({"STOP_LOSS_INITIAL", "TARGET_1_2"}))
        self.assertEqual(EXIT_REASONS,
                         LEGACY_EXIT_REASONS | NEW_POLICY_EXIT_REASONS)

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
        # "TARGET" (without the policy suffix) is not a valid reason; only the
        # explicit new-policy constants are accepted.
        for reason in ("SAME_CANDLE_EXIT", "SAME_CANDLE_EXIT_LTP_FALLBACK",
                       "TARGET", "TIME_EXIT"):
            with self.assertRaises(ValueError):
                self.state.close(
                    self.start + timedelta(minutes=1), 100.0, reason
                )
        self.assertIsNotNone(self.state.position)

    def test_new_policy_target_reason_is_accepted(self):
        pos = self.pos
        pos.exit_policy = EXIT_POLICY_SL_TARGET
        pos.initial_stop = 95.0
        pos.target_price = compute_target_price(pos.entry_price, pos.initial_stop)
        trade = self.state.close(
            self.start + timedelta(minutes=1), pos.target_price, EXIT_TARGET_1_2
        )
        self.assertEqual(trade["exit_reason"], "TARGET_1_2")
        self.assertEqual(trade["exit_price"], 110.0)
        self.assertEqual(trade["pnl_points"], 10.0)


class DiGateTest(unittest.TestCase):
    def _uptrend_rows(self):
        # 30 completed up bars: SMA9(last 9) = 125, prev close 129 > SMA,
        # forming open 130 > SMA and Wilder +DI > -DI.
        return _di_candles(list(range(100, 130)), 130)

    def _late_recovery_rows(self):
        # 20 steep down bars then 10 mild up bars: the last 9 closes are above
        # SMA9 and the forming open is above SMA9, but -DI still dominates.
        downtrend = [200 - 5 * i for i in range(20)]
        recovery = [106 + i for i in range(10)]
        return _di_candles(downtrend + recovery, 116)

    def test_di_gate_is_additional_to_unchanged_sma_gate(self):
        self.assertEqual(DI_PERIOD, 14)
        up = evaluate_option(self._uptrend_rows(), "CE", ltp=130)
        self.assertTrue(up.condition_a)
        self.assertTrue(up.condition_b)
        self.assertTrue(up.qualified)
        self.assertTrue(up.condition_di)
        self.assertGreater(up.plus_di, up.minus_di)
        self.assertTrue(up.signal)
        self.assertIn("DI+>DI-", up.reason)

        late = evaluate_option(self._late_recovery_rows(), "CE", ltp=116)
        self.assertTrue(late.condition_a)
        self.assertTrue(late.condition_b)
        self.assertTrue(late.qualified)
        self.assertFalse(late.condition_di)
        self.assertLess(late.plus_di, late.minus_di)
        self.assertFalse(late.signal)
        self.assertIn("DI+", late.reason)

        state = OptionStateMachine("CE")
        pos = state.try_entry(
            late,
            datetime(2026, 11, 25, 12, 0, tzinfo=timezone.utc),
            strike=25000,
            expiry="2026-11-26",
            token=12345,
            tradingsymbol="NIFTY26D0125000CE",
            market_close=datetime(2026, 11, 25, 15, 30, tzinfo=timezone.utc),
        )
        self.assertIsNone(pos)

    def test_di_unavailable_blocks_entry(self):
        # Only 9 completed bars: SMA conditions hold, but DI(14) needs 28 bars.
        rows = _di_candles(list(range(100, 109)), 109)
        ev = evaluate_option(rows, "CE", ltp=109)
        self.assertTrue(ev.qualified)
        self.assertIsNone(ev.plus_di)
        self.assertIsNone(ev.minus_di)
        self.assertFalse(ev.condition_di)
        self.assertFalse(ev.signal)
        self.assertIn("DI+", ev.reason)

    def test_forming_candle_does_not_change_di(self):
        base = evaluate_option(self._uptrend_rows(), "CE", ltp=130)
        rows = self._uptrend_rows()
        rows[-1] = {"start": rows[-1]["start"], "open": 130, "high": 999,
                    "low": 1, "close": 500, "volume": 1}
        changed = evaluate_option(rows, "CE", ltp=130)
        self.assertEqual(base.plus_di, changed.plus_di)
        self.assertEqual(base.minus_di, changed.minus_di)
        self.assertEqual(base.condition_di, changed.condition_di)

    def test_di_fields_exposed_in_evaluation_dict(self):
        ev = evaluate_option(self._uptrend_rows(), "CE", ltp=130)
        d = ev.as_dict()
        for key in ("plus_di", "minus_di", "condition_di"):
            self.assertIn(key, d)
        self.assertEqual(d["condition_di"], True)


class NewPolicyEngineTest(unittest.TestCase):
    def setUp(self):
        self.start = datetime(2026, 11, 27, 10, 0, tzinfo=timezone.utc)
        self.state = OptionStateMachine("CE")
        self.pos = self.state.try_entry(
            _signal(self.start, 100.123), self.start + timedelta(seconds=1),
            strike=25000, expiry="2026-12-24", token=1,
            tradingsymbol="TESTCE",
            market_close=self.start + timedelta(hours=6),
        )
        self.assertIsNotNone(self.pos)

    def test_entry_stores_fixed_initial_stop_and_target(self):
        self.assertEqual(self.pos.entry_price, 100.12)
        self.assertEqual(self.pos.initial_stop, 95.11)
        self.assertEqual(self.pos.stop, 95.11)
        self.assertEqual(self.pos.target_price, 110.14)
        self.assertEqual(self.pos.exit_policy, EXIT_POLICY_SL_TARGET)
        self.assertEqual(initial_stop_price(100.12), 95.11)

    def test_roundtrip_keeps_policy_fields(self):
        restored = Position.from_dict(self.pos.as_dict())
        for key in ("exit_policy", "initial_stop", "target_price", "stop",
                    "hwm"):
            self.assertEqual(getattr(restored, key), getattr(self.pos, key), key)

    def test_missing_fields_default_to_legacy(self):
        data = self.pos.as_dict()
        for key in ("exit_policy", "initial_stop", "target_price"):
            data.pop(key)
        legacy = Position.from_dict(data)
        self.assertEqual(legacy.exit_policy, "LEGACY")
        self.assertIsNone(legacy.initial_stop)
        self.assertIsNone(legacy.target_price)

    def test_new_policy_exits_fill_at_stored_levels(self):
        self.assertIsNone(self.state.check_new_policy_exit(105.0))
        self.assertEqual(self.state.check_new_policy_exit(95.0),
                         (95.11, EXIT_STOP_LOSS_INITIAL))
        self.assertEqual(self.state.check_new_policy_exit(111.0),
                         (110.14, EXIT_TARGET_1_2))
        trade = self.state.close(self.start + timedelta(minutes=1), 110.14,
                                 EXIT_TARGET_1_2)
        self.assertEqual(trade["exit_reason"], "TARGET_1_2")
        self.assertEqual(trade["exit_price"], 110.14)

    def test_new_policy_does_not_trail_or_use_legacy_stop(self):
        self.assertIsNone(self.state.update_trail(130.0))
        self.assertEqual(self.pos.hwm, 100.12)
        self.assertEqual(self.pos.stop, 95.11)
        self.assertIsNone(self.state.check_stop_loss(94.0))
        self.assertIsNone(self.state.check_new_policy_exit(None))


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

    def test_target_1_2_is_deliberately_allowed(self):
        # The old guard forbade any "TARGET" exit. The new policy reason is
        # explicitly allowed in the engine and runner; legacy reasons remain.
        engine_text = (ROOT / "app/sma9_5pct_trail_engine.py").read_text()
        runner_text = (ROOT / "app/live_sma9_5pct_trail_scanner.py").read_text()
        for text in (engine_text, runner_text):
            self.assertIn("TARGET_1_2", text)
        for reason in EXIT_STOP_LOSS, EXIT_TRAIL, EXIT_STOP_LOSS_INITIAL, EXIT_TARGET_1_2:
            self.assertIn(reason, EXIT_REASONS)


if __name__ == "__main__":
    unittest.main()
