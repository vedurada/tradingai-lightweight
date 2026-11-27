#!/usr/bin/env python3
"""Exact 5s polling and SL_TARGET_1_2 exit-policy tests for sma9_scanner."""

import importlib
import inspect
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta
from unittest import mock
from zoneinfo import ZoneInfo

_TMP = tempfile.mkdtemp(prefix="sma9_scanner-sl-target-")
os.environ["SMA9_DB_PATH"] = os.path.join(_TMP, "sma9.db")
CODE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if CODE_ROOT not in sys.path:
    sys.path.insert(0, CODE_ROOT)

engine = importlib.import_module("app.sma9_engine")
live = importlib.import_module("app.live_sma9_scanner")

IST = ZoneInfo("Asia/Kolkata")
ENTRY_LTP = 200.0
INITIAL_STOP = 190.0
TARGET = 220.0


def ts(hour=10, minute=0, second=5):
    return datetime(2026, 11, 27, hour, minute, second, tzinfo=IST)


def make_candles(start=None):
    """Nine completed 5m candles plus a forming candle that qualifies."""
    start = start or datetime(2026, 11, 27, 9, 15, tzinfo=IST)
    closes = [100.0] * 8 + [110.0]
    rows = []
    prev = 100.0
    for i, close in enumerate(closes):
        rows.append({
            "start": start + timedelta(minutes=5 * i),
            "open": prev,
            "high": max(prev, close) + 1.0,
            "low": min(prev, close) - 1.0,
            "close": close,
            "volume": 1000,
        })
        prev = close
    rows.append({
        "start": start + timedelta(minutes=45),
        "open": 150.0,
        "high": 250.0,
        "low": 149.0,
        "close": 150.0,  # forming close never used by the entry gate
        "volume": 500,
    })
    return rows


def make_entry(now=None):
    ev = engine.evaluate_option(make_candles(), "CE", ltp=ENTRY_LTP)
    state = engine.OptionStateMachine("CE")
    pos = state.try_entry(
        ev, now or ts(), 24850, "2026-12-03", 1, "CE-SYM",
        datetime(2026, 11, 27, 15, 30, tzinfo=IST),
    )
    if pos is None:
        raise AssertionError("synthetic entry did not qualify")
    return state, pos, ev


class FakeKite:
    def historical_data(self, token, start, end, interval):
        base = datetime(2026, 11, 27, 9, 0, tzinfo=IST)
        return [
            {
                "date": base + timedelta(minutes=5 * i),
                "open": 100.0, "high": 101.0, "low": 99.0,
                "close": 100.0, "volume": 1,
            }
            for i in range(12)
        ]


class FakeFeed:
    def __init__(self, ltp=ENTRY_LTP):
        self.ltp = ltp
        self.kite = FakeKite()

    def quote(self, symbols):
        return {
            sym: {"last_price": 24850.0 if sym.startswith("NSE:") else self.ltp}
            for sym in symbols
        }

    def nearest_expiry(self):
        return date(2026, 12, 3)

    def find_contract(self, strike, expiry, option_type):
        return {
            "strike": float(strike),
            "expiry": expiry,
            "tradingsymbol": "NIFTY-DEMO-%s-%d" % (option_type, int(strike)),
            "instrument_token": 11 if option_type == "CE" else 22,
        }

    def candles(self, token, force=False):
        return make_candles()

    def candle_at(self, token, candle_start):
        return None


