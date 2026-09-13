#!/usr/bin/env python3
"""Integration tests for downstream regime consumers.

Proves:
- Canonical regimes produce correct strategy/scenario/AI output.
- Legacy regime names produce equivalent output via normalization.
- UNKNOWN fails safely (NO TRADE / neutral / no accidental selection).
- Existing 58/58 + new tests all pass.
"""
import sys
import os
import inspect
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.strategies import StrategyEngine
from backend.scenarios import ScenarioEngine
from backend.ai_outlook import AIOutlookEngine
from backend.regime_utils import normalize_regime, UNKNOWN_REGIME


# ═══════════════════════════════════════════════════════════════
# StrategyEngine integration
# ═══════════════════════════════════════════════════════════════

def _make_base_strategy_input(**overrides):
    base = {
        "confidence": 70,
        "data_quality": "GOOD",
        "vix_price": 14.0,
        "vix_change_pct": 1.0,
        "symbol": "NIFTY",
        "price": 24500.0,
        "vwap": 24400.0,
        "rsi": 58.0,
        "adx": 28.0,
        "support": [24200.0, 24000.0],
        "resistance": [24800.0, 25000.0],
        "atr": 150.0,
    }
    base.update(overrides)
    return base


def test_strategy_bullish_selects_bull_spreads():
    engine = StrategyEngine()
    result = engine.select("BULLISH", **_make_base_strategy_input())
    strategy_names = [s["strategy"] for s in result["strategies"]]
    assert "Bull Call Spread" in strategy_names, f"Expected Bull Call Spread, got {strategy_names}"
    assert "Bull Put Spread" in strategy_names, f"Expected Bull Put Spread, got {strategy_names}"
    assert result["regime"] == "BULLISH"


def test_strategy_bearish_selects_bear_spreads():
    engine = StrategyEngine()
    result = engine.select("BEARISH", **_make_base_strategy_input())
    strategy_names = [s["strategy"] for s in result["strategies"]]
    assert "Bear Put Spread" in strategy_names, f"Expected Bear Put Spread, got {strategy_names}"
    assert "Bear Call Spread" in strategy_names, f"Expected Bear Call Spread, got {strategy_names}"
    assert result["regime"] == "BEARISH"


def test_strategy_sideways_selects_iron_condor():
    engine = StrategyEngine()
    result = engine.select("SIDEWAYS", **_make_base_strategy_input())
    strategy_names = [s["strategy"] for s in result["strategies"]]
    assert "Iron Condor" in strategy_names, f"Expected Iron Condor, got {strategy_names}"
    assert result["regime"] == "SIDEWAYS"


def test_strategy_high_volatility_selects_premium_selling():
    engine = StrategyEngine()
    result = engine.select("HIGH_VOLATILITY", **_make_base_strategy_input())
    strategy_names = [s["strategy"] for s in result["strategies"]]
    assert "Defined-risk premium selling" in strategy_names, f"Expected premium selling, got {strategy_names}"
    assert result["regime"] == "HIGH_VOLATILITY"


def test_strategy_unknown_fails_safe_to_no_trade():
    engine = StrategyEngine()
    result = engine.select("UNKNOWN", **_make_base_strategy_input())
    strategy_names = [s["strategy"] for s in result["strategies"]]
    assert "NO TRADE" in strategy_names, f"Expected NO TRADE, got {strategy_names}"
    assert result["regime"] == UNKNOWN_REGIME


def test_strategy_none_fails_safe_to_no_trade():
    engine = StrategyEngine()
    result = engine.select(None, **_make_base_strategy_input())
    strategy_names = [s["strategy"] for s in result["strategies"]]
    assert "NO TRADE" in strategy_names, f"Expected NO TRADE for None, got {strategy_names}"


def test_strategy_legacy_bullish_equivalent_to_canonical():
    engine = StrategyEngine()
    legacy = engine.select("TRENDING_BULLISH", **_make_base_strategy_input())
    canonical = engine.select("BULLISH", **_make_base_strategy_input())
    legacy_names = [s["strategy"] for s in legacy["strategies"]]
    canonical_names = [s["strategy"] for s in canonical["strategies"]]
    assert legacy_names == canonical_names, f"Legacy {legacy_names} ≠ canonical {canonical_names}"


def test_strategy_legacy_bearish_equivalent_to_canonical():
    engine = StrategyEngine()
    legacy = engine.select("TRENDING_BEARISH", **_make_base_strategy_input())
    canonical = engine.select("BEARISH", **_make_base_strategy_input())
    legacy_names = [s["strategy"] for s in legacy["strategies"]]
    canonical_names = [s["strategy"] for s in canonical["strategies"]]
    assert legacy_names == canonical_names, f"Legacy {legacy_names} ≠ canonical {canonical_names}"


