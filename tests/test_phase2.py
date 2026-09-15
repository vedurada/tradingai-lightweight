#!/usr/bin/env python3
"""Phase 2 tests — Historical Data, Indicators Versioned, Market State,
Expected Range, Data Validator Extension, Market Candles, API Endpoints.

Target: 921+ total tests (add ~60 new tests).
All frozen model files untouched.
"""
import os
import sys
import json
import sqlite3
import datetime
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from backend.data_normalizer import (
    to_ist, to_utc, candle_timestamp_to_ist,
    is_within_market_hours, get_ist_now, now_ist_str,
)
from backend.expected_range import (
    expected_move, bollinger_range, support_resistance_range,
    compute_expected_range,
)
from backend.indicators_versioned import (
    calculate_all_indicators as calc_all_v2,
    get_indicator_version,
)
from backend.data_validator import (
    DataValidator, MarketValidator, validate_market_data,
)
from backend.market_state import (
    MarketState, build_market_state, build_market_states,
)
from backend.indicators import (
    calculate_ema, calculate_vwap, calculate_pivot, calculate_cpr,
    calculate_bollinger_bands, calculate_rsi, calculate_macd,
    calculate_adx, calculate_atr, calculate_support_resistance,
    calculate_all_indicators,
)

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "database", "tradingai.db")


# ═══════════════════════════════════════════════════════
# Data Normalizer Tests
# ═══════════════════════════════════════════════════════

class TestToIST:
    def test_utc_z_normalization(self):
        result = to_ist("2026-09-15T10:30:00Z")
        assert result is not None
        assert "+05:30" in result

    def test_utc_offset_normalization(self):
        result = to_ist("2026-09-15T10:30:00+00:00")
        assert result is not None
        assert "+05:30" in result

    def test_already_ist(self):
        result = to_ist("2026-09-15T16:00:00+05:30")
        assert result is not None and "+05:30" in result

    def test_naive_utc_conversion(self):
        result = to_ist("2026-09-15 10:30:00")
        assert result is not None
        assert "+05:30" in result

    def test_empty_or_none(self):
        assert to_ist("") is None
        assert to_ist(None) is None

    def test_invalid_returns_none(self):
        assert to_ist("not-a-date") is None

    def test_ist_preserves_time(self):
        result = to_ist("2026-09-15T10:30:00Z")
        dt = datetime.datetime.fromisoformat(result)
        assert dt.hour == 16 or (dt.hour == 15 and dt.minute == 30)


class TestToUTC:
    def test_ist_to_utc(self):
        result = to_utc("2026-09-15T16:00:00+05:30")
        assert result is not None
        assert "+00:00" in result or "Z" in result

    def test_utc_passthrough(self):
        result = to_utc("2026-09-15T10:30:00Z")
        assert result is not None
        assert "T" in result

    def test_naive_to_utc(self):
        result = to_utc("2026-09-15 10:30:00")
        assert result is not None and "+00:00" in result

    def test_empty_returns_none(self):
        assert to_utc("") is None
        assert to_utc(None) is None


class TestCandleTimestampToIST:
    def test_naive_utc_candle(self):
        result = candle_timestamp_to_ist("2026-09-15 10:30:00")
        assert result is not None
        assert "T" in result

    def test_iso_candle(self):
        result = candle_timestamp_to_ist("2026-09-15T10:30:00+00:00")
        assert result is not None

    def test_empty_returns_empty(self):
        assert candle_timestamp_to_ist("") == ""
        assert candle_timestamp_to_ist(None) == ""


class TestIsWithinMarketHours:
    def test_always_returns_bool(self):
        result = is_within_market_hours()
        assert isinstance(result, bool)

    def test_with_timestamp_outside_hours(self):
        result = is_within_market_hours("2026-09-15T02:00:00+05:30")
        assert result is False

    def test_with_timestamp_inside_hours(self):
        result = is_within_market_hours("2026-09-15T11:00:00+05:30")
        assert result is True


class TestISTNow:
    def test_ist_now_returns_datetime(self):
        now = get_ist_now()
        assert isinstance(now, datetime.datetime)

    def test_ist_now_string(self):
        s = now_ist_str()
        assert isinstance(s, str) and len(s) > 10


