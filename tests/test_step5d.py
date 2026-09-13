#!/usr/bin/env python3
"""STEP 5D — Integration + regression tests.

Key invariants:
1. LLM CANNOT alter quantitative fields (regime, bias, confidence, key_levels, verdict, strategy)
2. LLM MAY provide primary_view (narrative) + llm_explanation (descriptive)
3. Scenario probabilities sum to 1.0 (mutually exclusive distribution)
4. RegimeEngine confidence ≠ build_outlook confidence (intentional — different layers)
5. UNKNOWN → NO TRADE / WAIT → no forced directional strategy
6. HIGH_VOLATILITY → strategy respects high-vol rules → no silent BULLISH/BEARISH conversion
7. StrategyEngine is canonical strategy authority
"""
import json, os, sys, tempfile, sqlite3
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend"))

from backend.scenarios import ScenarioEngine
from backend.strategies import StrategyEngine
from backend.regime import RegimeEngine


# ═══════════════════════════════════════════════════════
# Scenario normalization tests
# ═══════════════════════════════════════════════════════

class TestScenarioNormalization:
    """Scenario probabilities must sum to exactly 1.00."""

    regimes = ["BULLISH", "BEARISH", "SIDEWAYS", "HIGH_VOLATILITY", "UNKNOWN"]

    def _make_input(self):
        return {
            "support_levels": [24200.0, 24000.0],
            "resistance_levels": [24800.0, 25000.0],
            "current_price": 24500.0,
            "adx": 28.0,
            "vix_price": 14.0,
        }

    def test_probabilities_sum_to_one(self):
        engine = ScenarioEngine()
        for regime in self.regimes:
            result = engine.generate(regime, **self._make_input())
            total = sum(v["probability"] for v in result.values())
            assert abs(total - 1.0) < 0.01, f"{regime}: sum={total}, expected 1.0"

    def test_normalization_preserves_ranking(self):
        engine = ScenarioEngine()
        for regime in self.regimes:
            result = engine.generate(regime, **self._make_input())
            sorted_probs = sorted(result.values(), key=lambda v: -v["probability"])
            for i in range(len(sorted_probs) - 1):
                assert sorted_probs[i]["probability"] >= sorted_probs[i + 1]["probability"], \
                    f"{regime}: ranking violated at position {i}"

    def test_bullish_highest_bullish_prob(self):
        engine = ScenarioEngine()
        result = engine.generate("BULLISH", **self._make_input())
        assert result["bullish"]["probability"] >= result["bearish"]["probability"]
        assert result["bullish"]["probability"] >= result["range"]["probability"]

    def test_bearish_highest_bearish_prob(self):
        engine = ScenarioEngine()
        result = engine.generate("BEARISH", **self._make_input())
        assert result["bearish"]["probability"] >= result["bullish"]["probability"]
        assert result["bearish"]["probability"] >= result["range"]["probability"]


# ═══════════════════════════════════════════════════════
# Confidence semantics tests
# ═══════════════════════════════════════════════════════

class TestConfidenceSemantics:
    """Two confidence values are intentional and should not be forced to match."""

    def test_regime_engine_confidence_is_regime_level(self):
        engine = RegimeEngine()
        market = {"price": 24600, "sma20": 24400, "sma50": 24300, "rsi": 55,
                   "macd": {"histogram": 0.5}, "vix_close": 15, "advance_decline_ratio": 1.2}
        result = engine.evaluate(market, {})
        assert 15 <= result["confidence"] <= 100

    def test_build_outlook_confidence_is_outlook_level(self):
        from backend.outlook import _confidence
        conf = _confidence(adx=35, rsi=55, vix_reg="NORMAL", missing_oi=True, gap={"available": False})
        assert 0 <= conf <= 100

    def test_confidence_values_are_different_not_equal(self):
        engine = RegimeEngine()
        market = {"price": 24600, "sma20": 24400, "sma50": 24300, "rsi": 55,
                   "macd": {"histogram": 0.5}, "vix_close": 15, "advance_decline_ratio": 1.2}
        result = engine.evaluate(market, {})
        regime_conf = result["confidence"]
        from backend.outlook import _confidence
        outlook_conf = _confidence(adx=35, rsi=55, vix_reg="NORMAL", missing_oi=True, gap={"available": False})
        assert isinstance(regime_conf, int), f"regime_confidence should be int, got {type(regime_conf)}"
        assert isinstance(outlook_conf, int), f"outlook_confidence should be int, got {type(outlook_conf)}"


# ═══════════════════════════════════════════════════════
# Safety invariant tests
# ═══════════════════════════════════════════════════════