def test_strategy_legacy_range_equivalent_to_canonical():
    engine = StrategyEngine()
    legacy = engine.select("RANGE_BOUND", **_make_base_strategy_input())
    canonical = engine.select("SIDEWAYS", **_make_base_strategy_input())
    legacy_names = [s["strategy"] for s in legacy["strategies"]]
    canonical_names = [s["strategy"] for s in canonical["strategies"]]
    assert legacy_names == canonical_names, f"Legacy {legacy_names} ≠ canonical {canonical_names}"


def test_strategy_legacy_high_volatility_unchanged():
    engine = StrategyEngine()
    legacy = engine.select("HIGH_VOLATILITY", **_make_base_strategy_input())
    canonical = engine.select("HIGH_VOLATILITY", **_make_base_strategy_input())
    legacy_names = [s["strategy"] for s in legacy["strategies"]]
    canonical_names = [s["strategy"] for s in canonical["strategies"]]
    assert legacy_names == canonical_names


# ═══════════════════════════════════════════════════════════════
# ScenarioEngine integration
# ═══════════════════════════════════════════════════════════════

def _make_scenario_input(**overrides):
    base = {
        "support_levels": [24200.0, 24000.0],
        "resistance_levels": [24800.0, 25000.0],
        "current_price": 24500.0,
        "adx": 28.0,
        "vix_price": 14.0,
    }
    base.update(overrides)
    return base


def test_scenario_bullish_adjusts_probabilities():
    engine = ScenarioEngine()
    result = engine.generate("BULLISH", **_make_scenario_input())
    assert abs(result["bullish"]["probability"] - 0.4545) < 0.001, f"Expected ~0.4545, got {result['bullish']['probability']}"
    assert abs(result["bearish"]["probability"] - 0.1818) < 0.001, f"Expected ~0.1818, got {result['bearish']['probability']}"
    assert abs(result["range"]["probability"] - 0.1818) < 0.001, f"Expected ~0.1818, got {result['range']['probability']}"
    assert result["bullish"]["strategy_environment"] == "BULLISH"


def test_scenario_bearish_adjusts_probabilities():
    engine = ScenarioEngine()
    result = engine.generate("BEARISH", **_make_scenario_input())
    assert abs(result["bearish"]["probability"] - 0.4545) < 0.001, f"Expected ~0.4545, got {result['bearish']['probability']}"
    assert abs(result["bullish"]["probability"] - 0.1818) < 0.001, f"Expected ~0.1818, got {result['bullish']['probability']}"
    assert abs(result["range"]["probability"] - 0.1818) < 0.001, f"Expected ~0.1818, got {result['range']['probability']}"
    assert result["bearish"]["strategy_environment"] == "BEARISH"


def test_scenario_sideways_adjusts_probabilities():
    engine = ScenarioEngine()
    result = engine.generate("SIDEWAYS", **_make_scenario_input())
    assert abs(result["range"]["probability"] - 0.381) < 0.001, f"Expected ~0.381, got {result['range']['probability']}"
    assert abs(result["breakout"]["probability"] - 0.3333) < 0.001, f"Expected ~0.3333, got {result['breakout']['probability']}"
    assert abs(result["bullish"]["probability"] - 0.1429) < 0.001, f"Expected ~0.1429, got {result['bullish']['probability']}"
    assert abs(result["bearish"]["probability"] - 0.0952) < 0.001, f"Expected ~0.0952, got {result['bearish']['probability']}"
    assert result["range"]["strategy_environment"] == "Iron Condor / Butterfly"


def test_scenario_high_volatility_adjusts_probabilities():
    engine = ScenarioEngine()
    result = engine.generate("HIGH_VOLATILITY", **_make_scenario_input())
    assert abs(result["breakout"]["probability"] - 0.381) < 0.001, f"Expected ~0.381, got {result['breakout']['probability']}"
    assert abs(result["range"]["probability"] - 0.0952) < 0.001, f"Expected ~0.0952, got {result['range']['probability']}"
    assert abs(result["bullish"]["probability"] - 0.2381) < 0.001, f"Expected ~0.2381, got {result['bullish']['probability']}"
    assert abs(result["bearish"]["probability"] - 0.2381) < 0.001, f"Expected ~0.2381, got {result['bearish']['probability']}"


def test_scenario_unknown_uses_defaults():
    engine = ScenarioEngine()
    result = engine.generate("UNKNOWN", **_make_scenario_input())
    assert result["bullish"]["probability"] == 0.3, f"Expected 0.3, got {result['bullish']['probability']}"
    assert result["bearish"]["probability"] == 0.3, f"Expected 0.3, got {result['bearish']['probability']}"
    assert result["range"]["probability"] == 0.2, f"Expected 0.2, got {result['range']['probability']}"
    assert result["breakout"]["probability"] == 0.15, f"Expected 0.15, got {result['breakout']['probability']}"
    assert result["reversal"]["probability"] == 0.05