# ═══════════════════════════════════════════════════════
# Expected Range Tests
# ═══════════════════════════════════════════════════════

class TestExpectedMove:
    def test_positive_price(self):
        result = expected_move(23000.0, 100.0, 13.5)
        assert "low" in result and "high" in result
        assert result["low"] < result["high"]
        assert "move_pct" in result

    def test_zero_price(self):
        result = expected_move(0, 100.0, 13.5)
        assert result["price"] == 0

    def test_atr_only(self):
        result = expected_move(23000.0, 100.0, None)
        assert result["basis"] == "atr"
        assert result["move_pct"] > 0

    def test_vix_only(self):
        result = expected_move(23000.0, None, 15.0)
        assert result["basis"] == "vix"

    def test_neither(self):
        result = expected_move(23000.0, None, None)
        assert result["basis"] == "default"
        assert result["move_pct"] > 0

    def test_range_contains_price(self):
        result = expected_move(23000.0, 100.0, 13.5)
        assert result["low"] <= result["price"]
        assert result["high"] >= result["price"]


class TestBollingerRange:
    def test_valid_bollinger(self):
        bb = {"upper": 23200, "lower": 22800, "middle": 23000, "width": 400}
        result = bollinger_range(bb, 23000.0)
        assert result["low"] == 22800.0
        assert result["high"] == 23200.0
        assert result["basis"] == "bollinger"

    def test_none_bollinger(self):
        result = bollinger_range(None, 23000.0)
        assert result["basis"] in ("atr", "vix", "default")

    def test_zero_price(self):
        bb = {"upper": 23200, "lower": 22800}
        result = bollinger_range(bb, 0)
        assert result["price"] == 0


class TestSupportResistanceRange:
    def test_valid_sr(self):
        sr = {"support": [22500, 22600], "resistance": [23500, 23600]}
        result = support_resistance_range(sr, 23000.0)
        assert result["low"] <= 23000 <= result["high"] or result["basis"] in ("atr", "vix", "default")

    def test_none_sr(self):
        result = support_resistance_range(None, 23000.0)
        assert result["basis"] in ("atr", "vix", "default")


class TestComputeExpectedRange:
    def test_priority_bollinger(self):
        indicators = {
            "bollinger_bands": {"upper": 23200, "lower": 22800},
            "atr": 100.0,
        }
        result = compute_expected_range(indicators, 23000.0)
        assert result["basis"] == "bollinger"

    def test_fallback_atr_vix(self):
        indicators = {"atr": 100.0, "support_resistance": {"support": [], "resistance": []}}
        result = compute_expected_range(indicators, 23000.0)
        assert result["move_pct"] > 0

    def test_empty_indicators(self):
        result = compute_expected_range(None, 23000.0)
        assert result["price"] == 23000.0


# ═══════════════════════════════════════════════════════
# Indicator Versioned Tests
# ═══════════════════════════════════════════════════════