class TestSlTargetPolicy(unittest.TestCase):
    def setUp(self):
        self.db_dir = tempfile.mkdtemp(prefix="sma9_scanner-sl-test-")
        live.DB_PATH = os.path.join(self.db_dir, "live.db")
        live.init_db()
        self.feed = FakeFeed()
        self.scanner = live.Sma9LiveScanner(self.feed)

    def _scan(self, ltp, hour=10, minute=0, second=5):
        self.feed.ltp = ltp
        now = ts(hour, minute, second)
        with mock.patch.object(live, "now_ist", return_value=now):
            return self.scanner.scan()

    def _trades(self, option_type=None):
        conn = sqlite3.connect(live.DB_PATH)
        conn.row_factory = sqlite3.Row
        sql = "SELECT * FROM sma9_trades"
        params = ()
        if option_type:
            sql += " WHERE option_type = ?"
            params = (option_type,)
        sql += " ORDER BY exit_timestamp"
        try:
            return [dict(r) for r in conn.execute(sql, params)]
        finally:
            conn.close()

    def test_01_sleep_uses_exact_5s_wall_clock_boundaries(self):
        self.assertEqual(live.POLL_SECONDS, 5)
        for name in ("POLL_OFFSET_SECONDS", "POLL_OFFSET_SEC",
                     "POLL_OFFSET", "next_poll_time"):
            self.assertFalse(hasattr(live, name), name)
        src = inspect.getsource(live)
        for token in ("POLL_OFFSET", "next_poll_time", "poll_alignment"):
            self.assertNotIn(token, src)

        for second, micro in ((3, 123456), (5, 0), (7, 500000), (58, 500000)):
            now = datetime(2026, 11, 27, 10, 0, second, micro, tzinfo=IST)
            next_second = ((second // 5) + 1) * 5
            expected = max(0.2, next_second - second - micro / 1000000.0)
            with mock.patch.object(live, "now_ist", return_value=now), \
                    mock.patch.object(live.time, "sleep") as sleeper:
                live.sleep_to_next_tick()
            sleeper.assert_called_once()
            self.assertAlmostEqual(sleeper.call_args[0][0], expected, places=6)

    def test_02_new_entry_math_for_long_and_short(self):
        state, pos, ev = make_entry()
        self.assertTrue(ev.signal)
        self.assertEqual(pos.exit_policy, "SL_TARGET_1_2")
        self.assertEqual(pos.initial_stop, INITIAL_STOP)
        self.assertEqual(pos.target_price, TARGET)
        self.assertEqual(pos.hwm, ENTRY_LTP)
        self.assertIsNone(pos.stop)

        short_stop = engine.initial_stop_for_entry(100.0, "SHORT")
        self.assertEqual(short_stop, 105.0)
        self.assertEqual(engine.target_for_entry(100.0, short_stop, "SHORT"), 90.0)

    def test_03_position_round_trip_and_legacy_defaults(self):
        _, pos, _ = make_entry()
        payload = pos.as_dict()
        for key in ("exit_policy", "initial_stop", "target_price"):
            self.assertIn(key, payload)
        restored = engine.Position.from_dict(payload)
        for key in ("exit_policy", "initial_stop", "target_price"):
            self.assertEqual(getattr(restored, key), getattr(pos, key))
        self.assertEqual(restored.trade_id, pos.trade_id)

        legacy_payload = dict(payload)
        for key in ("exit_policy", "initial_stop", "target_price"):
            legacy_payload.pop(key)
        legacy = engine.Position.from_dict(legacy_payload)
        self.assertEqual(legacy.exit_policy, "LEGACY")
        self.assertIsNone(legacy.initial_stop)
        self.assertIsNone(legacy.target_price)

    def test_04_old_db_rows_migrate_to_legacy_policy(self):
        old_db = os.path.join(self.db_dir, "legacy.db")
        conn = sqlite3.connect(old_db)
        conn.execute("""CREATE TABLE sma9_open_positions (
            option_type TEXT PRIMARY KEY, trade_id TEXT, strike REAL,
            expiry TEXT, token INTEGER, tradingsymbol TEXT,
            entry_timestamp TEXT, entry_candle_start TEXT,
            entry_candle_end TEXT, entry_price REAL, sma9 REAL, prev_close REAL, current_open REAL, condition_a INTEGER, condition_b INTEGER, ltp_at_entry REAL, hwm REAL, stop REAL, be_locked INTEGER, updated_at TEXT
        )""")
        conn.execute(
            """INSERT INTO sma9_open_positions (
                   option_type, trade_id, strike, expiry, token, tradingsymbol,
                   entry_timestamp, entry_candle_start, entry_candle_end,
                   entry_price, sma9, prev_close, current_open, condition_a, condition_b, ltp_at_entry, hwm, stop, be_locked, updated_at) VALUES ('CE', 'LEGACY-1', 24850,
                   '2026-12-03', 11, 'CE-SYM', '2026-11-27T10:00:05+05:30',
                   '2026-11-27T10:00:00+05:30',
                   '2026-11-27T10:05:00+05:30', 200.0, 101.11, 110.0, 150.0, 1, 1, 200.0, 200.0, NULL, 0, '2026-11-27T10:00:05+05:30')"""
        )
        conn.commit()
        conn.close()

        original = live.DB_PATH
        live.DB_PATH = old_db
        try:
            live.init_db()
            loaded = live.load_open_positions()
        finally:
            live.DB_PATH = original
        pos = loaded["CE"]
        self.assertEqual(pos.exit_policy, "LEGACY")
        self.assertIsNone(pos.initial_stop)
        self.assertIsNone(pos.target_price)

    def test_05_exit_levels_and_reasons(self):
        state, _, _ = make_entry()
        self.assertIsNone(state.check_initial_stop(INITIAL_STOP + 0.01))
        self.assertEqual(state.check_initial_stop(INITIAL_STOP), INITIAL_STOP)
        self.assertEqual(state.check_initial_stop(INITIAL_STOP - 1), INITIAL_STOP)
        self.assertIsNone(state.check_target(TARGET - 0.01))
        self.assertEqual(state.check_target(TARGET), TARGET)
        self.assertEqual(state.check_target(TARGET + 1), TARGET)

        sl_fill = state.check_initial_stop(189.5)
        sl_trade = state.close(ts(), sl_fill, "STOP_LOSS_INITIAL")
        self.assertEqual(sl_trade["exit_reason"], "STOP_LOSS_INITIAL")
        self.assertEqual(sl_trade["exit_price"], INITIAL_STOP)
        self.assertEqual(sl_trade["pnl_points"], -10.0)

        state2, _, _ = make_entry()
        target_fill = state2.check_target(221.0)
        target_trade = state2.close(ts(), target_fill, "TARGET_1_2")
        self.assertEqual(target_trade["exit_reason"], "TARGET_1_2")
        self.assertEqual(target_trade["exit_price"], TARGET)
        self.assertEqual(target_trade["pnl_points"], 20.0)

    def test_06_new_policy_never_trails_and_legacy_still_works(self):
        state, pos, _ = make_entry()
        self.assertIsNone(state.update_trail(215.0))
        self.assertEqual(pos.hwm, ENTRY_LTP)
        self.assertIsNone(pos.stop)
        self.assertIsNone(state.check_stop_loss(INITIAL_STOP - 1))
        self.assertFalse(state.needs_exit(pos.entry_candle_end))

        payload = pos.as_dict()
        for key in ("exit_policy", "initial_stop", "target_price"):
            payload.pop(key)
        legacy = engine.Position.from_dict(payload)
        legacy_state = engine.OptionStateMachine("CE")
        legacy_state.restore(legacy)
        self.assertTrue(legacy_state.needs_exit(legacy.entry_candle_end))
        self.assertEqual(legacy_state.check_stop_loss(INITIAL_STOP), INITIAL_STOP)
        legacy_state.update_trail(215.0)
        self.assertEqual(legacy_state.update_trail(209.0), 210.0)

    def test_07_live_entry_persists_policy(self):
        status = self._scan(ENTRY_LTP)
        option = status["options"]["CE"]
        self.assertTrue(option["entry_made"])
        self.assertEqual(option["exit_policy"], "SL_TARGET_1_2")
        self.assertEqual(option["initial_stop"], INITIAL_STOP)
        self.assertEqual(option["target_price"], TARGET)
        self.assertEqual(status["poll_seconds"], 5)
        self.assertNotIn("poll_alignment", status)
        stored = live.load_open_positions()["CE"]
        self.assertEqual(stored.exit_policy, "SL_TARGET_1_2")
        self.assertEqual(stored.initial_stop, INITIAL_STOP)
        self.assertEqual(stored.target_price, TARGET)

    def test_08_live_stop_loss_exit_fills_at_initial_stop(self):
        self._scan(ENTRY_LTP)
        self._scan(189.5)
        trades = self._trades("CE")
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0]["exit_reason"], "STOP_LOSS_INITIAL")
        self.assertEqual(trades[0]["exit_price"], INITIAL_STOP)
        self.assertEqual(trades[0]["pnl_points"], -10.0)
        self.assertIsNone(self.scanner.states["CE"].position)

    def test_09_live_target_exit_fills_at_1_2_target(self):
        self._scan(ENTRY_LTP)
        self._scan(221.0)
        trades = self._trades("CE")
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0]["exit_reason"], "TARGET_1_2")
        self.assertEqual(trades[0]["exit_price"], TARGET)
        self.assertEqual(trades[0]["pnl_points"], 20.0)
        self.assertIsNone(self.scanner.states["CE"].position)

    def test_10_new_policy_has_no_eod_flatten(self):
        self._scan(ENTRY_LTP)
        pos = self.scanner.states["CE"].position
        status = self._scan(205.0, hour=15, minute=40, second=0)
        self.assertFalse(status["market_open"])
        self.assertIs(self.scanner.states["CE"].position, pos)
        self.assertEqual(pos.hwm, ENTRY_LTP)
        self.assertIsNone(pos.stop)
        self.assertEqual(self._trades("CE"), [])

    def test_11_new_policy_recovery_skips_entry_candle_close(self):
        self._scan(ENTRY_LTP)
        recovered = live.Sma9LiveScanner(FakeFeed())
        with mock.patch.object(live, "now_ist", return_value=ts(11, 0, 0)), \
                mock.patch.object(recovered.feed, "candle_at",
                                  side_effect=AssertionError("candle_at called")):
            recovered.recover_open_positions()
        self.assertIsNotNone(recovered.states["CE"].position)
        self.assertEqual(self._trades("CE"), [])

    def test_12_legacy_recovery_still_closes_at_candle_close(self):
        _, pos, _ = make_entry()
        payload = pos.as_dict()
        for key in ("exit_policy", "initial_stop", "target_price"):
            payload.pop(key)
        legacy = engine.Position.from_dict(payload)
        live.save_open_position(legacy)
        recovered = live.Sma9LiveScanner(FakeFeed())
        candle = {"close": 205.0, "high": 216.0, "low": 149.0}
        with mock.patch.object(live, "now_ist", return_value=ts(11, 0, 0)), \
                mock.patch.object(recovered.feed, "candle_at", return_value=candle):
            recovered.recover_open_positions()
        trades = self._trades("CE")
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0]["exit_reason"], "SAME_CANDLE_EXIT")
        self.assertEqual(trades[0]["exit_price"], 205.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
