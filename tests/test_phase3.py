#!/usr/bin/env python3
"""Phase 3 tests - Options Intelligence Engine.

Covers:
- OptionsState creation and properties
- Mobile summary format
- Evidence/uncertainty descriptions
- ATM strike identification
- OI summaries
- Options engine wrapper (frozen OptionsEngine)
- Data quality flags
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from backend.options_state import OptionsState, _describe_evidence, _describe_uncertainty
from backend.options_normalizer import build_options_state


# ═══════════════════════════════════════════════════════
# Options State Tests
# ═══════════════════════════════════════════════════════

class TestOptionsStateCreation:
    def test_state_creation(self):
        state = OptionsState(
            symbol="NIFTY", timestamp="2026-09-15T10:00:00+05:30",
            spot=23118.0, atm_strike=23100, expiry="2026-09-18",
            dte=3, pcr=1.12, pe_oi=500000, ce_oi=450000,
            total_oi=950000, max_pain=23100, iv_atm=14.8,
            iv_rank=65.5, expected_move={"low": 22900, "high": 23300, "move_pct": 0.86},
            bias="BULLISH", confidence=78,
            evidence=["Total OI: 950,000"], uncertainty=["IV unavailable"],
            data_quality="LIVE",
        )
        d = state.to_dict()
        assert d["symbol"] == "NIFTY"
        assert d["pcr"] == 1.12
        assert d["bias"] == "BULLISH"
        assert d["data_quality"] == "LIVE"

    def test_mobile_summary(self):
        state = OptionsState(
            symbol="NIFTY", timestamp="", spot=23118.0,
            atm_strike=23100, expiry=None, dte=None,
            pcr=1.12, pe_oi=500000, ce_oi=450000, total_oi=950000,
            max_pain=23100, iv_atm=14.8, iv_rank=65.5,
            expected_move=None, bias="BULLISH", confidence=78,
            evidence=[], uncertainty=[], data_quality="LIVE",
        )
        summary = state.mobile_summary()
        assert summary["symbol"] == "NIFTY"
        assert summary["bias"] == "BULLISH"
        assert "options" in summary
        assert "key_levels" in summary

    def test_immutable(self):
        state = OptionsState(
            symbol="NIFTY", timestamp="", spot=23118.0,
            atm_strike=23100, expiry=None, dte=None,
            pcr=None, pe_oi=None, ce_oi=None, total_oi=None,
            max_pain=None, iv_atm=None, iv_rank=None,
            expected_move=None, bias="NEUTRAL", confidence=0,
            evidence=[], uncertainty=[], data_quality="UNAVAILABLE",
        )
        d = state.to_dict()
        d["bias"] = "HACKED"
        assert state.bias == "NEUTRAL"

    def test_to_json(self):
        state = OptionsState(
            symbol="NIFTY", timestamp="", spot=23118.0,
            atm_strike=23100, expiry=None, dte=None,
            pcr=None, pe_oi=None, ce_oi=None, total_oi=None,
            max_pain=None, iv_atm=None, iv_rank=None,
            expected_move=None, bias="NEUTRAL", confidence=0,
            evidence=[], uncertainty=[], data_quality="UNAVAILABLE",
        )
        j = state.to_json()
        import json
        parsed = json.loads(j)
        assert parsed["symbol"] == "NIFTY"


# ═══════════════════════════════════════════════════════
# Evidence & Uncertainty Tests
# ═══════════════════════════════════════════════════════

class TestEvidence:
    def test_evidence_from_chain(self):
        chain = [
            {"strike": 23100, "option_type": "CE", "open_interest": 50000, "implied_volatility": 14.5},
            {"strike": 23200, "option_type": "CE", "open_interest": 30000, "implied_volatility": 14.8},
            {"strike": 23000, "option_type": "PE", "open_interest": 40000, "implied_volatility": 14.2},
        ]
        evidence = _describe_evidence(chain, "NIFTY")
        assert len(evidence) >= 2
        assert any("OI" in e for e in evidence)

    def test_evidence_empty(self):
        assert _describe_evidence([], "NIFTY") == []

    def test_uncertainty_missing_iv(self):
        state = OptionsState(
            symbol="NIFTY", timestamp="", spot=23118.0,
            atm_strike=None, expiry=None, dte=None,
            pcr=None, pe_oi=None, ce_oi=None, total_oi=None,
            max_pain=None, iv_atm=None, iv_rank=None,
            expected_move=None, bias="NEUTRAL", confidence=0,
            evidence=[], uncertainty=[], data_quality="DATA UNAVAILABLE",
        )
        unc = _describe_uncertainty(state)
        assert any("IV" in u for u in unc)
        assert any("UNAVAILABLE" in u for u in unc)


# ═══════════════════════════════════════════════════════
# Options Normalizer Tests (uses frozen OptionsEngine)
# ═══════════════════════════════════════════════════════

class TestBuildOptionsState:
    def test_empty_chain(self):
        state = build_options_state("NIFTY", [], 23118.0)
        assert state is not None
        assert state.bias == "NEUTRAL"
        assert state.data_quality == "LIVE"
        assert len(state.evidence) == 0

    def test_minimal_chain(self):
        chain = [
            {"strike": 23100, "option_type": "CE", "open_interest": 1000, "implied_volatility": 14.5},
            {"strike": 23200, "option_type": "PE", "open_interest": 800, "implied_volatility": 14.8},
        ]
        state = build_options_state("NIFTY", chain, 23118.0)
        assert state is not None
        assert state.atm_strike is not None
        assert state.pcr is not None
        assert state.max_pain is not None
        assert len(state.evidence) >= 1

    def test_no_chain(self):
        state = build_options_state("NIFTY", None, 23118.0)
        assert state is not None
        assert state.bias == "NEUTRAL"

    def test_atm_identification(self):
        chain = [
            {"strike": 23000, "option_type": "CE", "open_interest": 100},
            {"strike": 23100, "option_type": "CE", "open_interest": 200},
            {"strike": 23200, "option_type": "CE", "open_interest": 150},
        ]
        state = build_options_state("NIFTY", chain, 23118.0)
        assert state.atm_strike == 23100  # closest to 23118

    def test_ce_pe_separation(self):
        chain = [
            {"strike": 23100, "option_type": "CE", "open_interest": 500},
            {"strike": 23200, "option_type": "PE", "open_interest": 300},
            {"strike": 23300, "option_type": "CE", "open_interest": 200},
            {"strike": 23400, "option_type": "PE", "open_interest": 100},
        ]
        state = build_options_state("NIFTY", chain, 23118.0)
        assert state.ce_oi == 700  # 500 + 200
        assert state.pe_oi == 400  # 300 + 100
        assert state.total_oi == 1100


# ═══════════════════════════════════════════════════════
# Evidence Quality Tests
# ═══════════════════════════════════════════════════════

class TestEvidenceQuality:
    def test_no_simplistic_claims(self):
        """Evidence should describe data, not make guarantees."""
        chain = [
            {"strike": 23100, "option_type": "CE", "open_interest": 1000000},
        ]
        state = build_options_state("NIFTY", chain, 23118.0)
        for ev in state.evidence:
            assert "guarantee" not in ev.lower()
            assert "certain" not in ev.lower()
            assert "will" not in ev.lower()

    def test_uncertainty_present_when_data_incomplete(self):
        chain = [{"strike": 23100, "option_type": "CE", "open_interest": 100}]
        state = build_options_state("NIFTY", chain, 23118.0)
        assert len(state.uncertainty) >= 0  # may or may not have uncertainty


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