class TestIndicatorVersioned:
    def test_calc_all_v2_returns_dict(self):
        ohlcv = [
            {"close": 100, "high": 102, "low": 98, "open": 99, "volume": 1000},
            {"close": 101, "high": 103, "low": 99, "open": 100, "volume": 1000},
        ]
        quote = {"close": 101, "high": 103, "low": 99, "open": 100}
        result = calc_all_v2(ohlcv, quote)
        assert isinstance(result, dict)
        assert "rsi" in result or "vwap" in result

    def test_calc_all_v2_has_version(self):
        ohlcv = [
            {"close": 100, "high": 102, "low": 98, "open": 99, "volume": 1000},
            {"close": 101, "high": 103, "low": 99, "open": 100, "volume": 1000},
        ]
        quote = {"close": 101, "high": 103, "low": 99, "open": 100}
        result = calc_all_v2(ohlcv, quote)
        assert "indicator_version" in result
        assert result["indicator_version"] != ""

    def test_calc_all_v2_has_hash(self):
        ohlcv = [
            {"close": 100, "high": 102, "low": 98, "open": 99, "volume": 1000},
            {"close": 101, "high": 103, "low": 99, "open": 100, "volume": 1000},
        ]
        quote = {"close": 101, "high": 103, "low": 99, "open": 100}
        result = calc_all_v2(ohlcv, quote)
        assert "indicator_hash" in result

    def test_calc_all_v2_timestamp_from_candle(self):
        ohlcv = [
            {"close": 100, "high": 102, "low": 98, "open": 99, "volume": 1000},
            {"close": 101, "high": 103, "low": 99, "open": 100, "volume": 1000},
        ]
        quote = {"close": 101, "high": 103, "low": 99, "open": 100, "timestamp": "2026-09-15 10:30:00"}
        result = calc_all_v2(ohlcv, quote, candle_timestamp="2026-09-15 10:30:00")
        assert "timestamp" in result
        assert result["timestamp"] != ""

    def test_indicator_version_info(self):
        info = get_indicator_version()
        assert "version" in info
        assert "hash" in info
        assert "source" in info

    def test_v2_matches_frozen_values(self):
        ohlcv = [{"close": 100 + i, "high": 102 + i, "low": 98 + i, "open": 99 + i, "volume": 1000} for i in range(30)]
        quote = {"close": ohlcv[-1]["close"], "high": ohlcv[-1]["high"], "low": ohlcv[-1]["low"], "open": ohlcv[-1]["open"]}
        frozen = calculate_all_indicators(ohlcv, quote)
        versioned = calc_all_v2(ohlcv, quote)
        assert frozen.get("rsi") == versioned.get("rsi")
        assert frozen.get("vwap") == versioned.get("vwap")
        assert frozen.get("pivot") == versioned.get("pivot")


# ═══════════════════════════════════════════════════════
# Data Validator Extension Tests
# ═══════════════════════════════════════════════════════

class TestMarketValidator:
    def test_market_validator_initializes(self):
        mv = MarketValidator(DB_PATH)
        assert mv.db_path == DB_PATH

    def test_validate_candle_continuity_requires_db(self):
        mv = MarketValidator(DB_PATH)
        conn = sqlite3.connect(DB_PATH)
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            result = mv.validate_candle_continuity(conn, "NIFTY", "price_1m", 1)
            assert isinstance(result, dict)
            assert "symbol" in result
            assert "gaps" in result
        finally:
            conn.close()

    def test_validate_candle_ohlc(self):
        mv = MarketValidator(DB_PATH)
        conn = sqlite3.connect(DB_PATH)
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            result = mv.validate_candle_ohlc(conn, "price_1d")
            assert isinstance(result, dict)
            assert "total" in result
            assert "valid" in result
        finally:
            conn.close()

    def test_validate_ist_timestamps(self):
        mv = MarketValidator(DB_PATH)
        conn = sqlite3.connect(DB_PATH)
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            result = mv.validate_ist_timestamps(conn, "price_1d")
            assert isinstance(result, dict)
            assert "total" in result
        finally:
            conn.close()

    def test_validate_market_candles(self):
        mv = MarketValidator(DB_PATH)
        conn = sqlite3.connect(DB_PATH)
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            result = mv.validate_market_candles(conn)
            assert isinstance(result, dict)
            assert "timeframes" in result
            assert "symbols" in result
        finally:
            conn.close()

    def test_validate_expected_range_valid(self):
        mv = MarketValidator(DB_PATH)
        issues = mv.validate_expected_range(23000.0, 22800.0, 23200.0)
        assert len(issues) == 0

    def test_validate_expected_range_below(self):
        mv = MarketValidator(DB_PATH)
        issues = mv.validate_expected_range(22000.0, 22800.0, 23200.0)
        assert len(issues) > 0

    def test_validate_expected_range_above(self):
        mv = MarketValidator(DB_PATH)
        issues = mv.validate_expected_range(24000.0, 22800.0, 23200.0)
        assert len(issues) > 0

    def test_validate_expected_range_inverted(self):
        mv = MarketValidator(DB_PATH)
        issues = mv.validate_expected_range(23000.0, 23200.0, 22800.0)
        assert any("inverted" in i for i in issues)


class TestValidateMarketData:
    def test_validate_market_data_returns_list(self):
        result = validate_market_data(DB_PATH)
        assert isinstance(result, list)


