#!/usr/bin/env python3
"""Tests for merge_llm_into_payload() — LLM boundary hardening (STEP 4A).

Proves:
- LLM CANNOT change regime, bias, confidence, key_levels, verdict, strategy.
- LLM CAN contribute primary_view (narrative) and llm_explanation (descriptive).
- Rule-based ai_outlook rows (market_summary contains 'analysis - ') are skipped.
- No LLM row → payload unchanged.
- Deterministic fields survive even when LLM explicitly tries to override.
"""
import sys
import os
import sqlite3
import json
import tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.outlook import merge_llm_into_payload


def _make_llm_outlook(**overrides):
    base = {
        "market_regime": "BEARISH",
        "directional_bias": "BEARISH",
        "confidence": 91,
        "market_summary": "LLM narrative: comprehensive market analysis complete",
        "trend_analysis": "Price below EMA20 and EMA50",
        "momentum_analysis": "RSI 38, MACD histogram negative",
        "volatility_analysis": "ATR elevated, VIX 22",
        "support_levels": [24100, 24000],
        "resistance_levels": [24800, 25000],
        "bullish_scenario": {"trigger": "break resistance", "confirmation": "volume surge", "target": "25000", "invalidation": "below 24600"},
        "bearish_scenario": {"trigger": "break support", "confirmation": "RSI divergence", "target": "24000", "invalidation": "above 24400"},
        "range_scenario": {"condition": "between support and resistance", "strategy_environment": "Iron Condor", "invalidation": "breakout"},
        "primary_strategy": {"strategy": "Bear Put Spread", "market_condition": "Bearish trend", "expiry": "NEXT_WEEKLY"},
        "alternative_strategies": [{"strategy": "Short Strangle"}],
        "intraday_plan": ["Wait for resistance rejection", "Enter on close confirmation"],
        "no_trade_conditions": ["Unclear direction", "Low liquidity"],
        "strategy_environment": "BEARISH",
        "invalidation": "Break of 24800",
        "risk_warnings": ["This is decision-support"],
        "data_quality": "GOOD",
        "generated_at": "2026-09-13T10:00:00",
    }
    base.update(overrides)
    return base


def _make_payload():
    return {
        "date": "2026-09-13",
        "symbol": "NIFTY",
        "regime": {"primary": "BULLISH", "engine": "BULLISH", "confidence": 72},
        "bias": {"label": "BULLISH", "probs": {"bullish": 50, "neutral": 30, "bearish": 20}},
        "confidence": 72,
        "expected_range": {"upper": 24750.0, "lower": 24250.0},
        "key_levels": {"supports": [24200.0], "resistances": [24800.0]},
        "decision": {"verdict": "TRADE", "primary_view": "Rule-based bullish view"},
        "strategies": [{"strategy": "Bull Call Spread", "fit": 78}],
    }


