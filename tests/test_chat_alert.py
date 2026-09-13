#!/usr/bin/env python3
"""Tests for resolve_verdict() — chat alert fix (STEP 4B).

Proves:
- decision.verdict is correctly detected (was the bug)
- Top-level verdict still works (backward compatibility)
- Missing decision/verdict does not raise
- Non-TRADE verdicts do not resolve to TRADE
"""
from backend.outlook import resolve_verdict


def test_decision_verdict_detected():
    payload = {"decision": {"verdict": "TRADE"}}
    assert resolve_verdict(payload) == "TRADE"


def test_decision_verdict_wait():
    payload = {"decision": {"verdict": "WAIT"}}
    assert resolve_verdict(payload) == "WAIT"


def test_decision_verdict_avoid():
    payload = {"decision": {"verdict": "AVOID"}}
    assert resolve_verdict(payload) == "AVOID"


def test_decision_verdict_lowercase_normalized():
    payload = {"decision": {"verdict": "trade"}}
    assert resolve_verdict(payload) == "TRADE"


def test_top_level_verdict_backward_compat():
    payload = {"verdict": "TRADE"}
    assert resolve_verdict(payload) == "TRADE"


def test_outlook_verdict_fallback():
    payload = {"outlook": {"verdict": "TRADE"}}
    assert resolve_verdict(payload) == "TRADE"


def test_trade_decision_fallback():
    payload = {"trade_decision": "TRADE"}
    assert resolve_verdict(payload) == "TRADE"


def test_missing_decision_no_exception():
    payload = {"something": "else"}
    assert resolve_verdict(payload) == ""


def test_empty_payload_no_exception():
    assert resolve_verdict({}) == ""


def test_none_verdict_no_exception():
    payload = {"decision": {}}
    assert resolve_verdict(payload) == ""


def test_priority_decision_over_top_level():
    payload = {"decision": {"verdict": "WAIT"}, "verdict": "TRADE"}
    assert resolve_verdict(payload) == "WAIT"


def test_none_payload_verdict():
    payload = {"decision": {"verdict": None}}
    assert resolve_verdict(payload) == ""
