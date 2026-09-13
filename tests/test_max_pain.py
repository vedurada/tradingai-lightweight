#!/usr/bin/env python3
"""
Regression tests for Options Intelligence.
Tests Max Pain correction and OI concentration calculations.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.options import OptionsEngine
from backend.api_server import max_pain as api_max_pain
from backend.fo_fetcher import compute_pcr_maxpain
import sqlite3


def make_contracts(ce_oi_dict, pe_oi_dict):
    """Helper to create contract list from strike->OI dicts."""
    contracts = []
    for strike, oi in ce_oi_dict.items():
        contracts.append({"strike": strike, "option_type": "CE", "open_interest": oi})
    for strike, oi in pe_oi_dict.items():
        contracts.append({"strike": strike, "option_type": "PE", "open_interest": oi})
    return contracts


def test_known_max_pain():
    """Test with synthetic chain where expected Max Pain is known."""
    # Setup: Spot ~ 100
    # CE OI:  90: 100, 100: 200, 110: 50
    # PE OI:  90: 50,  100: 300, 110: 100
    #
    # At settlement 90:  Call payout = 0 + 100*100 + 200*200 = 50000
    #                    Put payout = 0*50 + 10*300 + 20*100 = 5000
    #                    Total = 55000
    #
    # At settlement 100: Call payout = 10*100 + 0*200 + 0*50 = 1000
    #                    Put payout = 0*50 + 0*300 + 10*100 = 1000
    #                    Total = 2000
    #
    # At settlement 110: Call payout = 20*100 + 10*200 + 0*50 = 4000
    #                    Put payout = 0*50 + 0*300 + 0*100 = 0
    #                    Total = 4000
    #
    # Expected Max Pain = 100 (minimum total payout = 2000)
    contracts = make_contracts(
        {90: 100, 100: 200, 110: 50},
        {90: 50, 100: 300, 110: 100}
    )

    engine = OptionsEngine()
    result = engine._max_pain_aggregate_payout(contracts)
    assert result["max_pain"] == 100, f"Expected 100, got {result['max_pain']}"
    assert result["min_payout"] == 2000, f"Expected min payout 2000, got {result['min_payout']}"
    print("✓ test_known_max_pain passed")


def test_oi_ranking_different_from_max_pain():
    """Verify that Max Pain != OI ranking (the old incorrect method)."""
    # If we just pick strike with highest combined OI, we'd get 100
    # But true Max Pain is 95 (let's construct a case where they differ)

    # CE: 90: 1000, 95: 100, 100: 10
    # PE: 90: 10, 95: 100, 100: 1000
    # Combined OI: 90: 1010, 95: 200, 100: 1010 -> OI ranking would pick 90 or 100
    # But true Max Pain:
    # At 90:  calls=0+500+1000=1500, puts=0+500+1000=1500 -> total=3000
    # At 95:  calls=500+0+500=1000, puts=500+0+500=1000 -> total=2000
    # At 100: calls=1000+500+0=1500, puts=1000+500+0=1500 -> total=3000
    # Max Pain = 95
    contracts = make_contracts(
        {90: 1000, 95: 100, 100: 10},
        {90: 10, 95: 100, 100: 1000}
    )

    engine = OptionsEngine()
    result = engine._max_pain_aggregate_payout(contracts)
    assert result["max_pain"] == 95, f"Expected 95, got {result['max_pain']}"

    # Old OI ranking would pick 90 or 100 (both have combined OI 1010)
    # New method correctly picks 95
    print("✓ test_oi_ranking_different_from_max_pain passed")


def test_calls_only():
    """Edge case: only calls present."""
    contracts = make_contracts(
        {90: 100, 100: 200, 110: 50},
        {}
    )

    engine = OptionsEngine()
    result = engine._max_pain_aggregate_payout(contracts)
    # With only calls, payout at each strike:
    # At 90: 0*100 + 0*200 + 0*50 = 0
    # At 100: 10*100 + 0*200 + 0*50 = 1000
    # At 110: 20*100 + 10*200 + 0*50 = 4000
    # Min is at 90
    assert result["max_pain"] == 90, f"Expected 90, got {result['max_pain']}"
    print("✓ test_calls_only passed")


def test_puts_only():
    """Edge case: only puts present."""
    contracts = make_contracts(
        {},
        {90: 100, 100: 200, 110: 50}
    )

    engine = OptionsEngine()
    result = engine._max_pain_aggregate_payout(contracts)
    # With only puts:
    # At 90: 0*100 + 10*200 + 20*50 = 3000
    # At 100: 0*100 + 0*200 + 10*50 = 500
    # At 110: 0*100 + 0*200 + 0*50 = 0
    # Min is at 110
    assert result["max_pain"] == 110, f"Expected 110, got {result['max_pain']}"
    print("✓ test_puts_only passed")


def test_single_strike():
    """Edge case: single strike."""
    contracts = make_contracts(
        {100: 100},
        {100: 50}
    )

    engine = OptionsEngine()
    result = engine._max_pain_aggregate_payout(contracts)
    # Only one strike, payout = 0
    assert result["max_pain"] == 100, f"Expected 100, got {result['max_pain']}"
    print("✓ test_single_strike passed")


def test_zero_oi_excluded():
    """Zero OI contracts should be excluded."""
    contracts = make_contracts(
        {90: 0, 100: 200, 110: 0},
        {90: 0, 100: 0, 110: 0}
    )

    engine = OptionsEngine()
    result = engine._max_pain_aggregate_payout(contracts)
    # Only 100 has non-zero OI
    assert result["max_pain"] == 100, f"Expected 100, got {result['max_pain']}"
    print("✓ test_zero_oi_excluded passed")


def test_empty_contracts():
    """Empty contracts list."""
    engine = OptionsEngine()
    result = engine._max_pain_aggregate_payout([])
    assert result["max_pain"] is None, f"Expected None, got {result['max_pain']}"
    print("✓ test_empty_contracts passed")


def test_invalid_contracts():
    """Invalid contracts (missing fields) should be skipped."""
    contracts = [
        {"strike": 100, "option_type": "CE", "open_interest": 100},
        {"strike": 100},  # missing option_type and open_interest
        {"option_type": "PE", "open_interest": 50},  # missing strike
        {"strike": 90, "option_type": "CE", "open_interest": -10},  # negative OI
        {"strike": 110, "option_type": "PE", "open_interest": 200},
    ]

    engine = OptionsEngine()
    result = engine._max_pain_aggregate_payout(contracts)
    # Valid: CE 100: 100, PE 110: 200
    # At 100: call=0, put=10*200=2000 -> total=2000
    # At 110: call=10*100=1000, put=0 -> total=1000
    # Max Pain = 110
    assert result["max_pain"] == 110, f"Expected 110, got {result['max_pain']}"
    print("✓ test_invalid_contracts passed")


def test_multiple_expiries():
    """Verify per-expiry calculation works independently."""
    # This tests the logic used by api_server.py and fo_fetcher.py
    # by calling the internal method that they now use
    pass  # These are integration tests requiring DB


def test_oi_concentration_basic():
    """OI concentration with known expected values."""
    contracts = [
        {"strike": 100, "option_type": "CE", "open_interest": 5000, "change_in_oi": 500},
        {"strike": 105, "option_type": "CE", "open_interest": 3000, "change_in_oi": 300},
        {"strike": 110, "option_type": "CE", "open_interest": 2000, "change_in_oi": 200},
        {"strike": 100, "option_type": "PE", "open_interest": 4000, "change_in_oi": -100},
        {"strike": 105, "option_type": "PE", "open_interest": 6000, "change_in_oi": 400},
        {"strike": 110, "option_type": "PE", "open_interest": 1000, "change_in_oi": 50},
    ]
    engine = OptionsEngine()
    result = engine.compute_oi_concentration(contracts)

    assert result["call_oi"] == 10000, f"Expected call_oi 10000, got {result['call_oi']}"
    assert result["put_oi"] == 11000, f"Expected put_oi 11000, got {result['put_oi']}"
    assert result["total_oi"] == 21000, f"Expected total_oi 21000, got {result['total_oi']}"

    # Highest Call OI: strike 100 with 5000 (50% of call OI)
    assert result["highest_call_oi"]["strike"] == 100
    assert result["highest_call_oi"]["oi"] == 5000
    assert result["highest_call_oi"]["pct_of_call_oi"] == 50.0

    # Highest Put OI: strike 105 with 6000 (54.55% of put OI)
    assert result["highest_put_oi"]["strike"] == 105
    assert result["highest_put_oi"]["oi"] == 6000

    # OI change available (some change_in_oi > 0)
    assert result["oi_change_available"] == True
    # Sum of positive CE changes: 500+300+200=1000
    assert result["call_oi_change"] == 1000, f"Expected 1000, got {result['call_oi_change']}"
    # Sum of positive PE changes: 400+50=450
    assert result["put_oi_change"] == 450, f"Expected 450, got {result['put_oi_change']}"

    print("✓ test_oi_concentration_basic passed")


def test_oi_concentration_no_change_available():
    """All change_in_oi = 0 → DATA TEMPORARILY UNAVAILABLE."""
    contracts = [
        {"strike": 100, "option_type": "CE", "open_interest": 5000, "change_in_oi": 0},
        {"strike": 105, "option_type": "CE", "open_interest": 3000, "change_in_oi": 0},
        {"strike": 100, "option_type": "PE", "open_interest": 4000, "change_in_oi": 0},
        {"strike": 105, "option_type": "PE", "open_interest": 6000, "change_in_oi": 0},
    ]
    engine = OptionsEngine()
    result = engine.compute_oi_concentration(contracts)

    assert result["oi_change_available"] == False
    assert result["call_oi_change"] == "DATA TEMPORARILY UNAVAILABLE"
    assert result["put_oi_change"] == "DATA TEMPORARILY UNAVAILABLE"
    print("✓ test_oi_concentration_no_change_available passed")


def test_oi_concentration_major_zones():
    """Major Call/Put zones are strikes with >= 10% of total OI."""
    contracts = [
        {"strike": 100, "option_type": "CE", "open_interest": 5000, "change_in_oi": 0},
        {"strike": 105, "option_type": "CE", "open_interest": 2000, "change_in_oi": 0},
        {"strike": 110, "option_type": "CE", "open_interest": 500, "change_in_oi": 0},
        {"strike": 100, "option_type": "PE", "open_interest": 6000, "change_in_oi": 0},
        {"strike": 105, "option_type": "PE", "open_interest": 2000, "change_in_oi": 0},
        {"strike": 110, "option_type": "PE", "open_interest": 500, "change_in_oi": 0},
    ]
    engine = OptionsEngine()
    result = engine.compute_oi_concentration(contracts)

    # Call OI: 100=5000(66.67%), 105=2000(26.67%), 110=500(6.67%)
    # Major call zones: 100 (66.67% >= 10%), 105 (26.67% >= 10%)
    assert len(result["major_call_zones"]) == 2
    assert result["major_call_zones"][0]["strike"] == 100
    assert abs(result["major_call_zones"][0]["pct"] - 66.67) < 0.1
    assert result["major_call_zones"][1]["strike"] == 105
    assert abs(result["major_call_zones"][1]["pct"] - 26.67) < 0.1

    # Put OI: 100=6000(60%), 105=2000(20%), 110=500(5%)
    assert len(result["major_put_zones"]) == 2
    assert result["major_put_zones"][0]["strike"] == 100

    print("✓ test_oi_concentration_major_zones passed")


def test_oi_concentration_mixed_change():
    """Some strikes have positive change, some have 0 within a real-data expiry."""
    contracts = [
        {"strike": 100, "option_type": "CE", "open_interest": 5000, "change_in_oi": 500},
        {"strike": 105, "option_type": "CE", "open_interest": 3000, "change_in_oi": 0},  # NSE didn't report
        {"strike": 100, "option_type": "PE", "open_interest": 4000, "change_in_oi": 0},  # NSE didn't report
        {"strike": 105, "option_type": "PE", "open_interest": 6000, "change_in_oi": -200},  # negative = reduction
    ]
    engine = OptionsEngine()
    result = engine.compute_oi_concentration(contracts)

    # Some positive changes exist → available
    assert result["oi_change_available"] == True
    # Only positive CE change: 500 (0 is excluded from positive sum)
    assert result["call_oi_change"] == 500
    # PE changes: 0 and -200, both not positive → 0
    assert result["put_oi_change"] == 0

    print("✓ test_oi_concentration_mixed_change passed")


def test_oi_concentration_single_strike():
    """Single strike concentration."""
    contracts = [
        {"strike": 100, "option_type": "CE", "open_interest": 1000, "change_in_oi": 100},
        {"strike": 100, "option_type": "PE", "open_interest": 500, "change_in_oi": 50},
    ]
    engine = OptionsEngine()
    result = engine.compute_oi_concentration(contracts)

    assert result["call_oi"] == 1000
    assert result["put_oi"] == 500
    assert result["highest_call_oi"]["pct_of_call_oi"] == 100.0
    assert result["highest_put_oi"]["pct_of_put_oi"] == 100.0

    print("✓ test_oi_concentration_single_strike passed")


def test_api_oi_concentration_endpoint():
    """Test /api/oi-concentration endpoint with temporary DB data."""
    import tempfile
    import shutil

    from backend.api_server import app, DB_PATH

    tmpdir = tempfile.mkdtemp()
    tmpdb = os.path.join(tmpdir, "test.db")

    # Create temp DB with schema
    conn = sqlite3.connect(tmpdb)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS option_chain (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT, expiry TEXT, strike REAL, option_type TEXT,
            open_interest INTEGER, change_in_oi INTEGER, fetched_at TEXT,
            UNIQUE(symbol, expiry, strike, option_type)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS live_quotes (
            symbol TEXT PRIMARY KEY, price REAL, timestamp TEXT
        )
    """)

    # Insert NIFTY spot price
    conn.execute("INSERT INTO live_quotes VALUES ('NIFTY', 23400.0, '2026-09-13T10:00:00')")

    # Insert option chain data: 3 strikes, CE and PE
    chain_data = [
        ("NIFTY", "2026-09-25", 100, "CE", 5000, 500, "2026-09-13T10:00:00"),
        ("NIFTY", "2026-09-25", 105, "CE", 3000, 300, "2026-09-13T10:00:00"),
        ("NIFTY", "2026-09-25", 110, "CE", 2000, 200, "2026-09-13T10:00:00"),
        ("NIFTY", "2026-09-25", 100, "PE", 4000, -100, "2026-09-13T10:00:00"),
        ("NIFTY", "2026-09-25", 105, "PE", 6000, 400, "2026-09-13T10:00:00"),
        ("NIFTY", "2026-09-25", 110, "PE", 1000, 50, "2026-09-13T10:00:00"),
        # Second expiry - all change_in_oi = 0 (yfinance/unavailable)
        ("NIFTY", "2026-12-25", 100, "CE", 5000, 0, "2026-09-13T10:00:00"),
        ("NIFTY", "2026-12-25", 105, "CE", 3000, 0, "2026-09-13T10:00:00"),
        ("NIFTY", "2026-12-25", 100, "PE", 4000, 0, "2026-09-13T10:00:00"),
        ("NIFTY", "2026-12-25", 105, "PE", 6000, 0, "2026-09-13T10:00:00"),
    ]
    for row in chain_data:
        conn.execute(
            "INSERT OR REPLACE INTO option_chain (symbol, expiry, strike, option_type, open_interest, change_in_oi, fetched_at) VALUES (?,?,?,?,?,?,?)",
            row
        )
    conn.commit()
    conn.close()

    # Temporarily redirect DB path
    original_db = DB_PATH
    try:
        # Monkey-patch DB_PATH in api_server module
        import backend.api_server as api_mod
        api_mod.DB_PATH = tmpdb

        with app.test_client() as c:
            resp = c.get('/api/oi-concentration/NIFTY')
            assert resp.status_code == 200
            data = resp.get_json()

        assert data["symbol"] == "NIFTY"
        assert data["spot"] == 23400.0

        # First expiry: real change data
        exp1 = data["2026-09-25"]
        assert exp1["call_oi"] == 10000
        assert exp1["put_oi"] == 11000
        assert exp1["oi_change_available"] == True
        assert exp1["call_oi_change"] == 1000  # 500+300+200 positive
        assert exp1["put_oi_change"] == 450   # 400+50 positive
        assert exp1["highest_call_oi"]["strike"] == 100
        assert exp1["highest_call_oi"]["pct_of_call_oi"] == 50.0
        assert exp1["highest_put_oi"]["strike"] == 105
        assert exp1["highest_put_oi"]["pct_of_put_oi"] == round(6000/11000*100, 2)

        # Second expiry: all change_in_oi = 0
        exp2 = data["2026-12-25"]
        assert exp2["call_oi"] == 8000
        assert exp2["put_oi"] == 10000
        assert exp2["oi_change_available"] == False
        assert exp2["call_oi_change"] == "DATA TEMPORARILY UNAVAILABLE"
        assert exp2["put_oi_change"] == "DATA TEMPORARILY UNAVAILABLE"

        print("✓ test_api_oi_concentration_endpoint passed")
    finally:
        api_mod.DB_PATH = original_db
        shutil.rmtree(tmpdir)


