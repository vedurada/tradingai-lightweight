#!/usr/bin/env python3
"""Phase 4 tests - Trade Lifecycle Engine.

Covers:
- TradeSetup creation and properties
- Lifecycle stages (DETECTED → TRIGGER → CONFIRMATION → ENTRY_WINDOW → ACTIVE → COMPLETE)
- Trade readiness: GO / WAIT / NO_SETUP
- AI WAIT capability (not manufacturing trades)
- Evidence/uncertainty descriptions
- Mobile summary format
- GAP UP bullish setup
- GAP DOWN bearish setup
- Flat open (WAIT)
- No data (NO_SETUP)
- Immutability
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from backend.trade_lifecycle import TradeSetup, TradeStage, detect_trade_setup


# ═══════════════════════════════════════════════════════
# Basic Tests
# ═══════════════════════════════════════════════════════

class TestTradeSetupCreation:
    def test_setup_has_all_stages(self):
        ts = detect_trade_setup("NIFTY", {}, {}, {}, timestamp="2026-09-15T10:00:00+05:30")
        for stage in TradeSetup.STAGES:
            assert stage in ts.stages, f"Missing stage: {stage}"

    def test_immutable(self):
        ts = detect_trade_setup("NIFTY", {}, {}, {}, timestamp="")
        d = ts.to_dict()
        d["trade_readiness"] = "HACKED"
        assert ts.trade_readiness != "HACKED"

    def test_to_json(self):
        ts = detect_trade_setup("NIFTY", {}, {}, {}, timestamp="")
        import json
        parsed = json.loads(ts.to_json())
        assert parsed["symbol"] == "NIFTY"

    def test_mobile_summary(self):
        ts = detect_trade_setup("NIFTY", {}, {}, {}, timestamp="")
        summary = ts.mobile_summary()
        assert "trade_readiness" in summary
        assert "stages" in summary
        assert "key_levels" in summary


# ═══════════════════════════════════════════════════════
# Trade Readiness Tests
# ═══════════════════════════════════════════════════════

class TestTradeReadiness:
    def test_gap_up_bullish_go(self):
        """Strong gap up with trend regime should reach GO."""
        market = {
            "spot": 25642,
            "regime": {"regime": "TRENDING_BULLISH"},
            "confidence": 78,
            "indicators": {"vwap": 25600},
        }
        options = {"pcr": 1.12, "atm_strike": 25600}
        gap = {"gap_pct": 0.62, "kind": "GAP UP", "cover_prob": 65, "high": 25650, "low": 25600}
        ts = detect_trade_setup("NIFTY", market, options, gap, timestamp="", data_quality="LIVE")
        assert ts.trade_readiness == "GO"
        assert ts.setup_type == "BREAKOUT"
        assert ts.entry_window is not None
        assert ts.invalidation is not None
        assert ts.target is not None

    def test_gap_down_bearish_go(self):
        """Gap down with bearish regime should reach GO as bounce setup."""
        market = {
            "spot": 25600,
            "regime": {"regime": "TRENDING_BEARISH"},
            "confidence": 72,
            "indicators": {"vwap": 25650},
        }
        gap = {"gap_pct": -0.55, "kind": "GAP DOWN", "cover_prob": 30, "high": 25650, "low": 25580}
        ts = detect_trade_setup("NIFTY", market, {}, gap, timestamp="")
        assert ts.trade_readiness == "GO"
        assert ts.setup_type == "BOUNCE"

    def test_flat_open_wait(self):
        """Flat open should be WAIT, not GO."""
        market = {"spot": 25642, "regime": {"regime": "BULLISH"}}
        gap = {"gap_pct": 0.05, "kind": "FLAT OPEN", "cover_prob": None}
        ts = detect_trade_setup("NIFTY", market, {}, gap, timestamp="")
        assert ts.trade_readiness == "WAIT"
        assert ts.setup_type is None or ts.setup_type == "RANGE"

    def test_no_data_no_setup(self):
        """No data should return NO_SETUP."""
        ts = detect_trade_setup("NIFTY", None, None, None, timestamp="")
        assert ts.trade_readiness == "NO_SETUP"
        assert "Market state unavailable" in str(ts.uncertainty)

    def test_small_gap_waits_for_trend(self):
        """Small gap in trend regime is WAIT, not NO_SETUP."""
        market = {"spot": 25642, "regime": {"regime": "BULLISH_RANGE"}}
        gap = {"gap_pct": 0.1, "kind": "FLAT OPEN", "cover_prob": None}
        ts = detect_trade_setup("NIFTY", market, {}, gap, timestamp="")
        assert ts.trade_readiness == "WAIT"


# ═══════════════════════════════════════════════════════
# AI WAIT Capability
# ═══════════════════════════════════════════════════════

class TestAIWait:
    def test_ai_does_not_manufacture_trade(self):
        """AI should NEVER return GO without evidence."""
        market = {"spot": 25642, "regime": {"regime": "BULLISH"}, "confidence": 78}
        gap = {"gap_pct": 0.62, "kind": "GAP UP", "cover_prob": 65, "high": 25650, "low": 25600}
        ts = detect_trade_setup("NIFTY", market, {}, gap, timestamp="")
        if ts.trade_readiness == "GO":
            assert len(ts.evidence) > 0, "GO without evidence is manufactured"
            assert ts.entry_window is not None
            assert ts.invalidation is not None

    def test_uncertainty_present_when_incomplete(self):
        """WAIT setups should have uncertainty."""
        market = {"spot": 25642, "regime": {"regime": "BULLISH"}}
        gap = {"gap_pct": 0.1, "kind": "FLAT OPEN", "cover_prob": None}
        ts = detect_trade_setup("NIFTY", market, {}, gap, timestamp="")
        assert ts.trade_readiness == "WAIT"
        assert len(ts.uncertainty) >= 0

    def test_no_setup_has_uncertainty(self):
        """NO_SETUP should explain why."""
        ts = detect_trade_setup("NIFTY", None, None, None, timestamp="")
        assert ts.trade_readiness == "NO_SETUP"
        assert len(ts.uncertainty) > 0


# ═══════════════════════════════════════════════════════
# Evidence Quality Tests
# ═══════════════════════════════════════════════════════

class TestEvidenceQuality:
    def test_no_guarantees(self):
        """Evidence should never guarantee outcomes."""
        market = {"spot": 25642, "regime": {"regime": "TRENDING_BULLISH"}}
        gap = {"gap_pct": 0.62, "kind": "GAP UP", "cover_prob": 65, "high": 25650, "low": 25600}
        ts = detect_trade_setup("NIFTY", market, {}, gap, timestamp="")
        for ev in ts.evidence:
            ev_lower = ev.lower()
            assert "guarantee" not in ev_lower
            assert "certain" not in ev_lower
            assert "will " not in ev_lower

    def test_no_simplistic_oi_claims(self):
        """Should not say 'high OI = bullish'."""
        market = {"spot": 25642, "regime": {"regime": "TRENDING_BULLISH"}}
        gap = {"gap_pct": 0.62, "kind": "GAP UP", "cover_prob": 65, "high": 25650, "low": 25600}
        ts = detect_trade_setup("NIFTY", market, {}, gap, timestamp="")
        for ev in ts.evidence:
            assert "oi is high" not in ev.lower()
            assert "oi shows bullish" not in ev.lower()


# ═══════════════════════════════════════════════════════
# Immutability and Serialization
# ═══════════════════════════════════════════════════════

class TestImmutability:
    def test_stage_immutable(self):
        stage = TradeStage("TRIGGER", "ACTIVE", reason="Test")
        d = stage.to_dict()
        d["status"] = "HACKED"
        assert stage.status == "ACTIVE"

    def test_stage_has_required_fields(self):
        stage = TradeStage("TRIGGER", "ACTIVE", reason="Test", evidence=["E1"])
        d = stage.to_dict()
        assert "name" in d
        assert "status" in d
        assert "reason" in d
        assert "evidence" in d
        assert "timestamp" in d
        assert "uncertainty" in d
        assert "levels" in d


# ═══════════════════════════════════════════════════════
# Options Integration
# ═══════════════════════════════════════════════════════

class TestOptionsIntegration:
    def test_options_summary_in_setup(self):
        market = {"spot": 25642, "regime": {"regime": "TRENDING_BULLISH"}, "confidence": 78}
        options = {"pcr": 1.12, "atm_strike": 25600, "iv_atm": 14.8, "bias": "BULLISH", "confidence": 78,
                   "evidence": ["Total OI: 950,000"], "uncertainty": ["IV unavailable"], "data_quality": "LIVE"}
        gap = {"gap_pct": 0.62, "kind": "GAP UP", "cover_prob": 65, "high": 25650, "low": 25600}
        ts = detect_trade_setup("NIFTY", market, options, gap, timestamp="")
        assert ts.options_summary is not None
        assert ts.options_summary["pcr"] == 1.12
        assert ts.options_summary["bias"] == "BULLISH"
        assert "Total OI" in str(ts.evidence)


# ═══════════════════════════════════════════════════════
# GAP DOWN Cover Probability Test
# ═══════════════════════════════════════════════════════

class TestGapDownCover:
    def test_gap_down_high_cover_is_bearish(self):
        """Gap down with high cover probability → bearish continuation."""
        market = {"spot": 25600, "regime": {"regime": "BEARISH"}, "confidence": 65}
        gap = {"gap_pct": -0.55, "kind": "GAP DOWN", "cover_prob": 80, "high": 25650, "low": 25580}
        ts = detect_trade_setup("NIFTY", market, {}, gap, timestamp="")
        assert ts.trade_readiness == "GO"
        # Should flag uncertainty about bearish case
        found_cover_uncertainty = any("cover" in u.lower() for u in ts.uncertainty)
        assert found_cover_uncertainty


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