def _setup_db_with_llm(outlook_dict, timestamp="2026-09-13T12:00:00"):
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE ai_outlooks (
        symbol TEXT, timestamp TEXT, outlook TEXT, data_quality TEXT
    )""")
    conn.execute(
        "INSERT INTO ai_outlooks (symbol, timestamp, outlook, data_quality) VALUES (?,?,?,?)",
        ("NIFTY", timestamp, json.dumps(outlook_dict), "GOOD"),
    )
    conn.commit()
    return conn


# ═══════════════════════════════════════════════════════════════
# Core protection tests — LLM cannot override deterministic fields
# ═══════════════════════════════════════════════════════════════

def test_llm_cannot_override_regime():
    payload = _make_payload()
    original_regime = json.loads(json.dumps(payload["regime"]))
    original_bias = json.loads(json.dumps(payload["bias"]))
    original_confidence = payload["confidence"]
    original_key_levels = json.loads(json.dumps(payload["key_levels"]))

    llm = _make_llm_outlook(
        market_regime="BEARISH",
        directional_bias="BEARISH",
        confidence=91,
        support_levels=[99999],
        resistance_levels=[11111],
    )
    conn = _setup_db_with_llm(llm)
    merge_llm_into_payload(conn, "NIFTY", payload)
    conn.close()

    assert payload["regime"] == original_regime, f"Regime changed: {payload['regime']} != {original_regime}"
    assert payload["bias"] == original_bias, f"Bias changed: {payload['bias']} != {original_bias}"
    assert payload["confidence"] == original_confidence, f"Confidence changed: {payload['confidence']} != {original_confidence}"
    assert payload["key_levels"] == original_key_levels, f"Key levels changed: {payload['key_levels']} != {original_key_levels}"


def test_llm_cannot_override_verdict():
    payload = _make_payload()
    original_verdict = payload["decision"]["verdict"]

    llm = _make_llm_outlook(market_regime="BEARISH", directional_bias="BEARISH", confidence=91)
    conn = _setup_db_with_llm(llm)
    merge_llm_into_payload(conn, "NIFTY", payload)
    conn.close()

    assert payload["decision"]["verdict"] == original_verdict, f"Verdict changed: {payload['decision']['verdict']}"


def test_llm_cannot_override_strategy():
    payload = _make_payload()
    original_strategy = payload["strategies"][0]["strategy"]

    llm = _make_llm_outlook(market_regime="BEARISH", primary_strategy={"strategy": "BEAR PUT SPREAD"})
    conn = _setup_db_with_llm(llm)
    merge_llm_into_payload(conn, "NIFTY", payload)
    conn.close()

    assert payload["strategies"][0]["strategy"] == original_strategy, f"Strategy changed: {payload['strategies'][0]['strategy']}"


def test_llm_cannot_override_expected_range():
    payload = _make_payload()
    original_range = json.loads(json.dumps(payload["expected_range"]))

    llm = _make_llm_outlook(market_regime="BEARISH")
    conn = _setup_db_with_llm(llm)
    merge_llm_into_payload(conn, "NIFTY", payload)
    conn.close()

    assert payload["expected_range"] == original_range, f"Expected range changed"


def test_llm_cannot_override_tradeability():
    payload = _make_payload()
    payload["tradeability"] = {"score": 65, "band": "GOOD"}
    original_tradeability = json.loads(json.dumps(payload["tradeability"]))

    llm = _make_llm_outlook(market_regime="BEARISH")
    conn = _setup_db_with_llm(llm)
    merge_llm_into_payload(conn, "NIFTY", payload)
    conn.close()

    assert payload["tradeability"] == original_tradeability, f"Tradeability changed"


# ═══════════════════════════════════════════════════════════════
# LLM explanation tests — LLM CAN contribute narrative/explanation
# ═══════════════════════════════════════════════════════════════

def test_llm_primary_view_incorporated():
    payload = _make_payload()
    llm_summary = "LLM narrative: genuine bullish narrative with strong evidence"
    llm = _make_llm_outlook(market_summary=llm_summary)
    conn = _setup_db_with_llm(llm)
    merge_llm_into_payload(conn, "NIFTY", payload)
    conn.close()

    assert payload["decision"]["primary_view"] == llm_summary, f"Primary view not updated: {payload['decision'].get('primary_view')}"


def test_llm_explanation_fields_incorporated():
    payload = _make_payload()
    llm = _make_llm_outlook(
        trend_analysis="LLM trend analysis",
        momentum_analysis="LLM momentum analysis",
        volatility_analysis="LLM volatility analysis",
        risk_warnings=["LLM risk warning 1", "LLM risk warning 2"],
    )
    conn = _setup_db_with_llm(llm)
    merge_llm_into_payload(conn, "NIFTY", payload)
    conn.close()

    assert "llm_explanation" in payload, "llm_explanation not added to payload"
    assert payload["llm_explanation"]["trend_analysis"] == "LLM trend analysis"
    assert payload["llm_explanation"]["momentum_analysis"] == "LLM momentum analysis"
    assert payload["llm_explanation"]["volatility_analysis"] == "LLM volatility analysis"
    assert payload["llm_explanation"]["risk_warnings"] == ["LLM risk warning 1", "LLM risk warning 2"]


def test_llm_explanation_does_not_override_deterministic():
    payload = _make_payload()
    original_supports = payload["key_levels"]["supports"]
    llm = _make_llm_outlook(
        support_levels=[99999, 99998],
        resistance_levels=[11111, 11112],
        market_regime="BEARISH",
        directional_bias="BEARISH",
        confidence=91,
    )
    conn = _setup_db_with_llm(llm)
    merge_llm_into_payload(conn, "NIFTY", payload)
    conn.close()

    assert payload["key_levels"]["supports"] == original_supports, f"Supports changed: {payload['key_levels']['supports']}"
    assert payload["regime"]["primary"] == "BULLISH", f"Regime changed: {payload['regime']['primary']}"
    assert payload["bias"]["label"] == "BULLISH", f"Bias changed: {payload['bias']['label']}"
    assert payload["confidence"] == 72, f"Confidence changed: {payload['confidence']}"


def test_llm_market_structure_in_explanation():
    payload = _make_payload()
    llm = _make_llm_outlook(market_structure="UPTREND", evidence_strength=0.85)
    conn = _setup_db_with_llm(llm)
    merge_llm_into_payload(conn, "NIFTY", payload)
    conn.close()

    assert "llm_explanation" in payload
    assert payload["llm_explanation"]["market_structure"] == "UPTREND"
    assert payload["llm_explanation"]["evidence_strength"] == 0.85


# ═══════════════════════════════════════════════════════════════
# Edge cases — rule-based rows, no LLM, missing data
# ═══════════════════════════════════════════════════════════════

def test_rule_based_row_skipped():
    payload = _make_payload()
    original = json.loads(json.dumps(payload))
    llm = _make_llm_outlook(market_summary="NIFTY analysis - BEARISH trend summary")
    conn = _setup_db_with_llm(llm)
    merge_llm_into_payload(conn, "NIFTY", payload)
    conn.close()

    assert payload == original, f"Rule-based row should not modify payload: {payload}"
    assert "llm_explanation" not in payload, "llm_explanation should not be present for rule-based"
    assert payload.get("ai_source") != "LLM", "ai_source should not be LLM for rule-based"


def test_no_llm_row_unchanged():
    payload = _make_payload()
    original = json.loads(json.dumps(payload))
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE ai_outlooks (symbol TEXT, timestamp TEXT, outlook TEXT, data_quality TEXT)")
    merge_llm_into_payload(conn, "NIFTY", payload)
    conn.close()

    assert payload == original, f"No LLM row should not modify payload"


def test_no_llm_row_no_llm_explanation():
    payload = _make_payload()
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE ai_outlooks (symbol TEXT, timestamp TEXT, outlook TEXT, data_quality TEXT)")
    merge_llm_into_payload(conn, "NIFTY", payload)
    conn.close()

    assert "llm_explanation" not in payload
    assert payload.get("ai_source") is None or payload.get("ai_source") != "LLM"


def test_empty_summary_row_skipped():
    payload = _make_payload()
    original = json.loads(json.dumps(payload))
    llm = _make_llm_outlook(market_summary="")
    conn = _setup_db_with_llm(llm)
    merge_llm_into_payload(conn, "NIFTY", payload)
    conn.close()

    assert payload == original


def test_llm_explanation_goodness_test():
    """Prove: deterministic BULLISH survives LLM trying to make it BEARISH."""
    payload = _make_payload()
    assert payload["regime"]["primary"] == "BULLISH"
    assert payload["bias"]["label"] == "BULLISH"
    assert payload["confidence"] == 72

    llm = _make_llm_outlook(
        market_regime="BEARISH",
        directional_bias="BEARISH",
        confidence=91,
        market_summary="LLM narrative: bearish market with strong signal",
    )
    conn = _setup_db_with_llm(llm)
    merge_llm_into_payload(conn, "NIFTY", payload)
    conn.close()

    # Deterministic fields PROTECTED
    assert payload["regime"]["primary"] == "BULLISH", "Regime was overridden by LLM!"
    assert payload["bias"]["label"] == "BULLISH", "Bias was overridden by LLM!"
    assert payload["confidence"] == 72, "Confidence was overridden by LLM!"

    # LLM explanation INCORPORATED
    assert payload["decision"]["primary_view"] == "LLM narrative: bearish market with strong signal"
    assert "llm_explanation" in payload
    assert payload["llm_explanation"]["directional_bias"] == "BEARISH"  # LLM's bias is in explanation, not as authority
    assert payload["llm_explanation"]["confidence"] == 91  # LLM's confidence in explanation, not as authority


def test_ai_source_and_timestamp():
    payload = _make_payload()
    llm = _make_llm_outlook(market_summary="Test narrative")
    conn = _setup_db_with_llm(llm, timestamp="2026-09-13T12:30:00Z")
    merge_llm_into_payload(conn, "NIFTY", payload)
    conn.close()

    assert payload["ai_source"] == "LLM"
    assert payload["llm_generated_at"] == "2026-09-13T12:30:00Z"


def test_rule_based_row_with_analysis_marker():
    """Market summary containing 'analysis - ' is treated as rule-based."""
    payload = _make_payload()
    original = json.loads(json.dumps(payload))
    llm = _make_llm_outlook(
        market_summary="NIFTY analysis - RANGE market conditions",
    )
    conn = _setup_db_with_llm(llm)
    merge_llm_into_payload(conn, "NIFTY", payload)
    conn.close()

    assert payload == original
    assert "llm_explanation" not in payload


def test_llm_explanation_only_fields_not_in_deterministic():
    """LLM's market_regime, directional_bias, confidence are in llm_explanation, NOT as authoritative."""
    payload = _make_payload()
    llm = _make_llm_outlook(
        market_regime="BEARISH",
        directional_bias="BEARISH",
        confidence=91,
        market_summary="Genuine LLM narrative",
    )
    conn = _setup_db_with_llm(llm)
    merge_llm_into_payload(conn, "NIFTY", payload)
    conn.close()

    # NOT as authoritative
    assert payload["regime"]["primary"] != "BEARISH"
    assert payload["bias"]["label"] != "BEARISH"
    assert payload["confidence"] != 91

    # IS in explanation
    assert "llm_explanation" in payload
    assert payload["llm_explanation"]["market_regime"] == "BEARISH"
    assert payload["llm_explanation"]["directional_bias"] == "BEARISH"
    assert payload["llm_explanation"]["confidence"] == 91