def test_expected_move_valid():
    """Valid ATM CE + PE with known spot and expiry."""
    contracts = [
        {"strike": 100, "option_type": "CE", "open_interest": 5000, "change_in_oi": 500, "implied_volatility": 20.0},
        {"strike": 105, "option_type": "CE", "open_interest": 3000, "change_in_oi": 300, "implied_volatility": 22.0},
        {"strike": 100, "option_type": "PE", "open_interest": 4000, "change_in_oi": -100, "implied_volatility": 18.0},
        {"strike": 105, "option_type": "PE", "open_interest": 6000, "change_in_oi": 400, "implied_volatility": 21.0},
    ]
    engine = OptionsEngine()
    from datetime import datetime, timezone
    from datetime import date as date_cls
    today = datetime.now(timezone.utc).date()
    future = today.replace(year=today.year + 1)
    expiry = future.isoformat()

    result = engine.compute_expected_move(contracts, 100.0, expiry)
    em = result["expected_move"]

    assert em["type"] == "options_implied"
    assert em["atm_strike"] == 100, f"Expected ATM 100, got {em['atm_strike']}"
    assert em["data_quality"] == "LIVE"

    # Manual verification
    dte = (future - today).days
    expected_iv = (20.0 + 18.0) / 2  # avg of CE ATM 20.0 and PE ATM 18.0
    expected_points = expected_iv / 100 * (dte / 365) ** 0.5 * 100.0
    expected_points = round(expected_points, 2)
    assert em["points"] == expected_points, f"Expected {expected_points} points, got {em['points']}"
    assert em["lower"] == round(100.0 - expected_points, 2)
    assert em["upper"] == round(100.0 + expected_points, 2)
    assert "IV" in em["methodology"]
    assert "sqrt" in em["methodology"] or "DTE" in em["methodology"]
    assert expiry in em["expiry"] or em["expiry"] == expiry
    print("✓ test_expected_move_valid passed")


