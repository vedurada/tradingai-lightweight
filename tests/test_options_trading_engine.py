#!/usr/bin/env python3
"""
Unit tests for TradingAI Options Trading Engine.
Uses mocks — no Zerodha API calls. Safe to run anywhere.
"""

import sys
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo

# Add scripts to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

IST = ZoneInfo("Asia/Kolkata")

# Fixed test time within market hours (14:00 IST)
TEST_TIME = datetime(2026, 10, 30, 14, 0, 0, tzinfo=IST)

import options_trading_engine as ote


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def make_mock_kc(spot_price=23000.0, premium=100.0):
    """Build a mock KiteConnect client."""
    kc = MagicMock()

    # Quote for spot
    kc.quote.return_value = {
        f"NSE:NIFTY": {"last_price": spot_price, "ohlc": {"close": spot_price}},
    }

    # Instruments list (NFO options)
    kc.instruments.return_value = [
        {
            "instrument_token": 1001,
            "name": "NIFTY",
            "instrument_type": "CE",
            "expiry": "2026-11-05",
            "strike": 22950.0,
            "tradingsymbol": "NIFTY26NOV5CE22950.00",
            "lot_size": 50,
        },
        {
            "instrument_token": 1002,
            "name": "NIFTY",
            "instrument_type": "CE",
            "expiry": "2026-11-05",
            "strike": 23000.0,
            "tradingsymbol": "NIFTY26NOV5CE23000.00",
            "lot_size": 50,
        },
        {
            "instrument_token": 1003,
            "name": "NIFTY",
            "instrument_type": "CE",
            "expiry": "2026-11-05",
            "strike": 23050.0,
            "tradingsymbol": "NIFTY26NOV5CE23050.00",
            "lot_size": 50,
        },
        {
            "instrument_token": 2001,
            "name": "NIFTY",
            "instrument_type": "PE",
            "expiry": "2026-11-05",
            "strike": 22950.0,
            "tradingsymbol": "NIFTY26NOV5PE22950.00",
            "lot_size": 50,
        },
        {
            "instrument_token": 2002,
            "name": "NIFTY",
            "instrument_type": "PE",
            "expiry": "2026-11-05",
            "strike": 23000.0,
            "tradingsymbol": "NIFTY26NOV5PE23000.00",
            "lot_size": 50,
        },
        {
            "instrument_token": 2003,
            "name": "NIFTY",
            "instrument_type": "PE",
            "expiry": "2026-11-05",
            "strike": 23050.0,
            "tradingsymbol": "NIFTY26NOV5PE23050.00",
            "lot_size": 50,
        },
    ]

    def quote_side_effect(symbols):
        result = {}
        for s in symbols:
            result[s] = {"last_price": premium}
        return result

    kc.quote.side_effect = quote_side_effect
    return kc


