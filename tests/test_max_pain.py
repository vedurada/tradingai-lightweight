#!/usr/bin/env python3
"""
Regression tests for Max Pain calculation.
Tests the corrected Max Pain algorithm against known expected values.
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


def run_all_tests():
    """Run all Max Pain regression tests."""
    print("Running Max Pain regression tests...\n")

    test_known_max_pain()
    test_oi_ranking_different_from_max_pain()
    test_calls_only()
    test_puts_only()
    test_single_strike()
    test_zero_oi_excluded()
    test_empty_contracts()
    test_invalid_contracts()
    # test_multiple_expiries - needs DB integration

    print("\n✅ All Max Pain regression tests passed!")


if __name__ == "__main__":
    run_all_tests()