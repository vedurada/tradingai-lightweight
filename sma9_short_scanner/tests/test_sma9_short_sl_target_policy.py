#!/usr/bin/env python3
"""Persistence and live-loop checks for SL_TARGET_1_2 short positions."""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, "app")
if APP not in sys.path:
    sys.path.insert(0, APP)

TMP = tempfile.TemporaryDirectory()
OLD_DB_PATH = os.environ.get("SMA9_SHORT_DB_PATH")
os.environ["SMA9_SHORT_DB_PATH"] = os.path.join(TMP.name, "sma9_short.db")

import live_sma9_short_scanner as live  # noqa: E402
import sma9_short_engine as engine  # noqa: E402

if OLD_DB_PATH is None:
    os.environ.pop("SMA9_SHORT_DB_PATH", None)
else:
    os.environ["SMA9_SHORT_DB_PATH"] = OLD_DB_PATH

IST = ZoneInfo("Asia/Kolkata")


def ts(h, m, s=0, day=27):
    return datetime(2026, 11, day, h, m, s, tzinfo=IST)


def bearish_candles():
    """30 completed down bars (SMA9=100, ATR=3, -DI>+DI) + forming bar."""
    start = ts(10, 0)
    rows = []
    prev = 125.0
    for i, close in enumerate(range(125, 95, -1)):
        r_start = start + timedelta(minutes=5 * i)
        rows.append({
            "start": r_start, "open": prev, "high": max(prev, close) + 1,
            "low": min(prev, close) - 1, "close": float(close), "volume": 1000,
        })
        prev = float(close)
    rows.append({
        "start": ts(12, 30), "open": 96.0, "high": 97.0, "low": 95.0,
        "close": 96.0, "volume": 500,
    })
    return rows


def make_position(exit_policy=engine.EXIT_POLICY_SL_TARGET):
    return engine.Position(
        option_type="CE", trade_id="T1", strike=25550.0,
        expiry="2026-12-22", token=1, tradingsymbol="NIFTY26D2225550CE",
        entry_timestamp=ts(12, 30, 5), entry_candle_start=ts(12, 30),
        entry_candle_end=ts(12, 35), entry_price=98.0, sma9=100.0,
        prev_close=101.0, current_open=99.0, condition_a=True,
        condition_b=True, ltp_at_entry=98.0, lowest_ltp=98.0,
        stop=100.1, atr_distance=2.1, initial_stop=100.1,
        exit_policy=exit_policy,
        target_price=(93.8 if exit_policy == engine.EXIT_POLICY_SL_TARGET
                      else None),
    )


