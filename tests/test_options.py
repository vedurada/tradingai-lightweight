"""TradingAI.in — Options Intelligence Test Suite (~35 tests).

Covers PCR, Max Pain, OI concentration, IV stats, expected move,
confirmation, options bias, expiry handling, and malformed data.
Build per TEST_PLAN_SCOPE.md Section 4.2.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from backend.options import OptionsEngine

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

engine = OptionsEngine()


def contracts(ce=None, pe=None):
    out = []
    for strike, oi in (ce or {}).items():
        out.append({"strike": strike, "option_type": "CE", "open_interest": oi, "implied_volatility": 0.20})
    for strike, oi in (pe or {}).items():
        out.append({"strike": strike, "option_type": "PE", "open_interest": oi, "implied_volatility": 0.22})
    return out


# ── PCR ────────────────────────────────────────────────────────────

class TestPCR:
    def test_pcr_basic(self):
        r = engine.calculate_pcr(1000, 500)
        assert r == 0.5

    def test_pcr_call_zero(self):
        r = engine.calculate_pcr(0, 500)
        assert r == 0.0

    def test_pcr_put_zero(self):
        r = engine.calculate_pcr(500, 0)
        assert r == 0.0

    def test_pcr_both_zero(self):
        r = engine.calculate_pcr(0, 0)
        assert r == 0.0

    def test_pcr_high_put(self):
        r = engine.calculate_pcr(200, 600)
        assert abs(r - 3.0) < 0.001


# ── Max Pain ───────────────────────────────────────────────────────

class TestMaxPain:
    def test_max_pain_basic(self):
        c = contracts({90: 100, 100: 200, 110: 50}, {90: 50, 100: 300, 110: 100})
        r = engine.calculate_max_pain(c)
        assert r["max_pain"] == 100

    def test_max_pain_empty(self):
        r = engine.calculate_max_pain([])
        assert r["max_pain"] is None

    def test_max_pain_single_strike(self):
        c = contracts({100: 500}, {100: 300})
        r = engine.calculate_max_pain(c)
        assert r["max_pain"] == 100

    def test_max_pain_zero_oi(self):
        c = contracts({}, {})
        r = engine.calculate_max_pain(c)
        assert r["max_pain"] is None

    def test_max_pain_returns_dict(self):
        c = contracts({100: 100}, {100: 100})
        r = engine.calculate_max_pain(c)
        assert isinstance(r, dict)
        assert "max_pain" in r


# ── OI Concentration ───────────────────────────────────────────────

class TestOIConcentration:
    def test_oi_empty(self):
        r = engine.compute_oi_concentration([])
        assert r["call_oi"] == 0
        assert r["put_oi"] == 0
        assert r["total_oi"] == 0
        assert r["oi_change_available"] is False
        assert r["strikes"] == []

    def test_oi_basic(self):
        c = contracts({100: 500, 110: 300}, {100: 400, 110: 200})
        r = engine.compute_oi_concentration(c)
        assert r["call_oi"] == 800
        assert r["put_oi"] == 600
        assert r["total_oi"] == 1400

    def test_oi_highest_call(self):
        c = contracts({100: 500, 110: 300}, {100: 400})
        r = engine.compute_oi_concentration(c)
        assert r["highest_call_oi"]["strike"] == 100
        assert r["highest_call_oi"]["oi"] == 500

    def test_oi_change_unavailable(self):
        c = contracts({100: 500}, {100: 400})
        r = engine.compute_oi_concentration(c)
        assert r["call_oi_change"] == "DATA TEMPORARILY UNAVAILABLE"

    # malformed data: negative strikes/OI are skipped
    def test_oi_negative_strikes_skipped(self):
        c = contracts({-10: 100, 100: 500}, {0: 200, 110: 400})
        r = engine.compute_oi_concentration(c)
        assert r["call_oi"] == 500
        assert r["put_oi"] == 400

    # malformed data: missing fields default gracefully
    def test_oi_missing_fields(self):
        c = [{"strike": 100}, {"option_type": "CE", "open_interest": 50}]
        r = engine.compute_oi_concentration(c)
        assert isinstance(r, dict)
        assert "call_oi" in r


# ── IV Stats ───────────────────────────────────────────────────────

class TestIVStats:
    def test_iv_empty(self):
        r = engine.calculate_iv_stats([])
        assert r["avg_iv"] == 0
        assert r["iv_rank"] == 0

    def test_iv_basic(self):
        c = [{"implied_volatility": 0.20}, {"implied_volatility": 0.30}]
        r = engine.calculate_iv_stats(c)
        assert r["avg_iv"] == 0.25
        assert r["min_iv"] == 0.20
        assert r["max_iv"] == 0.30

    def test_iv_single(self):
        c = [{"implied_volatility": 0.18}]
        r = engine.calculate_iv_stats(c)
        assert r["avg_iv"] == 0.18
        assert r["iv_rank"] == 50.0


# ── Expected Move ──────────────────────────────────────────────────

class TestExpectedMove:
    def test_em_no_contracts(self):
        r = engine.compute_expected_move([], 100, "2026-12-31")
        em = r["expected_move"]
        assert em["data_quality"] == "DATA TEMPORARILY UNAVAILABLE"

    def test_em_zero_underlying(self):
        c = contracts({100: 500}, {100: 400})
        r = engine.compute_expected_move(c, 0, "2026-12-31")
        assert r["expected_move"]["data_quality"] == "DATA TEMPORARILY UNAVAILABLE"

    def test_em_past_expiry(self):
        c = contracts({100: 500}, {100: 400})
        r = engine.compute_expected_move(c, 100, "2000-01-01")
        assert r["expected_move"]["data_quality"] == "DATA TEMPORARILY UNAVAILABLE"

    def test_em_basic(self):
        c = contracts({100: 500}, {100: 400})
        r = engine.compute_expected_move(c, 100, "2030-01-01")
        em = r["expected_move"]
        assert em["type"] == "options_implied"
        assert em["points"] > 0
        assert em["lower"] < 100
        assert em["upper"] > 100
        assert em["data_quality"] == "LIVE"

    def test_em_missing_iv(self):
        c = [{"strike": 100, "option_type": "CE", "open_interest": 500, "implied_volatility": None}]
        r = engine.compute_expected_move(c, 100, "2030-01-01")
        assert r["expected_move"]["data_quality"] == "DATA TEMPORARILY UNAVAILABLE"


# ── Confirmation ───────────────────────────────────────────────────

class TestConfirmation:
    def test_confirmation_both_unavailable(self):
        r = engine.compute_confirmation(None, None, None, None)
        assert r["confirmation"]["status"] == "UNAVAILABLE"

    def test_confirmation_confirmed(self):
        r = engine.compute_confirmation("BULLISH", 80, "BULLISH", 70)
        assert r["confirmation"]["status"] in ("CONFIRMED", "PARTIAL CONFIRMATION")

    def test_confirmation_divergence(self):
        r = engine.compute_confirmation("BULLISH", 80, "BEARISH", 70)
        assert r["confirmation"]["status"] == "DIVERGENCE"

    def test_confirmation_partial_bullish_market_neutral_options(self):
        r = engine.compute_confirmation("NEUTRAL", 50, "BULLISH", 60)
        assert r["confirmation"]["status"] == "PARTIAL CONFIRMATION"

    def test_confirmation_partial_bearish_market_bullish_options(self):
        r = engine.compute_confirmation("BULLISH", 50, "NEUTRAL", 60)
        assert r["confirmation"]["status"] == "PARTIAL CONFIRMATION"


# ── Options Bias ───────────────────────────────────────────────────

class TestOptionsBias:
    def test_bias_no_max_pain(self):
        r = engine.derive_options_bias(None, 100)
        assert r["options_bias"] is None
        assert r["data_quality"] == "DATA TEMPORARILY UNAVAILABLE"

    def test_bias_no_spot(self):
        r = engine.derive_options_bias(100, None)
        assert r["options_bias"] is None

    def test_bias_neutral(self):
        r = engine.derive_options_bias(100, 100)
        assert r["options_bias"] in ("BULLISH", "BEARISH", "NEUTRAL")
        assert "reasons" in r

    def test_bias_has_fields(self):
        r = engine.derive_options_bias(105, 100, pcr_value=1.2)
        assert "options_bias" in r
        assert "options_confidence" in r
        assert "data_quality" in r


# ── API Endpoints ──────────────────────────────────────────────────

class TestOptionsEndpoints:
    def test_pcr_endpoint_structure(self):
        from backend.api_server import app
        with app.test_client() as c:
            r = c.get("/api/pcr")
            assert r.status_code == 200
            data = r.get_json()
            assert isinstance(data, dict)
            for sym in ["NIFTY", "BANKNIFTY", "FINNIFTY"]:
                assert sym in data, f"{sym} missing from PCR"
                assert isinstance(data[sym], list)

    def test_maxpain_endpoint_structure(self):
        from backend.api_server import app
        with app.test_client() as c:
            r = c.get("/api/maxpain")
            assert r.status_code == 200
            data = r.get_json()
            assert isinstance(data, dict)
            for sym in ["NIFTY", "BANKNIFTY", "FINNIFTY"]:
                assert sym in data, f"{sym} missing from maxpain"

    def test_options_intelligence_no_data(self):
        from backend.api_server import app
        with app.test_client() as c:
            r = c.get("/api/options-intelligence/NIFTY")
            assert r.status_code == 200
            data = r.get_json()
            assert data["symbol"] == "NIFTY"
            assert "data_quality" in data
            assert data["pcr"] is None or isinstance(data["pcr"], dict)
            assert data["oi"] is None or isinstance(data["oi"], dict)
            assert data["max_pain"] is None or isinstance(data["max_pain"], dict)
            assert "spot" in data