def test_expected_move_missing_ce():
    """Only PE available."""
    contracts = [
        {"strike": 100, "option_type": "PE", "open_interest": 4000, "implied_volatility": 18.0},
        {"strike": 105, "option_type": "PE", "open_interest": 6000, "implied_volatility": 21.0},
    ]
    engine = OptionsEngine()
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).date()
    future = today.replace(year=today.year + 1)
    expiry = future.isoformat()

    result = engine.compute_expected_move(contracts, 102.0, expiry)
    em = result["expected_move"]
    assert em["atm_strike"] == 100, f"Nearest PE to 102 is 100, got {em['atm_strike']}"
    assert em["data_quality"] == "LIVE"
    assert em["type"] == "options_implied"
    print("✓ test_expected_move_missing_ce passed")


def test_expected_move_missing_pe():
    """Only CE available."""
    contracts = [
        {"strike": 100, "option_type": "CE", "open_interest": 5000, "implied_volatility": 20.0},
        {"strike": 105, "option_type": "CE", "open_interest": 3000, "implied_volatility": 22.0},
    ]
    engine = OptionsEngine()
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).date()
    future = today.replace(year=today.year + 1)
    expiry = future.isoformat()

    result = engine.compute_expected_move(contracts, 103.0, expiry)
    em = result["expected_move"]
    assert em["atm_strike"] == 105, f"Nearest CE to 103 is 105, got {em['atm_strike']}"
    assert em["data_quality"] == "LIVE"
    print("✓ test_expected_move_missing_pe passed")