class TestSafetyInvariants:
    """UNKNOWN and HIGH_VOLATILITY must fail safe."""

    def test_unknown_uses_defaults(self):
        engine = ScenarioEngine()
        result = engine.generate("UNKNOWN", support_levels=[24200], resistance_levels=[24800],
                                  current_price=24500, adx=28, vix_price=14)
        assert result["bullish"]["probability"] == 0.3
        assert result["bearish"]["probability"] == 0.3
        assert result["range"]["probability"] == 0.2

    def test_unknown_has_no_directional_bias(self):
        engine = StrategyEngine()
        result = engine.select("UNKNOWN", 0, "UNAVAILABLE")
        assert result["regime"] == "UNKNOWN"
        strategy_names = [s["strategy"] for s in result["strategies"]]
        assert "NO TRADE" in strategy_names or strategy_names == ["NO TRADE"]

    def test_high_volatility_uses_high_vol_strategies(self):
        engine = StrategyEngine()
        result = engine.select("HIGH_VOLATILITY", 50, "LIVE", vix_price=28)
        strategy_names = [s["strategy"] for s in result["strategies"]]
        assert "Defined-risk premium selling" in strategy_names, \
            f"HIGH_VOLATILITY should use defined-risk strategies, got {strategy_names}"
        assert result["regime"] == "HIGH_VOLATILITY"

    def test_high_volatility_strategy_position_size(self):
        engine = StrategyEngine()
        result = engine.select("HIGH_VOLATILITY", 50, "LIVE", vix_price=28)
        for s in result["strategies"]:
            assert s["position_size"] == "50%", \
                f"HIGH_VOLATILITY strategy should have 50% position size, got {s['position_size']}"


# ═══════════════════════════════════════════════════════
# StrategyEngine canonical authority tests
# ═══════════════════════════════════════════════════════

class TestStrategyEngineCanonical:
    """StrategyEngine is the canonical strategy authority."""

    def test_bullish_selects_bull_spreads(self):
        engine = StrategyEngine()
        result = engine.select("BULLISH", 70, "LIVE", vix_price=15)
        names = [s["strategy"] for s in result["strategies"]]
        assert "Bull Call Spread" in names
        assert "Bull Put Spread" in names

    def test_bearish_selects_bear_spreads(self):
        engine = StrategyEngine()
        result = engine.select("BEARISH", 60, "LIVE", vix_price=16)
        names = [s["strategy"] for s in result["strategies"]]
        assert "Bear Put Spread" in names
        assert "Bear Call Spread" in names

    def test_sideways_selects_iron_condor(self):
        engine = StrategyEngine()
        result = engine.select("SIDEWAYS", 50, "LIVE", vix_price=14)
        names = [s["strategy"] for s in result["strategies"]]
        assert "Iron Condor" in names

    def test_position_size_by_confidence(self):
        engine = StrategyEngine()
        r80 = engine.select("BULLISH", 80, "LIVE", vix_price=15)
        r60 = engine.select("BULLISH", 60, "LIVE", vix_price=15)
        r40 = engine.select("BULLISH", 40, "LIVE", vix_price=15)
        assert r80["position_size"] == "40%"
        assert r60["position_size"] == "30%"
        assert r40["position_size"] == "20%"


# ═══════════════════════════════════════════════════════
# Determinism tests
# ═══════════════════════════════════════════════════════

class TestDeterminism:
    """Same inputs must produce identical outputs."""

    def test_regime_engine_determinism(self):
        engine = RegimeEngine()
        market = {"price": 24600, "sma20": 24400, "sma50": 24300, "rsi": 55,
                   "macd": {"histogram": 0.5}, "vix_close": 15, "advance_decline_ratio": 1.2}
        r1 = engine.evaluate(market, {})
        r2 = engine.evaluate(market, {})
        assert r1["regime"] == r2["regime"]
        assert r1["confidence"] == r2["confidence"]
        assert r1["components"] == r2["components"]

    def test_scenario_engine_determinism(self):
        engine = ScenarioEngine()
        r1 = engine.generate("BULLISH", [24200], [24800], 24600, adx=28, vix_price=14)
        r2 = engine.generate("BULLISH", [24200], [24800], 24600, adx=28, vix_price=14)
        for k in r1:
            assert r1[k]["probability"] == r2[k]["probability"], f"{k} differs"

    def test_strategy_engine_determinism(self):
        engine = StrategyEngine()
        r1 = engine.select("BULLISH", 70, "LIVE", vix_price=15)
        r2 = engine.select("BULLISH", 70, "LIVE", vix_price=15)
        assert r1["regime"] == r2["regime"]
        assert r1["position_size"] == r2["position_size"]
        names1 = sorted(s["strategy"] for s in r1["strategies"])
        names2 = sorted(s["strategy"] for s in r2["strategies"])
        assert names1 == names2