class TestSma9ShortSlTargetPolicy(unittest.TestCase):
    @classmethod
    def tearDownClass(cls) -> None:
        TMP.cleanup()

    def setUp(self) -> None:
        live.init_db()

    def test_legacy_open_row_without_new_columns_loads_as_legacy(self):
        # Simulate a database from before the policy migration.
        conn = sqlite3.connect(live.DB_PATH)
        try:
            conn.execute("DROP TABLE IF EXISTS sma9_short_open_positions")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sma9_short_open_positions (
                    option_type TEXT PRIMARY KEY, trade_id TEXT NOT NULL,
                    strike REAL NOT NULL, expiry TEXT NOT NULL, token INTEGER,
                    tradingsymbol TEXT, entry_timestamp TEXT NOT NULL,
                    entry_candle_start TEXT NOT NULL,
                    entry_candle_end TEXT NOT NULL, entry_price REAL NOT NULL,
                    sma9 REAL NOT NULL, prev_close REAL, current_open REAL,
                    condition_a INTEGER, condition_b INTEGER, ltp_at_entry REAL,
                    lowest_ltp REAL NOT NULL, initial_stop REAL NOT NULL,
                    atr_distance REAL, stop REAL NOT NULL,
                    updated_at TEXT NOT NULL)
            """)
            conn.execute("""
                INSERT INTO sma9_short_open_positions (
                    option_type, trade_id, strike, expiry, token, tradingsymbol,
                    entry_timestamp, entry_candle_start, entry_candle_end,
                    entry_price, sma9, prev_close, current_open, condition_a,
                    condition_b, ltp_at_entry, lowest_ltp, initial_stop,
                    atr_distance, stop, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                "CE", "OLD", 25550.0, "2026-12-22", 1, "X",
                ts(12, 30, 5).isoformat(), ts(12, 30).isoformat(),
                ts(12, 35).isoformat(), 98.0, 100.0, 101.0, 99.0, 1, 1,
                98.0, 98.0, 100.1, 2.1, 100.1, ts(12, 30, 5).isoformat(),
            ))
            conn.commit()
        finally:
            conn.close()

        live.init_db()  # migrations add exit_policy / target_price
        pos = live.load_open_positions()["CE"]
        self.assertEqual(pos.exit_policy, engine.EXIT_POLICY_LEGACY)
        self.assertIsNone(pos.target_price)
        self.assertEqual(pos.initial_stop, 100.1)
        self.assertEqual(pos.stop, 100.1)

    def test_new_position_and_trade_roundtrip(self):
        pos = make_position()
        live.save_open_position(pos)
        loaded = live.load_open_positions()["CE"]
        self.assertEqual(loaded.exit_policy, engine.EXIT_POLICY_SL_TARGET)
        self.assertEqual(loaded.initial_stop, 100.1)
        self.assertEqual(loaded.target_price, 93.8)

        state = engine.OptionStateMachine("CE")
        state.restore(pos)
        trade = state.close(ts(12, 30, 10), 93.8, engine.TARGET_1_2_REASON)
        live.save_trade(trade)
        conn = sqlite3.connect(live.DB_PATH)
        try:
            row = conn.execute(
                "SELECT exit_policy, initial_stop, target_price, exit_reason "
                "FROM sma9_short_trades WHERE trade_id='T1'"
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(row, (engine.EXIT_POLICY_SL_TARGET, 100.1, 93.8,
                               engine.TARGET_1_2_REASON))

    def test_eod_flatten_is_legacy_only(self):
        state = engine.OptionStateMachine("CE")
        pos = make_position()
        state.restore(pos)
        scanner = live.Sma9ShortLiveScanner(object())

        self.assertFalse(state.needs_exit(ts(15, 20)))
        self.assertIsNone(
            scanner._close_eod("CE", state, {}, [], 98.0, ts(15, 20)))
        self.assertIsNotNone(state.position)

        pos.exit_policy = engine.EXIT_POLICY_LEGACY
        self.assertTrue(state.needs_exit(ts(15, 20)))
        trade = scanner._close_eod("CE", state, {}, [], 98.0, ts(15, 20))
        self.assertIsNotNone(trade)
        self.assertEqual(trade["exit_reason"], "EOD_15_20_FLAT")

    def test_live_scan_fills_target_at_persisted_level(self):
        class Feed:
            def __init__(self):
                self.kite = type("Kite", (), {
                    "historical_data": lambda self, *a, **k: [],
                })()

            def quote(self, symbols):
                out = {}
                for sym in symbols:
                    if sym == "NSE:NIFTY 50":
                        out[sym] = {"last_price": 25350.0}
                    elif sym.endswith("CE"):
                        out[sym] = {"last_price": 93.0}  # below 93.8 target
                    else:
                        out[sym] = {"last_price": 200.0}
                return out

            def candles(self, token, force=False):
                return bearish_candles()

        rows = bearish_candles()
        ev = engine.evaluate_option(rows, "CE", ltp=98.0)
        self.assertTrue(ev.signal)
        now = ts(12, 30, 5)
        state = engine.OptionStateMachine("CE")
        pos = state.try_entry(ev, now, 25550, "2026-12-22", 1,
                              "NIFTY26D2225550CE", ts(15, 30))
        self.assertIsNotNone(pos)
        self.assertEqual(pos.target_price, 93.8)
        live.save_open_position(pos)

        scanner = live.Sma9ShortLiveScanner(Feed())
        scanner.states["CE"].restore(pos)
        scanner.contracts = {
            "CE": {"tradingsymbol": "NIFTY26D2225550CE", "instrument_token": 1,
                   "strike": 25550.0, "expiry": "2026-12-22"},
            "PE": {"tradingsymbol": "NIFTY26D2225150PE", "instrument_token": 2,
                   "strike": 25150.0, "expiry": "2026-12-22"},
        }
        scanner.atm_strike = 25350
        scanner.expiry = date(2026, 12, 22)
        scanner.regime_state = {"bias": "BEARISH", "allowed_option": "CE",
                                "error": None}
        scanner.regime_evaluated_at = now
        with patch.object(live, "now_ist", return_value=now):
            status = scanner.scan()
        self.assertEqual(status["options"]["CE"]["exit_reason"],
                         engine.TARGET_1_2_REASON)
        self.assertEqual(status["options"]["CE"]["exit_price"], 93.8)
        self.assertIsNone(status["options"]["CE"]["position"])

        conn = sqlite3.connect(live.DB_PATH)
        try:
            row = conn.execute(
                "SELECT exit_reason, exit_price, exit_policy FROM sma9_short_trades "
                "WHERE trade_id=?", (pos.trade_id,)
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(row, (engine.TARGET_1_2_REASON, 93.8,
                               engine.EXIT_POLICY_SL_TARGET))


if __name__ == "__main__":
    unittest.main()