def test_expected_move_missing_iv():
    """No IV available."""
    contracts = [
        {"strike": 100, "option_type": "CE", "open_interest": 5000, "implied_volatility": 0},
        {"strike": 100, "option_type": "PE", "open_interest": 4000, "implied_volatility": None},
    ]
    engine = OptionsEngine()
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).date()
    future = today.replace(year=today.year + 1)
    expiry = future.isoformat()

    result = engine.compute_expected_move(contracts, 100.0, expiry)
    em = result["expected_move"]
    assert em["points"] == "DATA TEMPORARILY UNAVAILABLE"
    assert em["data_quality"] == "DATA TEMPORARILY UNAVAILABLE"
    assert em["atm_strike"] == 100
    print("✓ test_expected_move_missing_iv passed")


def test_expected_move_invalid_iv():
    """Negative IV."""
    contracts = [
        {"strike": 100, "option_type": "CE", "open_interest": 5000, "implied_volatility": -5.0},
        {"strike": 100, "option_type": "PE", "open_interest": 4000, "implied_volatility": -2.0},
    ]
    engine = OptionsEngine()
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).date()
    future = today.replace(year=today.year + 1)
    expiry = future.isoformat()

    result = engine.compute_expected_move(contracts, 100.0, expiry)
    em = result["expected_move"]
    assert em["points"] == "DATA TEMPORARILY UNAVAILABLE"
    assert em["data_quality"] == "DATA TEMPORARILY UNAVAILABLE"
    print("✓ test_expected_move_invalid_iv passed")