def temp_db_path():
    """Create a temporary DB path for isolated testing."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.remove(path)
    return path


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
class TestATMSelection(unittest.TestCase):
    def test_select_atm_ce_bull(self):
        chain = [
            {"instrument_type": "CE", "strike": 22950.0, "tradingsymbol": "A"},
            {"instrument_type": "CE", "strike": 23000.0, "tradingsymbol": "B"},
            {"instrument_type": "CE", "strike": 23050.0, "tradingsymbol": "C"},
        ]
        atm = ote.select_atm_contract(chain, 23012.0, "CE")
        self.assertEqual(atm["tradingsymbol"], "B")  # 23000 closest to 23012

    def test_select_atm_pe_bear(self):
        chain = [
            {"instrument_type": "PE", "strike": 22950.0, "tradingsymbol": "A"},
            {"instrument_type": "PE", "strike": 23000.0, "tradingsymbol": "B"},
            {"instrument_type": "PE", "strike": 23050.0, "tradingsymbol": "C"},
        ]
        atm = ote.select_atm_contract(chain, 22988.0, "PE")
        # 22988 - 22950 = 38, 23000 - 22988 = 12 -> 23000 is closer
        self.assertEqual(atm["tradingsymbol"], "B")

    def test_no_contract_returns_none(self):
        atm = ote.select_atm_contract([], 23000.0, "CE")
        self.assertIsNone(atm)


class TestEngineInit(unittest.TestCase):
    def test_init_creates_table(self):
        db = temp_db_path()
        ote.DB_PATH = db
        ote.init_option_trades_table()
        conn = sqlite3.connect(db)
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='paper_option_trades'"
        ).fetchall()]
        conn.close()
        self.assertIn("paper_option_trades", tables)
        os.remove(db)


class TestSignalProcessing(unittest.TestCase):
    def setUp(self):
        self.db = temp_db_path()
        ote.DB_PATH = self.db
        ote.init_option_trades_table()

    def tearDown(self):
        os.remove(self.db)

    @patch.object(ote, "_kite_client")
    @patch.object(ote, "get_spot_price")
    @patch.object(ote, "get_option_chain")
    @patch.object(ote, "get_contract_quote")
    @patch.object(ote, "_ist_now", return_value=TEST_TIME)
    def test_bull_signal_creates_trade(
        self, mock_now, mock_quote, mock_chain, mock_spot, mock_kc
    ):
        mock_kc.return_value = make_mock_kc(spot_price=23000.0, premium=150.0)
        mock_spot.return_value = 23000.0
        mock_chain.return_value = make_mock_kc().instruments("NFO")
        mock_quote.return_value = 150.0

        engine = ote.OptionsEngine()
        result = engine.on_signal(
            instrument="NIFTY",
            direction="BULL",
            signal_time="2026-10-30T14:10:00+05:30",
            entry_spot=23000.0,
            stop_spot=22989.0,
            target_spot=23022.5,
            signal_id="SIG-001",
        )

        self.assertEqual(result["status"], "TRADE_CREATED")
        self.assertEqual(result["option_type"], "CE")
        self.assertEqual(result["strike"], 23000.0)
        self.assertEqual(result["premium_entry"], 150.0)
        self.assertTrue(engine.has_open_position("NIFTY"))
        self.assertEqual(len(engine.get_open_positions()), 1)

    @patch.object(ote, "_kite_client")
    @patch.object(ote, "get_spot_price")
    @patch.object(ote, "get_option_chain")
    @patch.object(ote, "get_contract_quote")
    @patch.object(ote, "_ist_now", return_value=TEST_TIME)
    def test_bear_signal_creates_pe(
        self, mock_now, mock_quote, mock_chain, mock_spot, mock_kc
    ):
        mock_kc.return_value = make_mock_kc(spot_price=23000.0, premium=120.0)
        mock_spot.return_value = 23000.0
        mock_chain.return_value = make_mock_kc().instruments("NFO")
        mock_quote.return_value = 120.0

        engine = ote.OptionsEngine()
        result = engine.on_signal(
            instrument="NIFTY",
            direction="BEAR",
            signal_time="2026-10-30T13:30:00+05:30",
            entry_spot=23000.0,
            stop_spot=23011.0,
            target_spot=22977.5,
            signal_id="SIG-002",
        )

        self.assertEqual(result["status"], "TRADE_CREATED")
        self.assertEqual(result["option_type"], "PE")
        self.assertEqual(result["premium_entry"], 120.0)

    @patch.object(ote, "_kite_client")
    @patch.object(ote, "get_spot_price")
    @patch.object(ote, "get_option_chain")
    @patch.object(ote, "get_contract_quote")
    @patch.object(ote, "_ist_now", return_value=TEST_TIME)
    def test_no_open_position_when_already_open(
        self, mock_now, mock_quote, mock_chain, mock_spot, mock_kc
    ):
        mock_kc.return_value = make_mock_kc(spot_price=23000.0, premium=150.0)
        mock_spot.return_value = 23000.0
        mock_chain.return_value = make_mock_kc().instruments("NFO")
        mock_quote.return_value = 150.0

        engine = ote.OptionsEngine()
        # First signal
        r1 = engine.on_signal(
            instrument="NIFTY", direction="BULL",
            signal_time="2026-10-30T14:10:00+05:30",
            entry_spot=23000.0, stop_spot=22989.0, target_spot=23022.5,
            signal_id="SIG-001",
        )
        self.assertEqual(r1["status"], "TRADE_CREATED")

        # Second signal for same instrument should be rejected
        r2 = engine.on_signal(
            instrument="NIFTY", direction="BEAR",
            signal_time="2026-10-30T14:15:00+05:30",
            entry_spot=23005.0, stop_spot=23016.0, target_spot=22982.5,
            signal_id="SIG-002",
        )
        self.assertEqual(r2["status"], "NO_TRADE")
        self.assertIn("Already open position", r2["reason"])

    @patch.object(ote, "_kite_client")
    @patch.object(ote, "_ist_now", return_value=TEST_TIME)
    def test_no_kite_client_degrades(self, mock_now, mock_kc):
        mock_kc.return_value = None
        engine = ote.OptionsEngine()
        result = engine.on_signal(
            instrument="NIFTY", direction="BULL",
            signal_time="2026-10-30T14:10:00+05:30",
            entry_spot=23000.0, stop_spot=22989.0, target_spot=23022.5,
            signal_id="SIG-003",
        )
        self.assertEqual(result["status"], "NO_TRADE")
        self.assertIn("Zerodha client", result["reason"])


class TestExitLogic(unittest.TestCase):
    def setUp(self):
        self.db = temp_db_path()
        ote.DB_PATH = self.db
        ote.init_option_trades_table()

    def tearDown(self):
        os.remove(self.db)

    @patch.object(ote, "get_contract_quote")
    @patch.object(ote, "_ist_now", return_value=TEST_TIME)
    def test_bull_target_exit(self, mock_now, mock_q):
        # Manually insert an open position into memory
        engine = ote.OptionsEngine()
        engine.kc = MagicMock()  # so get_contract_quote is called
        engine.open_positions["NIFTY"] = {
            "trade_id": "OPT-TEST-001",
            "instrument": "NIFTY",
            "direction": "BULL",
            "option_type": "CE",
            "expiry": "2026-11-05",
            "strike": 23000.0,
            "spot_at_signal": 23000.0,
            "premium_entry": 150.0,
            "stop_spot": 22989.0,
            "target_spot": 23022.5,
            "status": "OPEN",
            "tradingsymbol": "NIFTY26NOV5CE23000.00",
        }

        # Also insert into DB so check_exits can update it
        conn = sqlite3.connect(self.db)
        conn.execute("""
            INSERT INTO paper_option_trades
            (trade_id, signal_id, instrument, direction, option_type,
             expiry, strike, spot_at_signal, premium_entry,
             stop_spot, target_spot, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'OPEN', ?, ?)
        """, (
            "OPT-TEST-001", "SIG-001", "NIFTY", "BULL", "CE",
            "2026-11-05", 23000.0, 23000.0, 150.0,
            22989.0, 23022.5, "2026-10-30T14:00:00+05:30",
            "2026-10-30T14:00:00+05:30",
        ))
        conn.commit()
        conn.close()

        mock_q.return_value = 210.0  # premium rose
        exits = engine.check_exits(current_spot=23025.0)  # above target

        self.assertEqual(len(exits), 1)
        self.assertEqual(exits[0]["exit_reason"], "TARGET")
        self.assertEqual(exits[0]["pnl_points"], 60.0)  # 210 - 150
        self.assertEqual(exits[0]["pnl_rupees"], 3000.0)  # 60 * 50
        self.assertFalse(engine.has_open_position("NIFTY"))

    @patch.object(ote, "get_contract_quote")
    @patch.object(ote, "_ist_now", return_value=TEST_TIME)
    def test_bear_stop_exit(self, mock_now, mock_q):
        engine = ote.OptionsEngine()
        engine.kc = MagicMock()  # so get_contract_quote is called
        engine.open_positions["NIFTY"] = {
            "trade_id": "OPT-TEST-002",
            "instrument": "NIFTY",
            "direction": "BEAR",
            "option_type": "PE",
            "expiry": "2026-11-05",
            "strike": 23000.0,
            "spot_at_signal": 23000.0,
            "premium_entry": 120.0,
            "stop_spot": 23011.0,
            "target_spot": 22977.5,
            "status": "OPEN",
            "tradingsymbol": "NIFTY26NOV5PE23000.00",
        }

        conn = sqlite3.connect(self.db)
        conn.execute("""
            INSERT INTO paper_option_trades
            (trade_id, signal_id, instrument, direction, option_type,
             expiry, strike, spot_at_signal, premium_entry,
             stop_spot, target_spot, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'OPEN', ?, ?)
        """, (
            "OPT-TEST-002", "SIG-002", "NIFTY", "BEAR", "PE",
            "2026-11-05", 23000.0, 23000.0, 120.0,
            23011.0, 22977.5, "2026-10-30T13:30:00+05:30",
            "2026-10-30T13:30:00+05:30",
        ))
        conn.commit()
        conn.close()

        mock_q.return_value = 60.0  # premium fell
        exits = engine.check_exits(current_spot=23015.0)  # above stop for BEAR

        self.assertEqual(len(exits), 1)
        self.assertEqual(exits[0]["exit_reason"], "STOP")
        self.assertEqual(exits[0]["pnl_points"], -60.0)  # 60 - 120
        self.assertEqual(exits[0]["pnl_rupees"], -3000.0)

    @patch.object(ote, "_ist_now", return_value=TEST_TIME)
    def test_eod_exit_no_crash(self, mock_now):
        engine = ote.OptionsEngine()
        exits = engine.check_exits(current_spot=23010.0)
        self.assertIsInstance(exits, list)


class TestShadowEnforcement(unittest.TestCase):
    def test_live_execution_blocked(self):
        ote.LIVE_EXECUTION_AUTHORIZED = True
        try:
            engine = ote.OptionsEngine()
            result = engine.on_signal(
                instrument="NIFTY", direction="BULL",
                signal_time="2026-10-30T14:10:00+05:30",
                entry_spot=23000.0, stop_spot=22989.0, target_spot=23022.5,
                signal_id="SIG-BLOCKED",
            )
            self.assertEqual(result["status"], "NO_TRADE")
            self.assertIn("LIVE_EXECUTION_AUTHORIZED", result["reason"])
        finally:
            ote.LIVE_EXECUTION_AUTHORIZED = False  # reset


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    unittest.main(verbosity=2)