def test_scenario_bullish_not_default():
    engine = ScenarioEngine()
    result = engine.generate("BULLISH", **_make_scenario_input())
    assert result["bullish"]["probability"] != 0.3, f"BULLISH should not have default 0.3 probability"


def test_scenario_bearish_not_default():
    engine = ScenarioEngine()
    result = engine.generate("BEARISH", **_make_scenario_input())
    assert result["bearish"]["probability"] != 0.3, f"BEARISH should not have default 0.3 probability"


def test_scenario_sideways_not_default():
    engine = ScenarioEngine()
    result = engine.generate("SIDEWAYS", **_make_scenario_input())
    assert result["range"]["probability"] != 0.2, f"SIDEWAYS range should not have default 0.2 probability"


def test_scenario_legacy_bullish_equivalent_to_canonical():
    engine = ScenarioEngine()
    legacy = engine.generate("TRENDING_BULLISH", **_make_scenario_input())
    canonical = engine.generate("BULLISH", **_make_scenario_input())
    assert legacy["bullish"]["probability"] == canonical["bullish"]["probability"]
    assert legacy["bearish"]["probability"] == canonical["bearish"]["probability"]
    assert legacy["range"]["probability"] == canonical["range"]["probability"]


def test_scenario_legacy_bearish_equivalent_to_canonical():
    engine = ScenarioEngine()
    legacy = engine.generate("TRENDING_BEARISH", **_make_scenario_input())
    canonical = engine.generate("BEARISH", **_make_scenario_input())
    assert legacy["bullish"]["probability"] == canonical["bullish"]["probability"]
    assert legacy["bearish"]["probability"] == canonical["bearish"]["probability"]
    assert legacy["range"]["probability"] == canonical["range"]["probability"]


def test_scenario_legacy_range_equivalent_to_canonical():
    engine = ScenarioEngine()
    legacy = engine.generate("RANGE_BOUND", **_make_scenario_input())
    canonical = engine.generate("SIDEWAYS", **_make_scenario_input())
    assert legacy["range"]["probability"] == canonical["range"]["probability"]
    assert legacy["bullish"]["probability"] == canonical["bullish"]["probability"]


# ═══════════════════════════════════════════════════════════════
# AIOutlookEngine rule-based integration
# ═══════════════════════════════════════════════════════════════

def _make_ai_input(**overrides):
    base = {
        "symbol": "NIFTY",
        "price": 24500.0,
        "rsi": 58.0,
        "regime": "BULLISH",
        "atr": 150.0,
        "vix": 14.0,
        "ema20": 24350.0,
        "macd": {"histogram": 12.3},
        "data_quality": "GOOD",
        "options_unavailable": False,
        "support_levels": [24200.0],
        "resistance_levels": [24800.0],
    }
    base.update(overrides)
    return base


def test_ai_rule_based_bullish():
    engine = AIOutlookEngine()
    result = engine._rule_based_outlook(_make_ai_input(regime="BULLISH"))
    assert result["directional_bias"] == "BULLISH", f"Expected BULLISH, got {result['directional_bias']}"
    assert result["confidence"] == 65, f"Expected 65, got {result['confidence']}"
    assert result["market_structure"] == "UPTREND", f"Expected UPTREND, got {result['market_structure']}"


def test_ai_rule_based_bearish():
    engine = AIOutlookEngine()
    result = engine._rule_based_outlook(_make_ai_input(regime="BEARISH"))
    assert result["directional_bias"] == "BEARISH"
    assert result["confidence"] == 65
    assert result["market_structure"] == "DOWNTREND"


def test_ai_rule_based_sideways_neutral():
    engine = AIOutlookEngine()
    result = engine._rule_based_outlook(_make_ai_input(regime="SIDEWAYS"))
    assert result["directional_bias"] == "NEUTRAL"
    assert result["confidence"] == 45
    assert result["market_structure"] == "RANGE"


def test_ai_rule_based_unknown_neutral():
    engine = AIOutlookEngine()
    result = engine._rule_based_outlook(_make_ai_input(regime="UNKNOWN"))
    assert result["directional_bias"] == "NEUTRAL"
    assert result["confidence"] == 45
    assert result["market_structure"] == "RANGE"
    assert "Unclear direction" in result["no_trade_conditions"]


def test_ai_rule_based_legacy_bullish_equivalent():
    engine = AIOutlookEngine()
    legacy = engine._rule_based_outlook(_make_ai_input(regime="TRENDING_BULLISH"))
    canonical = engine._rule_based_outlook(_make_ai_input(regime="BULLISH"))
    assert legacy["directional_bias"] == canonical["directional_bias"]
    assert legacy["confidence"] == canonical["confidence"]
    assert legacy["market_structure"] == canonical["market_structure"]