def test_expected_move_zero_spot():
    """Zero spot price."""
    contracts = [
        {"strike": 100, "option_type": "CE", "open_interest": 5000, "implied_volatility": 20.0},
    ]
    engine = OptionsEngine()
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).date()
    future = today.replace(year=today.year + 1)
    expiry = future.isoformat()

    result = engine.compute_expected_move(contracts, 0, expiry)
    em = result["expected_move"]
    assert em["points"] == "DATA TEMPORARILY UNAVAILABLE"
    assert em["data_quality"] == "DATA TEMPORARILY UNAVAILABLE"
    print("✓ test_expected_move_zero_spot passed")


def test_expected_move_nearest_atm():
    """ATM strike selection picks nearest strike to spot."""
    contracts = [
        {"strike": 90, "option_type": "CE", "open_interest": 1000, "implied_volatility": 15.0},
        {"strike": 95, "option_type": "CE", "open_interest": 2000, "implied_volatility": 16.0},
        {"strike": 100, "option_type": "CE", "open_interest": 3000, "implied_volatility": 18.0},
        {"strike": 105, "option_type": "CE", "open_interest": 2500, "implied_volatility": 17.0},
        {"strike": 110, "option_type": "CE", "open_interest": 1500, "implied_volatility": 19.0},
    ]
    engine = OptionsEngine()
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).date()
    future = today.replace(year=today.year + 1)
    expiry = future.isoformat()

    result = engine.compute_expected_move(contracts, 98.0, expiry)
    em = result["expected_move"]
    # Nearest to 98 is 95 (dist 3) vs 100 (dist 2) → 100 is nearest
    assert em["atm_strike"] == 100, f"Expected 100, got {em['atm_strike']}"
    print("✓ test_expected_move_nearest_atm passed")


