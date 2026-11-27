"""SL_TARGET_1_2 policy and exact-5s polling checks for sma9_5pct_trail.

Fully offline: the live runner's DB path is redirected to a temporary SQLite
file before import, and all broker calls are faked.
"""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
TMPDIR = tempfile.TemporaryDirectory()
os.environ["SMA9_5PCT_TRAIL_DB_PATH"] = str(
    Path(TMPDIR.name) / "sma9_5pct_trail.db")
sys.path.insert(0, str(ROOT / "app"))

import live_sma9_5pct_trail_scanner as live  # noqa: E402
import sma9_5pct_trail_engine as engine  # noqa: E402

NOW = datetime(2026, 11, 27, 10, 0, 0)


def signal_ev(ltp=100.0, start=None):
    start = start or NOW - timedelta(minutes=10)
    return engine.Evaluation(
        option_type="CE", candle_start=start,
        candle_end=start + timedelta(minutes=5),
        sma=90.0, prev_close=99.0, prev_high=100.0, current_open=100.0,
        ltp=ltp, plus_di=25.0, minus_di=10.0, condition_a=True,
        condition_b=True, condition_di=True, qualified=True, confirmation=True,
        signal=True, ready=True, reason="BUY signal",
    )


def candles_at(now):
    start = now.replace(minute=0, second=0, microsecond=0) - timedelta(minutes=150)
    rows = []
    for i in range(30):
        c = 100.0 + i
        rows.append({
            "start": start + timedelta(minutes=5 * i),
            "open": c, "high": c + 3, "low": c - 3, "close": c, "volume": 1,
        })
    forming = now.replace(minute=(now.minute // 5) * 5, second=0, microsecond=0)
    rows.append({
        "start": forming, "open": 130.0, "high": 131.0, "low": 129.0,
        "close": 130.0, "volume": 1,
    })
    return rows


class FakeFeed:
    def __init__(self, ltps):
        self.ltps = dict(ltps)
        self.expiry = date.today() + timedelta(days=7)
        self.kite = type("FakeKite", (), {"bar_source": "fake"})()
        self.kite.historical_data = self._no_history

    @staticmethod
    def _no_history(*args, **kwargs):
        raise RuntimeError("history intentionally unavailable in tests")

    def quote(self, symbols):
        return {s: {"last_price": self.ltps[s]} for s in symbols}

    def candles(self, token, force=False):
        return candles_at(NOW)

    def nearest_expiry(self):
        return self.expiry

    def find_contract(self, strike, expiry, option_type):
        return {
            "tradingsymbol": f"TEST{option_type}",
            "instrument_token": 1 if option_type == "CE" else 2,
            "strike": strike, "expiry": expiry,
        }


class ScannerPolicyTest(unittest.TestCase):
    def setUp(self):
        live.init_db()
        conn = sqlite3.connect(live.DB_PATH)
        try:
            conn.execute("DELETE FROM sma9_5pct_trail_trades")
            conn.execute("DELETE FROM sma9_5pct_trail_open_positions")
            conn.commit()
        finally:
            conn.close()

    def _new_position(self, ltp=100.0):
        state = engine.OptionStateMachine("CE")
        pos = state.try_entry(signal_ev(ltp), NOW, 25000, "2026-12-24", 1,
                              "TESTCE", NOW + timedelta(hours=6))
        self.assertIsNotNone(pos)
        return pos

    def _scanner_with_position(self, pos):
        live.save_open_position(pos)
        scanner = live.TrailLiveScanner(FakeFeed({
            "NSE:NIFTY 50": 25000.0, "NFO:TESTCE": 100.0,
            "NFO:TESTPE": 100.0,
        }))
        with patch.object(live, "now_ist", return_value=NOW):
            scanner.recover_open_positions()
        self.assertIsNotNone(scanner.states["CE"].position)
        self.assertEqual(scanner.states["CE"].position.trade_id, pos.trade_id)
        scanner.atm_strike = 25000.0
        scanner.expiry = date.today() + timedelta(days=7)
        scanner.contracts = {
            "CE": {"tradingsymbol": "TESTCE", "instrument_token": 1,
                   "strike": 25000.0, "expiry": scanner.expiry},
            "PE": {"tradingsymbol": "TESTPE", "instrument_token": 2,
                   "strike": 25000.0, "expiry": scanner.expiry},
        }
        return scanner

    def _trade_row(self):
        conn = sqlite3.connect(live.DB_PATH)
        try:
            return conn.execute(
                "SELECT exit_reason, exit_price, pnl_points "
                "FROM sma9_5pct_trail_trades").fetchall()
        finally:
            conn.close()

    def test_no_offset_constants_and_exact_five_second_sleep(self):
        for rel in ("app/live_sma9_5pct_trail_scanner.py",
                    "app/sma9_5pct_trail_engine.py"):
            text = (ROOT / rel).read_text()
            for token in ("POLL_OFFSET", "next_poll_time", "poll_alignment"):
                self.assertNotIn(token, text, f"{token} found in {rel}")
        for second, micros, expected in ((2, 500000, 2.5), (5, 0, 5.0),
                                         (59, 0, 1.0)):
            now = NOW.replace(second=second, microsecond=micros)
            with patch.object(live, "now_ist", side_effect=[now, now]), \
                 patch.object(live.time, "sleep") as sleep:
                live.sleep_to_next_tick()
            sleep.assert_called_once_with(expected)
        status = live.TrailLiveScanner(FakeFeed({}))._status(NOW, {})
        self.assertEqual(status["poll_seconds"], 5)
        self.assertNotIn("poll_offset_seconds", status)
        self.assertIn(engine.EXIT_TARGET_1_2, status["exit_reasons"])

    def test_legacy_db_row_migrates_with_defaults(self):
        conn = sqlite3.connect(live.DB_PATH)
        try:
            conn.execute("DROP TABLE IF EXISTS sma9_5pct_trail_open_positions")
            conn.execute("""
                CREATE TABLE sma9_5pct_trail_open_positions (
                    option_type TEXT PRIMARY KEY, trade_id TEXT NOT NULL,
                    strike REAL NOT NULL, expiry TEXT NOT NULL, token INTEGER,
                    tradingsymbol TEXT, entry_timestamp TEXT NOT NULL,
                    entry_candle_start TEXT NOT NULL,
                    entry_candle_end TEXT NOT NULL, entry_price REAL NOT NULL,
                    prev_high REAL, current_open REAL, breakout INTEGER,
                    ltp_at_entry REAL, hwm REAL, stop REAL,
                    updated_at TEXT NOT NULL)
            """)
            conn.execute("""
                INSERT INTO sma9_5pct_trail_open_positions
                (option_type, trade_id, strike, expiry, token, tradingsymbol,
                 entry_timestamp, entry_candle_start, entry_candle_end,
                 entry_price, prev_high, current_open, breakout, ltp_at_entry,
                 hwm, stop, updated_at)
                VALUES ('CE','OLD',25000,'2026-12-24',1,'OLDCE',?,?,?,100,100,
                        100,0,100,100,95,?)
            """, (NOW.isoformat(), (NOW - timedelta(minutes=10)).isoformat(),
                  NOW.isoformat(), NOW.isoformat()))
            conn.commit()
        finally:
            conn.close()
        live.init_db()
        pos = live.load_open_positions()["CE"]
        self.assertEqual(pos.exit_policy, engine.EXIT_POLICY_LEGACY)
        self.assertIsNone(pos.initial_stop)
        self.assertIsNone(pos.target_price)

    def test_new_policy_sl_exit_fills_at_initial_stop(self):
        scanner = self._scanner_with_position(self._new_position())
        scanner.feed.ltps["NFO:TESTCE"] = 105.0
        with patch.object(live, "now_ist", return_value=NOW):
            status = scanner.scan()
        self.assertEqual(status["options"]["CE"]["exit_policy"],
                         engine.EXIT_POLICY_SL_TARGET)
        self.assertEqual(status["options"]["CE"]["initial_stop"], 95.0)
        self.assertEqual(status["options"]["CE"]["target_price"], 110.0)
        self.assertEqual(self._trade_row(), [])

        scanner.feed.ltps["NFO:TESTCE"] = 94.0
        with patch.object(live, "now_ist", return_value=NOW):
            scanner.scan()
        self.assertEqual(self._trade_row(),
                         [("STOP_LOSS_INITIAL", 95.0, -5.0)])
        self.assertIsNone(scanner.states["CE"].position)

    def test_new_policy_target_exit_fills_at_target(self):
        scanner = self._scanner_with_position(self._new_position())
        scanner.feed.ltps["NFO:TESTCE"] = 111.0
        with patch.object(live, "now_ist", return_value=NOW):
            scanner.scan()
        self.assertEqual(self._trade_row(), [("TARGET_1_2", 110.0, 10.0)])

    def test_new_policy_does_not_trail_or_eod_exit(self):
        scanner = self._scanner_with_position(self._new_position())
        late = NOW.replace(hour=15, minute=45)
        scanner.feed.ltps["NFO:TESTCE"] = 105.0
        with patch.object(live, "now_ist", return_value=late):
            scanner.scan()
        self.assertIsNotNone(scanner.states["CE"].position)
        self.assertEqual(scanner.states["CE"].position.hwm, 100.0)
        self.assertEqual(scanner.states["CE"].position.stop, 95.0)
        self.assertEqual(self._trade_row(), [])

    def test_legacy_position_still_trails_and_sl_exits(self):
        pos = self._new_position()
        pos.exit_policy = engine.EXIT_POLICY_LEGACY
        pos.initial_stop = None
        pos.target_price = None
        pos.hwm = 106.0
        pos.stop = 100.7

        scanner = self._scanner_with_position(pos)
        scanner.feed.ltps["NFO:TESTCE"] = 100.7
        with patch.object(live, "now_ist", return_value=NOW):
            scanner.scan()
        self.assertEqual(self._trade_row(), [("TRAIL_STOP_EXIT", 100.7, 0.7)])

        pos.hwm = 100.0
        pos.stop = 95.0
        live.save_open_position(pos)
        scanner = self._scanner_with_position(pos)
        scanner.feed.ltps["NFO:TESTCE"] = 94.0
        with patch.object(live, "now_ist", return_value=NOW):
            scanner.scan()
        self.assertEqual(self._trade_row()[-1], ("STOP_LOSS_5PCT", 95.0, -5.0))


if __name__ == "__main__":
    unittest.main()
