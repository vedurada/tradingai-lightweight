#!/usr/bin/env python3
"""Scanner-level checks for the 15:20 flat rule."""

import os
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_DIR = os.path.join(ROOT, "app")
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

TMP = tempfile.TemporaryDirectory()
os.environ["SMA9_SHORT_DB_PATH"] = os.path.join(TMP.name, "sma9_short.db")

import live_sma9_short_scanner as scanner_mod  # noqa: E402
from sma9_short_engine import EOD_EXIT_REASON, Position  # noqa: E402

IST = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 11, 25, 15, 25, 5, tzinfo=IST)
SYMBOL = "NIFTY26D0125950CE"


def ts(hour, minute):
    return datetime(2026, 11, 25, hour, minute, tzinfo=IST)


class FakeKite:
    bar_source = "unit-test"

    @staticmethod
    def historical_data(*args, **kwargs):
        return []


class FakeFeed:
    kite = FakeKite()

    def __init__(self, premium_ltp):
        self.premium_ltp = premium_ltp

    def quote(self, symbols):
        out = {"NSE:NIFTY 50": {"last_price": 25800.0}}
        if self.premium_ltp is not None:
            out[f"NFO:{SYMBOL}"] = {"last_price": self.premium_ltp}
        return out

    def candles(self, token, force=False):
        return [
            {"start": ts(15, 15), "open": 101, "high": 102, "low": 99,
             "close": 100, "volume": 1},
            {"start": ts(15, 20), "open": 90, "high": 92, "low": 88,
             "close": 89, "volume": 1},
        ]

    def nearest_expiry(self):
        return date(2026, 12, 1)

    def find_contract(self, strike, expiry, option_type):
        return {
            "tradingsymbol": SYMBOL, "instrument_token": 47893,
            "strike": strike, "expiry": expiry,
        }


class TestScannerEodExit(unittest.TestCase):
    def setUp(self):
        scanner_mod.now_ist = lambda: NOW
        scanner_mod.init_db()
        conn = scanner_mod.db_conn()
        conn.execute("DELETE FROM sma9_short_trades")
        conn.execute("DELETE FROM sma9_short_open_positions")
        conn.commit()
        conn.close()
        pos = Position(
            option_type="CE", trade_id="S9S-TEST-EOD", strike=25950.0,
            expiry="2026-12-01", token=47893, tradingsymbol=SYMBOL,
            entry_timestamp=ts(14, 59), entry_candle_start=ts(14, 55),
            entry_candle_end=ts(15, 0), entry_price=160.7, sma9=161.61,
            prev_close=167.6, current_open=166.7, condition_a=False,
            condition_b=False, ltp_at_entry=160.7, lowest_ltp=160.1,
            initial_stop=176.77, stop=176.11,
        )
        scanner_mod.save_open_position(pos)

    def _run_scan(self, premium_ltp):
        scanner = scanner_mod.Sma9ShortLiveScanner(FakeFeed(premium_ltp))
        scanner.recover_open_positions()
        status = scanner.scan()
        conn = scanner_mod.db_conn()
        open_rows = conn.execute(
            "SELECT COUNT(*) n FROM sma9_short_open_positions"
        ).fetchone()["n"]
        trade = conn.execute(
            "SELECT * FROM sma9_short_trades ORDER BY trade_id"
        ).fetchone()
        conn.close()
        return status, open_rows, trade

    def test_eod_uses_live_ltp_when_available(self):
        status, open_rows, trade = self._run_scan(95.0)
        self.assertEqual(open_rows, 0)
        self.assertIsNotNone(trade)
        self.assertEqual(trade["exit_reason"], EOD_EXIT_REASON)
        self.assertEqual(trade["exit_price"], 95.0)
        self.assertEqual(status["options"]["CE"]["exit_reason"], EOD_EXIT_REASON)
        self.assertTrue(status["options"]["CE"]["eod_due"])

    def test_eod_falls_back_to_1520_candle_open(self):
        status, open_rows, trade = self._run_scan(None)
        self.assertEqual(open_rows, 0)
        self.assertIsNotNone(trade)
        self.assertEqual(trade["exit_reason"], EOD_EXIT_REASON)
        self.assertEqual(trade["exit_price"], 90.0)


if __name__ == "__main__":
    unittest.main()
