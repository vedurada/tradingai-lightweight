#!/usr/bin/env python3
"""Regression tests for RegimeEngine (PHASE 5 STEP 2).

Covers the approved 18-test matrix plus determinism and no-LLM verification.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.regime import RegimeEngine


def make_market(**overrides):
    base = {
        "symbol": "NIFTY",
        "price": 24500.0,
        "sma20": 24350.0,
        "sma50": 24100.0,
        "prev_close": 24400.0,
        "rsi": 58.5,
        "macd": {"histogram": 12.3},
        "adx": 28.0,
        "vix_close": 14.2,
        "vix_change_pct": 1.5,
        "advances": 2150,
        "declines": 1200,
        "advance_decline_ratio": 1.79,
    }
    base.update(overrides)
    return base


def make_options(**overrides):
    base = {"pcr": 0.45}
    base.update(overrides)
    return base


# ── Test 1: Clear bullish ────────────────────────────────────────────────
def test_clear_bullish():
    engine = RegimeEngine()
    result = engine.evaluate(make_market(), make_options())
    assert result["regime"] == "BULLISH", f"Expected BULLISH, got {result['regime']}"
    assert result["confidence"] >= 75, f"Confidence too low: {result['confidence']}"
    assert result["components"]["trend"] == "BULLISH"
    assert result["components"]["momentum"] == "BULLISH"
    assert result["components"]["options"] == "BULLISH"
    assert "SMA20" in result["reasons"][0]


# ── Test 2: Clear bearish ────────────────────────────────────────────────
def test_clear_bearish():
    engine = RegimeEngine()
    result = engine.evaluate(
        make_market(price=23500.0, sma20=23800.0, sma50=24000.0, rsi=38.0,
                     macd={"histogram": -8.5}, advances=1200, declines=2150,
                     advance_decline_ratio=0.56),
        make_options(pcr=2.0),
    )
    assert result["regime"] == "BEARISH", f"Expected BEARISH, got {result['regime']}"
    assert result["confidence"] >= 75, f"Confidence too low: {result['confidence']}"
    assert result["components"]["trend"] == "BEARISH"
    assert result["components"]["momentum"] == "BEARISH"
    assert result["components"]["options"] == "BEARISH"


# ── Test 3: Sideways ─────────────────────────────────────────────────────
def test_sideways():
    engine = RegimeEngine()
    result = engine.evaluate(
        make_market(price=24350.0, sma20=24350.0, sma50=24100.0, rsi=55.0,
                     macd={"histogram": -5.0}, advances=1500, declines=1400,
                     advance_decline_ratio=1.07),
        make_options(pcr=1.0),
    )
    assert result["regime"] == "SIDEWAYS", f"Expected SIDEWAYS, got {result['regime']}"


# ── Test 4: High volatility (VIX >= 25 EXTREME) ──────────────────────────
def test_high_volatility_extreme():
    engine = RegimeEngine()
    result = engine.evaluate(make_market(vix_close=28.0), make_options())
    assert result["regime"] == "HIGH_VOLATILITY", f"Expected HIGH_VOLATILITY, got {result['regime']}"
    assert result["confidence"] <= 60, f"Confidence should be capped at 60, got {result['confidence']}"


# ── Test 5: High volatility (VIX >= 20 directional conflict) ─────────────
def test_high_volatility_conflict():
    engine = RegimeEngine()
    result = engine.evaluate(
        make_market(vix_close=22.0, sma20=24350.0, sma50=24100.0, price=23500.0,
                     rsi=38.0, macd={"histogram": -8.5}),
        make_options(),
    )
    assert result["regime"] == "HIGH_VOLATILITY", f"Expected HIGH_VOLATILITY, got {result['regime']}"


# ── Test 6: High volatility (VIX >= 20 all directional agree) ────────────
def test_high_volatility_aligned():
    engine = RegimeEngine()
    result = engine.evaluate(make_market(vix_close=22.0), make_options())
    assert result["regime"] == "HIGH_VOLATILITY", f"Expected HIGH_VOLATILITY, got {result['regime']}"
    assert result["confidence"] <= 60, f"Confidence should be capped at 60, got {result['confidence']}"


# ── Test 7: Missing VIX ──────────────────────────────────────────────────
def test_missing_vix():
    engine = RegimeEngine()
    result = engine.evaluate(make_market(vix_close=None), make_options())
    assert result["regime"] != "HIGH_VOLATILITY", "Should not be HIGH_VOLATILITY without VIX data"
    assert result["components"]["vix"] == "UNAVAILABLE", f"VIX should be UNAVAILABLE, got {result['components']['vix']}"
    assert result["data_quality"] in ("LIVE", "PARTIAL"), f"Data quality should not be UNAVAILABLE, got {result['data_quality']}"


# ── Test 8: Missing breadth ──────────────────────────────────────────────
def test_missing_breadth():
    engine = RegimeEngine()
    result = engine.evaluate(make_market(advances=None, declines=None, advance_decline_ratio=None), make_options())
    assert result["components"]["breadth"] == "UNAVAILABLE", f"Breadth should be UNAVAILABLE, got {result['components']['breadth']}"
    assert len([r for r in result["reasons"] if "Breadth" in r]) == 0, "Should not have breadth reason"


# ── Test 9: Missing options data ─────────────────────────────────────────
def test_missing_options():
    engine = RegimeEngine()
    result = engine.evaluate(make_market(), make_options(pcr=None))
    assert result["components"]["options"] == "UNAVAILABLE", f"Options should be UNAVAILABLE, got {result['components']['options']}"
    assert len([r for r in result["reasons"] if "Options" in r]) == 0, "Should not have options reason"


# ── Test 10: Missing all optional (UNAVAILABLE data quality) ──────────────
def test_missing_all_optional():
    engine = RegimeEngine()
    result = engine.evaluate(
        make_market(price=None, sma20=None, sma50=None, prev_close=None, rsi=None,
                     macd=None, adx=None, vix_close=None, vix_change_pct=None,
                     advances=None, declines=None, advance_decline_ratio=None),
        make_options(pcr=None),
    )
    assert result["data_quality"] == "UNAVAILABLE", f"Expected UNAVAILABLE, got {result['data_quality']}"
    assert result["regime"] == "SIDEWAYS", f"Expected SIDEWAYS with no data, got {result['regime']}"
    assert result["confidence"] == 15, f"Expected confidence 15, got {result['confidence']}"


# ── Test 11: Conflicting indicators ──────────────────────────────────────
def test_conflicting_indicators():
    engine = RegimeEngine()
    result = engine.evaluate(
        make_market(price=24500.0, sma20=24350.0, sma50=24100.0, rsi=38.0,
                     macd={"histogram": -8.5}),
        make_options(),
    )
    trend = result["components"]["trend"]
    momentum = result["components"]["momentum"]
    assert trend != momentum, f"Trend ({trend}) and momentum ({momentum}) should conflict"
    assert result["regime"] in ("SIDEWAYS", "HIGH_VOLATILITY"), f"Expected SIDEWAYS or HIGH_VOLATILITY, got {result['regime']}"


# ── Test 12: VIX boundary (exactly 20 → HIGH) ────────────────────────────
def test_vix_boundary_high():
    engine = RegimeEngine()
    result = engine.evaluate(make_market(vix_close=20.0), make_options())
    assert result["components"]["vix"] == "HIGH", f"VIX should be HIGH, got {result['components']['vix']}"
    assert result["regime"] == "HIGH_VOLATILITY", f"Expected HIGH_VOLATILITY, got {result['regime']}"


# ── Test 13: VIX boundary (19.99 → ELEVATED → directional) ──────────────
def test_vix_boundary_elevated():
    engine = RegimeEngine()
    result = engine.evaluate(make_market(vix_close=19.99), make_options())
    assert result["components"]["vix"] == "ELEVATED", f"VIX should be ELEVATED, got {result['components']['vix']}"
    assert result["regime"] != "HIGH_VOLATILITY", f"Should not be HIGH_VOLATILITY at VIX {result['components']['vix']}"


# ── Test 14: RSI boundary (exactly 50 → BULLISH) ────────────────────────
def test_rsi_boundary_bullish():
    engine = RegimeEngine()
    result = engine.evaluate(make_market(rsi=50.0, macd={"histogram": 0.0}), make_options())
    assert result["components"]["momentum"] == "BULLISH", f"RSI 50 should be BULLISH, got {result['components']['momentum']}"


# ── Test 15: PCR boundary (exactly 0.7 → NEUTRAL) ───────────────────────
def test_pcr_boundary_neutral_low():
    engine = RegimeEngine()
    result = engine.evaluate(make_market(), make_options(pcr=0.7))
    assert result["components"]["options"] == "NEUTRAL", f"PCR 0.7 should be NEUTRAL, got {result['components']['options']}"


# ── Test 16: PCR boundary (exactly 1.5 → NEUTRAL) ───────────────────────
def test_pcr_boundary_neutral_high():
    engine = RegimeEngine()
    result = engine.evaluate(make_market(), make_options(pcr=1.5))
    assert result["components"]["options"] == "NEUTRAL", f"PCR 1.5 should be NEUTRAL, got {result['components']['options']}"


# ── Test 17: Deterministic repeated execution ────────────────────────────
def test_deterministic():
    engine = RegimeEngine()
    market = make_market()
    options = make_options()
    r1 = engine.evaluate(market, options)
    r2 = engine.evaluate(market, options)
    assert r1["regime"] == r2["regime"], "Regime should be identical"
    assert r1["confidence"] == r2["confidence"], "Confidence should be identical"
    assert r1["components"] == r2["components"], "Components should be identical"
    assert r1["reasons"] == r2["reasons"], "Reasons should be identical"


# ── Test 18: ADX boost excluded during HIGH_VOLATILITY ──────────────────
def test_adx_boost_excluded_during_high_vol():
    engine = RegimeEngine()
    result_high_vol = engine.evaluate(make_market(vix_close=22.0, adx=35.0), make_options())
    assert result_high_vol["regime"] == "HIGH_VOLATILITY"
    assert result_high_vol["confidence"] <= 60, f"HIGH_VOLATILITY confidence should be capped at 60, got {result_high_vol['confidence']}"

    result_directional = engine.evaluate(make_market(vix_close=14.2, adx=35.0), make_options())
    assert result_directional["regime"] == "BULLISH", f"Expected BULLISH with ADX 35 and normal VIX, got {result_directional['regime']}"
    assert result_directional["confidence"] > result_high_vol["confidence"], "Directional regime with ADX boost should have higher confidence than HIGH_VOLATILITY"


# ── Bonus: No LLM or randomness ──────────────────────────────────────────
def test_no_llm_or_randomness():
    engine = RegimeEngine()
    import inspect
    source = inspect.getsource(engine.evaluate)
    assert "import random" not in source, "evaluate() should not import random"
    assert "random." not in source, "evaluate() should not use random"
    assert "llm" not in source.lower(), "evaluate() should not reference LLM"
    assert "openai" not in source.lower(), "evaluate() should not reference OpenAI"


# ── Bonus: VIX < 20 with strong unidirectional alignment → directional ──
def test_vix_below_20_strong_bullish():
    engine = RegimeEngine()
    result = engine.evaluate(make_market(vix_close=18.0), make_options())
    assert result["regime"] == "BULLISH", f"Expected BULLISH with VIX 18 and all components bullish, got {result['regime']}"
    assert result["regime"] != "HIGH_VOLATILITY"


if __name__ == "__main__":
    tests = [
        test_clear_bullish, test_clear_bearish, test_sideways,
        test_high_volatility_extreme, test_high_volatility_conflict, test_high_volatility_aligned,
        test_missing_vix, test_missing_breadth, test_missing_options, test_missing_all_optional,
        test_conflicting_indicators, test_vix_boundary_high, test_vix_boundary_elevated,
        test_rsi_boundary_bullish, test_pcr_boundary_neutral_low, test_pcr_boundary_neutral_high,
        test_deterministic, test_adx_boost_excluded_during_high_vol,
        test_no_llm_or_randomness, test_vix_below_20_strong_bullish,
    ]
    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS: {t.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"FAIL: {t.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"ERROR: {t.__name__}: {type(e).__name__}: {e}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed out of {len(tests)} tests")
    if failed > 0:
        sys.exit(1)
