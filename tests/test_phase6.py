#!/usr/bin/env python3
"""Phase 6 tests - Quote Tracking + Live Price Experience.

Covers:
- QuoteTracker receives quotes and produces telemetry
- Price change tracking (previous/current/change)
- Update interval measurement
- Quote age calculation
- Aggregate cadence statistics
- Blink decision (only on actual change)
- No blink on unchanged price
"""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from backend.quote_tracker import QuoteTracker


class TestQuoteTracker:
    def test_receive_basic(self):
        tracker = QuoteTracker("NIFTY")
        quote = tracker.receive(25642.0)
        assert quote["current_price"] == 25642.0
        assert quote["previous_price"] is None
        assert quote["price_change"] is None

    def test_receive_with_change(self):
        tracker = QuoteTracker("NIFTY")
        tracker.receive(25642.0)
        time.sleep(0.01)
        quote = tracker.receive(25643.0)
        assert quote["previous_price"] == 25642.0
        assert quote["price_change"] == 1.0

    def test_receive_no_blink_on_same(self):
        """No price change = no blink signal."""
        tracker = QuoteTracker("NIFTY")
        tracker.receive(25642.0)
        quote = tracker.receive(25642.0)
        assert quote["price_change"] == 0.0

    def test_telemetry_basic(self):
        tracker = QuoteTracker("NIFTY")
        tracker.receive(25642.0)
        tracker.receive(25643.0)
        t = tracker.get_telemetry()
        assert t["symbol"] == "NIFTY"
        assert t["status"] == "LIVE"
        assert t["total_quotes"] == 2
        assert t["current_price"] == 25643.0

    def test_telemetry_intervals(self):
        """Quote intervals should be measurable."""
        tracker = QuoteTracker("NIFTY")
        tracker.receive(25642.0)
        time.sleep(0.01)
        tracker.receive(25643.0)
        time.sleep(0.01)
        tracker.receive(25644.0)
        t = tracker.get_telemetry()
        intervals = t["quote_intervals"]
        assert intervals["min_ms"] is not None
        assert intervals["max_ms"] is not None
        assert intervals["min_ms"] <= intervals["avg_ms"] <= intervals["max_ms"]

    def test_telemetry_empty(self):
        tracker = QuoteTracker("NIFTY")
        t = tracker.get_telemetry()
        assert t["status"] == "NO_QUOTES"

    def test_source_tracking(self):
        tracker = QuoteTracker("NIFTY")
        tracker.receive(25642.0, source_timestamp="2026-09-15T09:15:00+05:30", source="live_quotes")
        quote = tracker.receive(25643.0, source_timestamp="2026-09-15T09:15:01+05:30", source="live_quotes")
        assert quote["source"] == "live_quotes"
        assert quote["previous_price"] == 25642.0

    def test_multiple_symbols(self):
        nifty = QuoteTracker("NIFTY")
        bank = QuoteTracker("BANKNIFTY")
        nifty.receive(25642.0)
        bank.receive(59420.0)
        assert nifty.get_telemetry()["current_price"] == 25642.0
        assert bank.get_telemetry()["current_price"] == 59420.0

    def test_telemetry_has_all_fields(self):
        tracker = QuoteTracker("NIFTY")
        tracker.receive(25642.0)
        t = tracker.get_telemetry()
        required = ["symbol", "status", "total_quotes", "current_price",
                    "quote_intervals", "last_update_interval_ms", "source"]
        for field in required:
            assert field in t, f"Missing field: {field}"


# ═══════════════════════════════════════════════════════
# Blink Decision Tests
# ═══════════════════════════════════════════════════════

class TestBlinkDecision:
    def test_blink_on_price_increase(self):
        """Price went up → should blink UP."""
        tracker = QuoteTracker("NIFTY")
        tracker.receive(25642.0)
        quote = tracker.receive(25643.0)
        assert quote["price_change"] > 0

    def test_blink_on_price_decrease(self):
        """Price went down → should blink DOWN."""
        tracker = QuoteTracker("NIFTY")
        tracker.receive(25643.0)
        quote = tracker.receive(25642.0)
        assert quote["price_change"] < 0

    def test_no_blink_on_unchanged(self):
        """Price unchanged → no blink."""
        tracker = QuoteTracker("NIFTY")
        tracker.receive(25642.0)
        quote = tracker.receive(25642.0)
        assert quote["price_change"] == 0

    def test_telemetry_produces_quote_age(self):
        """Quote age should be computed from source timestamp."""
        tracker = QuoteTracker("NIFTY")
        tracker.receive(25642.0, source_timestamp="2026-09-15T09:15:00+05:30")
        t = tracker.get_telemetry()
        assert t["last_quote_age_ms"] is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