def test_expected_move_no_contracts():
    """Empty contracts list."""
    engine = OptionsEngine()
    result = engine.compute_expected_move([], 100.0, "2026-12-25")
    em = result["expected_move"]
    assert em["points"] == "DATA TEMPORARILY UNAVAILABLE"
    assert em["data_quality"] == "DATA TEMPORARILY UNAVAILABLE"
    print("✓ test_expected_move_no_contracts passed")


def test_expected_move_api_endpoint():
    """Test /api/expected-move endpoint with temporary DB."""
    import tempfile, shutil
    from backend.api_server import app, DB_PATH as _db_path

    tmpdir = tempfile.mkdtemp()
    tmpdb = os.path.join(tmpdir, "test.db")

    conn = sqlite3.connect(tmpdb)
    conn.execute("""CREATE TABLE IF NOT EXISTS option_chain (
        id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT, expiry TEXT, strike REAL,
        option_type TEXT, open_interest INTEGER, change_in_oi INTEGER,
        implied_volatility REAL, bid REAL, ask REAL, last_price REAL,
        bid_size INTEGER, ask_size INTEGER, fetched_at TEXT,
        UNIQUE(symbol, expiry, strike, option_type))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS live_quotes (
        symbol TEXT PRIMARY KEY, price REAL, timestamp TEXT)""")
    conn.execute("INSERT INTO live_quotes VALUES ('NIFTY', 23400.0, '2026-09-13T10:00:00')")

    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).date()
    future = today.replace(year=today.year + 1)
    expiry = future.isoformat()

    chain_data = [
        ("NIFTY", expiry, 23300, "CE", 5000, 500, 14.0),
        ("NIFTY", expiry, 23400, "CE", 8000, 800, 15.0),
        ("NIFTY", expiry, 23500, "CE", 6000, 600, 16.0),
        ("NIFTY", expiry, 23300, "PE", 4000, -100, 13.0),
        ("NIFTY", expiry, 23400, "PE", 7000, 700, 14.5),
        ("NIFTY", expiry, 23500, "PE", 5000, 500, 15.5),
    ]
    for row in chain_data:
        conn.execute(
            "INSERT OR REPLACE INTO option_chain (symbol, expiry, strike, option_type, open_interest, change_in_oi, implied_volatility, fetched_at) VALUES (?,?,?,?,?,?,?,?)",
            (*row, "2026-09-13T10:00:00"))
    conn.commit()
    conn.close()

    import backend.api_server as api_mod
    orig = api_mod.DB_PATH
    try:
        api_mod.DB_PATH = tmpdb
        with app.test_client() as c:
            resp = c.get('/api/expected-move/NIFTY')
            assert resp.status_code == 200
            data = resp.get_json()

        assert data["symbol"] == "NIFTY"
        assert data["spot"] == 23400.0
        assert expiry in data["expected_moves"]
        em = data["expected_moves"][expiry]
        assert em["type"] == "options_implied"
        assert em["data_quality"] == "LIVE"
        # ATM strike should be 23400 (nearest to 23400)
        assert em["atm_strike"] == 23400, f"Expected 23400, got {em['atm_strike']}"
        assert em["points"] > 0, f"Expected positive points, got {em['points']}"
        assert em["lower"] < 23400, f"Expected lower < 23400, got {em['lower']}"
        assert em["upper"] > 23400, f"Expected upper > 23400, got {em['upper']}"
        print("✓ test_expected_move_api_endpoint passed")
    finally:
        api_mod.DB_PATH = orig
        shutil.rmtree(tmpdir)


