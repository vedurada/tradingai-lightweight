#!/usr/bin/env python3
"""Tests for backend/regime_utils.py — shared canonical regime normalizer."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.regime_utils import normalize_regime, REGIME_ALIASES, CANONICAL_REGIMES, UNKNOWN_REGIME


def test_normalize_trending_bullish():
    assert normalize_regime("TRENDING_BULLISH") == "BULLISH"


def test_normalize_trending_bearish():
    assert normalize_regime("TRENDING_BEARISH") == "BEARISH"


def test_normalize_range_bound():
    assert normalize_regime("RANGE_BOUND") == "SIDEWAYS"


def test_normalize_bullish():
    assert normalize_regime("BULLISH") == "BULLISH"


def test_normalize_bearish():
    assert normalize_regime("BEARISH") == "BEARISH"


def test_normalize_sideways():
    assert normalize_regime("SIDEWAYS") == "SIDEWAYS"


def test_normalize_high_volatility():
    assert normalize_regime("HIGH_VOLATILITY") == "HIGH_VOLATILITY"


def test_normalize_lowercase():
    assert normalize_regime("bullish") == "BULLISH"
    assert normalize_regime("bearish") == "BEARISH"
    assert normalize_regime("sideways") == "SIDEWAYS"


def test_normalize_with_spaces():
    assert normalize_regime("  BULLISH  ") == "BULLISH"
    assert normalize_regime("  TRENDING_BULLISH  ") == "BULLISH"


def test_normalize_unknown_string():
    assert normalize_regime("SOMETHING_WEIRD") == UNKNOWN_REGIME
    assert normalize_regime("CONFIRMED") == UNKNOWN_REGIME
    assert normalize_regime("NEUTRAL") == UNKNOWN_REGIME


def test_normalize_none():
    assert normalize_regime(None) == UNKNOWN_REGIME


def test_normalize_empty():
    assert normalize_regime("") == UNKNOWN_REGIME


def test_canonical_regimes_set():
    assert CANONICAL_REGIMES == {"BULLISH", "BEARISH", "SIDEWAYS", "HIGH_VOLATILITY"}


def test_alias_map_complete():
    assert REGIME_ALIASES["TRENDING_BULLISH"] == "BULLISH"
    assert REGIME_ALIASES["TRENDING_BEARISH"] == "BEARISH"
    assert REGIME_ALIASES["RANGE_BOUND"] == "SIDEWAYS"
    assert REGIME_ALIASES["BULLISH"] == "BULLISH"
    assert REGIME_ALIASES["BEARISH"] == "BEARISH"
    assert REGIME_ALIASES["SIDEWAYS"] == "SIDEWAYS"
    assert REGIME_ALIASES["HIGH_VOLATILITY"] == "HIGH_VOLATILITY"


def test_legacy_equivalence_bullish():
    assert normalize_regime("TRENDING_BULLISH") == normalize_regime("BULLISH")


def test_legacy_equivalence_bearish():
    assert normalize_regime("TRENDING_BEARISH") == normalize_regime("BEARISH")


def test_legacy_equivalence_range():
    assert normalize_regime("RANGE_BOUND") == normalize_regime("SIDEWAYS")