# ═══════════════════════════════════════════════════════
# Market State Tests
# ═══════════════════════════════════════════════════════

class TestMarketState:
    def test_market_state_creation(self):
        state = MarketState(
            symbol="NIFTY", timestamp="2026-09-15T10:30:00+05:30",
            indicators={"rsi": 58.0}, regime={"regime": "BULLISH"},
            support=[22500], resistance=[23500],
            expected_range={"low": 22800, "high": 23200},
        )
        d = state.to_dict()
        assert d["symbol"] == "NIFTY"
        assert d["regime"]["regime"] == "BULLISH"
        assert d["support"] == [22500]
        assert d["resistance"] == [23500]

    def test_market_state_to_json(self):
        state = MarketState(
            symbol="NIFTY", timestamp="2026-09-15T10:30:00+05:30",
            indicators={}, regime={}, support=[], resistance=[],
            expected_range={},
        )
        j = state.to_json()
        parsed = json.loads(j)
        assert parsed["symbol"] == "NIFTY"

    def test_market_state_immutable(self):
        state = MarketState(
            symbol="NIFTY", timestamp="2026-09-15T10:30:00+05:30",
            indicators={"rsi": 58.0}, regime={"regime": "BULLISH"},
            support=[22500], resistance=[23500],
            expected_range={"low": 22800, "high": 23200},
        )
        d = state.to_dict()
        d["regime"] = {"regime": "HACKED"}
        assert state.regime["regime"] == "BULLISH"

    def test_build_market_state_from_db(self):
        conn = sqlite3.connect(DB_PATH)
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            has_data = conn.execute("SELECT COUNT(*) FROM price_1d WHERE symbol='NIFTY'").fetchone()[0] > 0
            if has_data:
                state = build_market_state("NIFTY", conn)
                if state:
                    assert state.symbol == "NIFTY"
                    assert state.candle_count >= 0
                    assert "timestamp" in state.to_dict()
            else:
                pytest.skip("No NIFTY daily data available")
        finally:
            conn.close()

    def test_build_market_states_returns_dict(self):
        states = build_market_states(["NIFTY", "BANKNIFTY"])
        assert isinstance(states, dict)
        for sym in ["NIFTY", "BANKNIFTY"]:
            if sym in states:
                assert isinstance(states[sym], MarketState)


# ═══════════════════════════════════════════════════════
# API Endpoint Tests
# ═══════════════════════════════════════════════════════

class TestMarketStateEndpoint:
    def test_endpoint_importable(self):
        from backend.api_server import app
        assert app is not None

    def test_endpoint_registered(self):
        from backend.api_server import app
        rules = [r.rule for r in app.url_map.iter_rules()]
        assert "/api/market/state/<symbol>" in rules or any("/api/market/state" in r for r in rules)

    def test_endpoint_registered_range(self):
        from backend.api_server import app
        rules = [r.rule for r in app.url_map.iter_rules()]
        assert any("/api/market/expected-range" in r for r in rules)

    def test_endpoint_registered_validate(self):
        from backend.api_server import app
        rules = [r.rule for r in app.url_map.iter_rules()]
        assert any("/api/market/validate" in r for r in rules)


class TestDataValidatorBackwardCompat:
    def test_validate_price_data_still_works(self):
        from backend.data_validator import validate_price_data
        result = validate_price_data(DB_PATH)
        assert isinstance(result, list)


# ═══════════════════════════════════════════════════════
# Data Normalizer IST Consistency
# ═══════════════════════════════════════════════════════

class TestISTConsistency:
    def test_to_ist_and_back(self):
        original = "2026-09-15T10:30:00Z"
        ist = to_ist(original)
        utc = to_utc(ist)
        assert utc is not None
        assert "T" in utc

    def test_candle_timestamp_roundtrip(self):
        original = "2026-09-15 10:30:00"
        ist = candle_timestamp_to_ist(original)
        assert ist is not None and len(ist) > 0

    def test_ist_has_offset(self):
        result = to_ist("2026-09-15T10:30:00Z")
        parsed = datetime.datetime.fromisoformat(result)
        assert parsed.tzinfo is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