def test_confirmation_confirmed():
    """Bullish market + Bullish options → CONFIRMED."""
    engine = OptionsEngine()
    result = engine.compute_confirmation(
        market_bias="BULLISH", market_confidence=76,
        options_bias="BULLISH", options_confidence=68,
        pcr_value=1.18, max_pain_strike=23400, spot=23450,
        expected_move_points=180,
        oi_concentration={"highest_call_oi": {"strike": 23500, "pct_of_call_oi": 50},
                           "highest_put_oi": {"strike": 23300, "pct_of_put_oi": 45}}
    )
    c = result["confirmation"]
    assert c["status"] == "CONFIRMED"
    assert c["market_bias"] == "BULLISH"
    assert c["options_bias"] == "BULLISH"
    assert len(c["reasons"]) >= 2
    assert c["data_quality"] == "LIVE"
    print("✓ test_confirmation_confirmed passed")


def test_confirmation_divergence():
    """Bullish market + Bearish options → DIVERGENCE."""
    engine = OptionsEngine()
    result = engine.compute_confirmation(
        market_bias="BULLISH", market_confidence=76,
        options_bias="BEARISH", options_confidence=65,
        pcr_value=1.8, max_pain_strike=23800, spot=23450,
        expected_move_points=150,
    )
    c = result["confirmation"]
    assert c["status"] == "DIVERGENCE"
    assert c["market_bias"] == "BULLISH"
    assert c["options_bias"] == "BEARISH"
    assert any("diverges" in r for r in c["reasons"])
    print("✓ test_confirmation_divergence passed")


def test_confirmation_partial():
    """Bullish market + Bullish options with low confidence → PARTIAL CONFIRMATION."""
    engine = OptionsEngine()
    result = engine.compute_confirmation(
        market_bias="BULLISH", market_confidence=76,
        options_bias="BULLISH", options_confidence=45,
        pcr_value=1.18, max_pain_strike=23400, spot=23450,
    )
    c = result["confirmation"]
    assert c["status"] == "PARTIAL CONFIRMATION"
    assert c["market_bias"] == "BULLISH"
    assert c["options_bias"] == "BULLISH"
    print("✓ test_confirmation_partial passed")


def test_confirmation_neutral_both():
    """Both NEUTRAL → NEUTRAL."""
    engine = OptionsEngine()
    result = engine.compute_confirmation(
        market_bias="NEUTRAL", market_confidence=50,
        options_bias="NEUTRAL", options_confidence=40,
    )
    c = result["confirmation"]
    assert c["status"] == "NEUTRAL"
    assert "sufficient directional evidence" in c["reasons"][0]
    print("✓ test_confirmation_neutral_both passed")


def test_confirmation_unavailable_options():
    """Market directional + Options unavailable → UNAVAILABLE."""
    engine = OptionsEngine()
    result = engine.compute_confirmation(
        market_bias="BULLISH", market_confidence=76,
        options_bias=None, options_confidence=0,
    )
    c = result["confirmation"]
    assert c["status"] == "UNAVAILABLE"
    assert c["options_bias"] is None
    print("✓ test_confirmation_unavailable_options passed")


def test_confirmation_unavailable_both():
    """Both unavailable → UNAVAILABLE."""
    engine = OptionsEngine()
    result = engine.compute_confirmation(
        market_bias=None, market_confidence=0,
        options_bias=None, options_confidence=0,
    )
    c = result["confirmation"]
    assert c["status"] == "UNAVAILABLE"
    print("✓ test_confirmation_unavailable_both passed")