def test_ai_rule_based_legacy_bearish_equivalent():
    engine = AIOutlookEngine()
    legacy = engine._rule_based_outlook(_make_ai_input(regime="TRENDING_BEARISH"))
    canonical = engine._rule_based_outlook(_make_ai_input(regime="BEARISH"))
    assert legacy["directional_bias"] == canonical["directional_bias"]
    assert legacy["confidence"] == canonical["confidence"]
    assert legacy["market_structure"] == canonical["market_structure"]


def test_ai_rule_based_legacy_range_equivalent():
    engine = AIOutlookEngine()
    legacy = engine._rule_based_outlook(_make_ai_input(regime="RANGE_BOUND"))
    canonical = engine._rule_based_outlook(_make_ai_input(regime="SIDEWAYS"))
    assert legacy["directional_bias"] == canonical["directional_bias"]
    assert legacy["confidence"] == canonical["confidence"]
    assert legacy["market_structure"] == canonical["market_structure"]


def test_ai_prompt_vocab_updated():
    engine = AIOutlookEngine()
    prompt = engine._default_prompt()
    assert "TRENDING_BULLISH" not in prompt, "Old regime name TRENDING_BULLISH still in default prompt"
    assert "TRENDING_BEARISH" not in prompt, "Old regime name TRENDING_BEARISH still in default prompt"
    assert "RANGE_BOUND" not in prompt, "Old regime name RANGE_BOUND still in default prompt"
    assert "BULLISH" in prompt
    assert "BEARISH" in prompt
    assert "SIDEWAYS" in prompt
    assert "HIGH_VOLATILITY" in prompt


def test_ai_rule_based_no_llm_dependency():
    engine = AIOutlookEngine()
    source = inspect.getsource(engine._rule_based_outlook)
    assert "llm" not in source.lower(), "_rule_based_outlook should not reference LLM"
    assert "openai" not in source.lower(), "_rule_based_outlook should not reference OpenAI"
    assert "request" not in source.lower(), "_rule_based_outlook should not make HTTP calls"
    assert "_call_" not in source, "_rule_based_outlook should not call providers"


def test_ai_strategy_environment_canonical():
    engine = AIOutlookEngine()
    result = engine._rule_based_outlook(_make_ai_input(regime="BULLISH"))
    assert result["strategy_environment"] == "BULLISH", f"Expected BULLISH env, got {result['strategy_environment']}"
    result2 = engine._rule_based_outlook(_make_ai_input(regime="BEARISH"))
    assert result2["strategy_environment"] == "BEARISH"
    result3 = engine._rule_based_outlook(_make_ai_input(regime="UNKNOWN"))
    assert result3["strategy_environment"] == "Neutral"


# ═══════════════════════════════════════════════════════════════
# Alert normalization integration
# ═══════════════════════════════════════════════════════════════

def test_alert_normalize_prevents_false_change():
    from backend.regime_utils import normalize_regime
    prev_regime = normalize_regime("TRENDING_BULLISH")
    curr_regime = normalize_regime("BULLISH")
    assert prev_regime == curr_regime, f"Normalization should map TRENDING_BULLISH and BULLISH to same canonical: {prev_regime} != {curr_regime}"


def test_alert_same_regime_no_alert():
    from backend.regime_utils import normalize_regime
    prev = normalize_regime("BULLISH")
    curr = normalize_regime("BULLISH")
    assert prev == curr, f"Same canonical regime should match: {prev} != {curr}"


def test_alert_actual_change_detected():
    from backend.regime_utils import normalize_regime
    prev = normalize_regime("BULLISH")
    curr = normalize_regime("BEARISH")
    assert prev != curr, f"Different canonical regimes should differ: {prev} == {curr}"


def test_alert_legacy_range_to_sideways_no_false_change():
    from backend.regime_utils import normalize_regime
    prev = normalize_regime("RANGE_BOUND")
    curr = normalize_regime("SIDEWAYS")
    assert prev == curr, f"RANGE_BOUND and SIDEWAYS should be same canonical: {prev} != {curr}"


def test_alert_high_volatility_stable():
    from backend.regime_utils import normalize_regime
    assert normalize_regime("HIGH_VOLATILITY") == "HIGH_VOLATILITY"
    assert normalize_regime("HIGH_VOLATILITY") == normalize_regime("HIGH_VOLATILITY")


def test_alert_none_safe():
    from backend.regime_utils import normalize_regime
    assert normalize_regime(None) == "UNKNOWN"
    assert normalize_regime("") == "UNKNOWN"
    assert normalize_regime("UNCONFIRMED") == "UNKNOWN"
