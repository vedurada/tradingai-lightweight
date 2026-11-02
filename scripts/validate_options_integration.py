#!/usr/bin/env python3
"""
Validation script for Options Trading Engine integration.
Runs end-to-end checks using mocked Zerodha data.
Validates design → implementation → behavior before any VM integration.
"""

import sys
import os
import json
import sqlite3
import tempfile
from datetime import datetime
from zoneinfo import ZoneInfo
from unittest.mock import patch, MagicMock

IST = ZoneInfo("Asia/Kolkata")

# Fixed test time within market hours (14:00 IST)
TEST_TIME = datetime(2026, 10, 30, 14, 0, 0, tzinfo=IST)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import options_trading_engine as ote


RESULTS = []
FAILURES = []


def check(name, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    RESULTS.append((name, status, detail))
    if not condition:
        FAILURES.append((name, detail))
    print(f"[{status}] {name}" + (f" — {detail}" if detail else ""))


def setup_temp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.remove(path)
    ote.DB_PATH = path
    ote.init_option_trades_table()
    return path


def teardown_db(path):
    try:
        os.remove(path)
    except OSError:
        pass


def make_mock_kc(spot_price=23000.0, premium=100.0):
    kc = MagicMock()
    kc.quote.return_value = {
        f"NSE:NIFTY": {"last_price": spot_price, "ohlc": {"close": spot_price}},
        f"NFO:NIFTY26NOV5CE{spot_price}.00": {"last_price": premium},
        f"NFO:NIFTY26NOV5PE{spot_price}.00": {"last_price": premium},
    }
    kc.instruments.return_value = [
        {
            "instrument_token": 1001,
            "name": "NIFTY",
            "instrument_type": "CE",
            "expiry": "2026-11-05",
            "strike": float(spot_price),
            "tradingsymbol": f"NIFTY26NOV5CE{spot_price}.00",
            "lot_size": 50,
        },
        {
            "instrument_token": 2001,
            "name": "NIFTY",
            "instrument_type": "PE",
            "expiry": "2026-11-05",
            "strike": float(spot_price),
            "tradingsymbol": f"NIFTY26NOV5PE{spot_price}.00",
            "lot_size": 50,
        },
    ]

    def quote_side(symbols):
        out = {}
        for s in symbols:
            out[s] = {"last_price": premium}
        return out

    kc.quote.side_effect = quote_side
    return kc


def test_design_principles():
    """Validate design document principles are enforced in code."""
    print("\n=== Design Principle Validation ===")

    # 1. SHADOW enforced
    check("SHADOW enforced", ote.LIVE_EXECUTION_AUTHORIZED is False)

    # 2. Table has all required fields
    db = setup_temp_db()
    conn = sqlite3.connect(db)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(paper_option_trades)").fetchall()]
    conn.close()
    required = [
        "trade_id", "instrument", "direction", "option_type", "expiry",
        "strike", "spot_at_signal", "premium_entry", "stop_spot", "target_spot",
        "premium_exit", "exit_reason", "pnl_points", "pnl_rupees", "status",
    ]
    missing = [c for c in required if c not in cols]
    check("All required DB columns present", not missing, f"missing: {missing}")

    # 3. No place_order calls anywhere in engine source
    engine_path = os.path.join(os.path.dirname(__file__), "options_trading_engine.py")
    with open(engine_path) as f:
        src = f.read()
    check("No place_order() in engine", "place_order" not in src)
    check("No kite.place_order in engine", "kite.place_order" not in src)
    check("No orderplace in engine (case-insensitive)", "orderplace" not in src.lower())

    teardown_db(db)


def test_implementation_behavior():
    """Validate core engine behavior with mocked Zerodha."""
    print("\n=== Implementation Behavior Validation ===")

    db = setup_temp_db()

    with patch.object(ote, "_kite_client") as mock_kc, \
         patch.object(ote, "get_spot_price") as mock_spot, \
         patch.object(ote, "get_option_chain") as mock_chain, \
         patch.object(ote, "get_contract_quote") as mock_q, \
         patch.object(ote, "_ist_now", return_value=TEST_TIME):

        mock_kc.return_value = make_mock_kc(spot_price=23000.0, premium=150.0)
        mock_spot.return_value = 23000.0
        mock_chain.return_value = make_mock_kc().instruments("NFO")
        mock_q.return_value = 150.0

        engine = ote.OptionsEngine()

        # BULL signal -> CE ATM
        r = engine.on_signal(
            instrument="NIFTY", direction="BULL",
            signal_time="2026-10-30T14:10:00+05:30",
            entry_spot=23000.0, stop_spot=22989.0, target_spot=23022.5,
            signal_id="VAL-001",
        )
        check("BULL creates CE trade", r["status"] == "TRADE_CREATED", r.get("reason", ""))
        check("BULL selects CE", r.get("option_type") == "CE")
        check("BULL strike is ATM", r.get("strike") == 23000.0)
        check("BULL premium captured", r.get("premium_entry") == 150.0)
        check("Position tracked in memory", engine.has_open_position("NIFTY"))

        # Second signal for same instrument rejected
        r2 = engine.on_signal(
            instrument="NIFTY", direction="BEAR",
            signal_time="2026-10-30T14:15:00+05:30",
            entry_spot=23005.0, stop_spot=23016.0, target_spot=22982.5,
            signal_id="VAL-002",
        )
        check("Second signal rejected (Mode C)", r2["status"] == "NO_TRADE")

        # Target exit for BULL
        mock_spot.return_value = 23025.0
        mock_q.return_value = 210.0
        exits = engine.check_exits(current_spot=23025.0)
        check("Target exit triggered", len(exits) == 1)
        check("Exit reason TARGET", exits[0]["exit_reason"] == "TARGET")
        check("P&L points correct", exits[0]["pnl_points"] == 60.0, f"got {exits[0]['pnl_points']}")
        check("P&L rupees correct", exits[0]["pnl_rupees"] == 3000.0, f"got {exits[0]['pnl_rupees']}")
        check("Position closed", not engine.has_open_position("NIFTY"))

    teardown_db(db)


def test_validation_scenarios():
    """Validate edge cases and error handling."""
    print("\n=== Validation Scenarios ===")

    db = setup_temp_db()

    with patch.object(ote, "_kite_client") as mock_kc, \
         patch.object(ote, "get_spot_price") as mock_spot, \
         patch.object(ote, "get_option_chain") as mock_chain, \
         patch.object(ote, "_ist_now", return_value=TEST_TIME):

        # Scenario 1: No Zerodha client
        mock_kc.return_value = None
        engine = ote.OptionsEngine()
        r = engine.on_signal(
            instrument="NIFTY", direction="BULL",
            signal_time="2026-10-30T14:10:00+05:30",
            entry_spot=23000.0, stop_spot=22989.0, target_spot=23022.5,
            signal_id="VAL-010",
        )
        check("No Zerodha client -> NO_TRADE", r["status"] == "NO_TRADE")
        check("Reason explains client missing", "client" in r.get("reason", "").lower())

        # Scenario 2: No spot price
        mock_kc.return_value = make_mock_kc(spot_price=23000.0, premium=150.0)
        mock_spot.return_value = None
        engine2 = ote.OptionsEngine()
        r2 = engine2.on_signal(
            instrument="NIFTY", direction="BULL",
            signal_time="2026-10-30T14:10:00+05:30",
            entry_spot=23000.0, stop_spot=22989.0, target_spot=23022.5,
            signal_id="VAL-011",
        )
        check("No spot price -> NO_TRADE", r2["status"] == "NO_TRADE")

        # Scenario 3: No option chain
        mock_spot.return_value = 23000.0
        mock_chain.return_value = None
        engine3 = ote.OptionsEngine()
        r3 = engine3.on_signal(
            instrument="NIFTY", direction="BULL",
            signal_time="2026-10-30T14:10:00+05:30",
            entry_spot=23000.0, stop_spot=22989.0, target_spot=23022.5,
            signal_id="VAL-012",
        )
        check("No option chain -> NO_TRADE", r3["status"] == "NO_TRADE")
        check("Reason mentions chain", "chain" in r3.get("reason", "").lower())

    teardown_db(db)


def test_audit_trail():
    """Validate that all trades leave an audit trail in DB."""
    print("\n=== Audit Trail Validation ===")

    db = setup_temp_db()

    with patch.object(ote, "_kite_client") as mock_kc, \
         patch.object(ote, "get_spot_price") as mock_spot, \
         patch.object(ote, "get_option_chain") as mock_chain, \
         patch.object(ote, "get_contract_quote") as mock_q, \
         patch.object(ote, "_ist_now", return_value=TEST_TIME):

        mock_kc.return_value = make_mock_kc(spot_price=23000.0, premium=150.0)
        mock_spot.return_value = 23000.0
        mock_chain.return_value = make_mock_kc().instruments("NFO")
        mock_q.return_value = 150.0

        engine = ote.OptionsEngine()
        engine.on_signal(
            instrument="NIFTY", direction="BULL",
            signal_time="2026-10-30T14:10:00+05:30",
            entry_spot=23000.0, stop_spot=22989.0, target_spot=23022.5,
            signal_id="AUDIT-001",
        )

        # Check DB has the trade
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM paper_option_trades WHERE trade_id LIKE 'OPT-%'").fetchall()
        conn.close()

        check("Trade recorded in DB", len(rows) >= 1)
        if rows:
            row = dict(rows[0])
            check("Has trade_id", row["trade_id"] is not None)
            check("Has instrument", row["instrument"] == "NIFTY")
            check("Has direction", row["direction"] == "BULL")
            check("Has option_type", row["option_type"] == "CE")
            check("Has strike", row["strike"] == 23000.0)
            check("Has premium_entry", row["premium_entry"] == 150.0)
            check("Has stop_spot", row["stop_spot"] == 22989.0)
            check("Has target_spot", row["target_spot"] == 23022.5)
            check("Status OPEN initially", row["status"] == "OPEN")
            check("Has created_at", row["created_at"] is not None)

    teardown_db(db)


def main():
    print("=" * 60)
    print("TradingAI Options Engine — Validation Suite")
    print("=" * 60)

    test_design_principles()
    test_implementation_behavior()
    test_validation_scenarios()
    test_audit_trail()

    print("\n" + "=" * 60)
    print(f"Results: {len(RESULTS)} checks, {len(FAILURES)} failures")
    print("=" * 60)

    if FAILURES:
        print("\nFAILURES:")
        for name, detail in FAILURES:
            print(f"  - {name}: {detail}")
        sys.exit(1)
    else:
        print("ALL CHECKS PASSED ✅")
        sys.exit(0)


if __name__ == "__main__":
    main()