def test_confirmation_partial_market_neutral():
    """Market NEUTRAL + Options directional → PARTIAL CONFIRMATION."""
    engine = OptionsEngine()
    result = engine.compute_confirmation(
        market_bias="NEUTRAL", market_confidence=50,
        options_bias="BULLISH", options_confidence=65,
    )
    c = result["confirmation"]
    assert c["status"] == "PARTIAL CONFIRMATION"
    print("✓ test_confirmation_partial_market_neutral passed")


def test_confirmation_data_quality_unavailable():
    """Zero expected_move_points treated as numeric → LIVE (not fabricated)."""
    engine = OptionsEngine()
    result = engine.compute_confirmation(
        market_bias="BULLISH", market_confidence=76,
        options_bias="BULLISH", options_confidence=68,
        expected_move_points=0,
    )
    c = result["confirmation"]
    assert c["status"] == "CONFIRMED"
    print("✓ test_confirmation_data_quality_unavailable passed")


def test_derive_options_bullish():
    """Max Pain well below spot → bullish."""
    engine = OptionsEngine()
    result = engine.derive_options_bias(max_pain_strike=22000, spot=23450)
    assert result["options_bias"] == "BULLISH", f"Expected BULLISH, got {result['options_bias']}"
    assert result["data_quality"] == "LIVE"
    assert result["options_confidence"] > 0
    print("✓ test_derive_options_bullish passed")


def test_derive_options_bearish():
    """Max Pain well above spot → bearish."""
    engine = OptionsEngine()
    result = engine.derive_options_bias(max_pain_strike=25000, spot=23450)
    assert result["options_bias"] == "BEARISH", f"Expected BEARISH, got {result['options_bias']}"
    assert result["data_quality"] == "LIVE"
    print("✓ test_derive_options_bearish passed")


def test_derive_options_neutral():
    """Max Pain near spot → neutral."""
    engine = OptionsEngine()
    result = engine.derive_options_bias(max_pain_strike=23400, spot=23450)
    assert result["options_bias"] == "NEUTRAL", f"Expected NEUTRAL, got {result['options_bias']}"
    print("✓ test_derive_options_neutral passed")


def test_derive_options_unavailable():
    """Missing spot or max pain → UNAVAILABLE."""
    engine = OptionsEngine()
    result = engine.derive_options_bias(max_pain_strike=None, spot=23450)
    assert result["options_bias"] is None
    assert result["data_quality"] == "DATA TEMPORARILY UNAVAILABLE"
    result2 = engine.derive_options_bias(max_pain_strike=23400, spot=None)
    assert result2["options_bias"] is None
    print("✓ test_derive_options_unavailable passed")


def test_derive_options_with_pcr():
    """PCR modifies the bias."""
    engine = OptionsEngine()
    result = engine.derive_options_bias(max_pain_strike=23400, spot=23450, pcr_value=0.5)
    assert result["options_bias"] in ("BULLISH", "NEUTRAL")
    print("✓ test_derive_options_with_pcr passed")


def run_all_tests():
    """Run all Options Intelligence regression tests."""
    print("Running Options Intelligence regression tests...\n")

    test_known_max_pain()
    test_oi_ranking_different_from_max_pain()
    test_calls_only()
    test_puts_only()
    test_single_strike()
    test_zero_oi_excluded()
    test_empty_contracts()
    test_invalid_contracts()
    test_oi_concentration_basic()
    test_oi_concentration_no_change_available()
    test_oi_concentration_major_zones()
    test_oi_concentration_mixed_change()
    test_oi_concentration_single_strike()
    test_api_oi_concentration_endpoint()
    test_expected_move_valid()
    test_expected_move_missing_ce()
    test_expected_move_missing_pe()
    test_expected_move_missing_iv()
    test_expected_move_invalid_iv()
    test_expected_move_zero_spot()
    test_expected_move_nearest_atm()
    test_expected_move_no_contracts()
    test_expected_move_api_endpoint()
    test_confirmation_confirmed()
    test_confirmation_divergence()
    test_confirmation_partial()
    test_confirmation_neutral_both()
    test_confirmation_unavailable_options()
    test_confirmation_unavailable_both()
    test_confirmation_partial_market_neutral()
    test_confirmation_data_quality_unavailable()
    test_derive_options_bullish()
    test_derive_options_bearish()
    test_derive_options_neutral()
    test_derive_options_unavailable()
    test_derive_options_with_pcr()

    print("\n✅ All Options Intelligence regression tests passed!")


if __name__ == "__main__":
    run_all_tests()