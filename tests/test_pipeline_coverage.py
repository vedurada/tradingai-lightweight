#!/usr/bin/env python3
"""Pipeline coverage tests — STEP 4C.

Proves the corrected components work together through the actual production path:

    price_1d + indicators + vix_data + market_regime
              ↓
         RegimeEngine (if poller)
              ↓
         market_regime DB row
              ↓
         build_outlook()
              ↓
         final payload
              ↓
         API / consumer

Also verifies the LLM boundary invariant through the real pipeline:
    LLM output CANNOT modify regime / bias / confidence / key_levels / verdict / strategy
    LLM output MAY provide primary_view (narrative) + llm_explanation (descriptive)
"""
import json
import sqlite3
import tempfile
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.outlook import build_outlook, merge_llm_into_payload, resolve_verdict


def _make_regime_conn(regime="BULLISH", confidence=72, timestamp="2026-09-13T12:00:00"):
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE price_1d (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT, timestamp TEXT, open REAL, high REAL, low REAL, close REAL, volume INTEGER, adjusted_close REAL,
        UNIQUE(symbol, timestamp)
    )""")
    conn.execute("""CREATE TABLE indicators (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT, timestamp TEXT, ema9 REAL, ema20 REAL, ema50 REAL, ema100 REAL, ema200 REAL,
        sma20 REAL, sma50 REAL, sma200 REAL, vwap REAL, rsi REAL, macd REAL, macd_signal REAL,
        macd_histogram REAL, atr REAL, adx REAL, di_plus REAL, di_minus REAL,
        bollinger_upper REAL, bollinger_middle REAL, bollinger_lower REAL, bollinger_width REAL,
        pivot REAL, r1 REAL, s1 REAL, r2 REAL, s2 REAL, r3 REAL, s3 REAL, cpr_classification TEXT,
        day_high REAL, day_low REAL, prev_day_high REAL, prev_day_low REAL, prev_day_close REAL,
        open_range_high REAL, open_range_low REAL, support_resistance TEXT
    )""")
    conn.execute("""CREATE TABLE market_regime (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT, timestamp TEXT, regime TEXT, confidence REAL, trend TEXT, momentum TEXT,
        volatility TEXT, breadth TEXT, vix_regime TEXT, evidence TEXT,
        UNIQUE(symbol, timestamp)
    )""")
    conn.execute("""CREATE TABLE vix_data (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT, open REAL, high REAL, low REAL, close REAL, change REAL, change_pct REAL,
        UNIQUE(timestamp)
    )""")
    conn.execute("""CREATE TABLE option_expiries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT, expiry TEXT, fetched_at TEXT, UNIQUE(symbol, expiry)
    )""")
    conn.execute("""CREATE TABLE option_chain (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT, expiry TEXT, strike REAL, option_type TEXT, open_interest REAL
    )""")
    conn.execute("""CREATE TABLE oi_top_strikes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT, expiry TEXT, side TEXT, strike REAL, open_interest REAL, rank INTEGER
    )""")
    conn.execute("""CREATE TABLE history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT, direction TEXT, strategy TEXT, entry_time TEXT, locked_price REAL,
        exit_time TEXT, closed_price REAL, points REAL, result TEXT, no_trade_conditions TEXT,
        entry_outlook TEXT, created_at TEXT, archived_at TEXT
    )""")

    conn.execute(
        "INSERT INTO price_1d (symbol, timestamp, open, high, low, close, volume, adjusted_close) VALUES (?,?,?,?,?,?,?,?)",
        ("NIFTY", "2026-09-13T10:00:00", 24500, 24600, 24400, 24550, 1000000, 24550),
    )
    conn.execute(
        "INSERT INTO price_1d (symbol, timestamp, open, high, low, close, volume, adjusted_close) VALUES (?,?,?,?,?,?,?,?)",
        ("NIFTY", "2026-09-12T10:00:00", 24400, 24500, 24300, 24450, 950000, 24450),
    )
    conn.execute(
        "INSERT INTO indicators (symbol, timestamp, ema20, sma20, sma50, rsi, adx, atr, vwap) VALUES (?,?,?,?,?,?,?,?,?)",
        ("NIFTY", "2026-09-13T12:00:00", 24400, 24350, 24300, 55, 35, 50, 24480),
    )
    conn.execute(
        "INSERT INTO market_regime (symbol, timestamp, regime, confidence, trend, momentum, volatility, breadth, vix_regime) VALUES (?,?,?,?,?,?,?,?,?)",
        ("NIFTY", timestamp, regime, confidence, regime, regime, "NORMAL", "POSITIVE", regime),
    )
    conn.execute(
        "INSERT INTO vix_data (timestamp, open, high, low, close, change, change_pct) VALUES (?,?,?,?,?,?,?)",
        ("2026-09-13T12:00:00", 15, 16, 14, 15, 0, 0),
    )
    conn.execute(
        "INSERT INTO option_expiries (symbol, expiry, fetched_at) VALUES (?,?,?)",
        ("NIFTY", "2026-09-19", "2026-09-13T12:00:00"),
    )
    conn.execute("""CREATE TABLE IF NOT EXISTS ai_outlooks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT, timestamp TEXT, outlook TEXT
    )""")
    conn.commit()
    return conn


class TestBuildOutlookRegimePropagation:
    """Verify regime propagates correctly through build_outlook()."""

    def test_bullish_regime_propagates(self):
        conn = _make_regime_conn(regime="BULLISH")
        payload = build_outlook(conn, "NIFTY", "2026-09-13")
        conn.close()
        assert payload["regime"]["primary"] == "BULLISH"
        assert payload["regime"]["engine"] == "BULLISH"
        assert "BULLISH" in payload["bias"]["label"]
        assert payload["confidence"] is not None
        assert payload["decision"]["verdict"] in ("TRADE", "WAIT")

    def test_bearish_regime_propagates(self):
        conn = _make_regime_conn(regime="BEARISH")
        payload = build_outlook(conn, "NIFTY", "2026-09-13")
        conn.close()
        assert payload["regime"]["primary"] == "BEARISH"
        assert payload["regime"]["engine"] == "BEARISH"
        assert "BEARISH" in payload["bias"]["label"]
        assert payload["confidence"] is not None

    def test_sideways_regime_neutral(self):
        conn = _make_regime_conn(regime="SIDEWAYS")
        payload = build_outlook(conn, "NIFTY", "2026-09-13")
        conn.close()
        assert payload["regime"]["primary"] == "SIDEWAYS"
        assert payload["bias"]["label"] == "NEUTRAL"
        assert payload["confidence"] is not None

    def test_high_volatility_regime(self):
        conn = _make_regime_conn(regime="HIGH_VOLATILITY")
        payload = build_outlook(conn, "NIFTY", "2026-09-13")
        conn.close()
        assert payload["regime"]["primary"] == "EVENT / ABNORMAL VOLATILITY"
        assert payload["confidence"] <= 60

    def test_unknown_regime(self):
        conn = _make_regime_conn(regime="UNKNOWN")
        payload = build_outlook(conn, "NIFTY", "2026-09-13")
        conn.close()
        assert payload["regime"]["primary"] == "UNKNOWN"
        assert payload["decision"]["verdict"] in ("WAIT", "TRADE")

    def test_regime_in_engine_field(self):
        conn = _make_regime_conn(regime="BULLISH")
        payload = build_outlook(conn, "NIFTY", "2026-09-13")
        conn.close()
        assert payload["regime"]["engine"] == "BULLISH"
        assert payload["regime"]["primary"] == "BULLISH"


class TestBuildOutlookDeterminism:
    """Verify deterministic fields are consistent for same inputs."""

    def test_same_input_same_output(self):
        conn1 = _make_regime_conn(regime="BULLISH")
        payload1 = build_outlook(conn1, "NIFTY", "2026-09-13")
        conn1.close()
        conn2 = _make_regime_conn(regime="BULLISH")
        payload2 = build_outlook(conn2, "NIFTY", "2026-09-13")
        conn2.close()
        assert payload1["regime"] == payload2["regime"]
        assert payload1["bias"] == payload2["bias"]
        assert payload1["confidence"] == payload2["confidence"]
        assert payload1["decision"]["verdict"] == payload2["decision"]["verdict"]

    def test_confidence_is_int(self):
        conn = _make_regime_conn(regime="BULLISH")
        payload = build_outlook(conn, "NIFTY", "2026-09-13")
        conn.close()
        assert isinstance(payload["confidence"], int)
        assert 0 <= payload["confidence"] <= 100

    def test_key_levels_present(self):
        conn = _make_regime_conn(regime="BULLISH")
        payload = build_outlook(conn, "NIFTY", "2026-09-13")
        conn.close()
        assert "key_levels" in payload
        assert "supports" in payload["key_levels"]
        assert "resistances" in payload["key_levels"]

    def test_expected_range_present(self):
        conn = _make_regime_conn(regime="BULLISH")
        payload = build_outlook(conn, "NIFTY", "2026-09-13")
        conn.close()
        assert "expected_range" in payload


class TestRegimeEngineToBuildOutlookChain:
    """Test RegimeEngine → market_regime DB row → build_outlook()."""

    def test_regime_engine_bullish_via_db(self):
        from regime import RegimeEngine
        engine = RegimeEngine()
        market = {"price": 24600, "sma20": 24400, "sma50": 24300, "rsi": 55, "macd": {"histogram": 0.5}, "vix_close": 15, "advance_decline_ratio": 1.2}
        options = {}
        result = engine.evaluate(market, options)
        assert result["regime"] == "BULLISH"

        conn = _make_regime_conn()
        conn.execute(
            "INSERT INTO market_regime (symbol, timestamp, regime, confidence, trend, momentum, volatility, breadth, vix_regime) VALUES (?,?,?,?,?,?,?,?,?)",
            ("NIFTY", "2026-09-13T13:00:00", result["regime"], result["confidence"],
             result["components"]["trend"], result["components"]["momentum"],
             result["components"]["vix"], result["components"]["breadth"], result["components"]["vix"]),
        )
        conn.commit()
        payload = build_outlook(conn, "NIFTY", "2026-09-13")
        conn.close()
        assert payload["regime"]["primary"] == "BULLISH"

    def test_regime_engine_bearish_via_db(self):
        from regime import RegimeEngine
        engine = RegimeEngine()
        market = {"price": 24200, "sma20": 24400, "sma50": 24500, "rsi": 40, "macd": {"histogram": -0.5}, "vix_close": 16, "advance_decline_ratio": 0.7}
        options = {}
        result = engine.evaluate(market, options)
        assert result["regime"] == "BEARISH"

        conn = _make_regime_conn()
        conn.execute(
            "INSERT INTO market_regime (symbol, timestamp, regime, confidence, trend, momentum, volatility, breadth, vix_regime) VALUES (?,?,?,?,?,?,?,?,?)",
            ("NIFTY", "2026-09-13T13:00:00", result["regime"], result["confidence"],
             result["components"]["trend"], result["components"]["momentum"],
             result["components"]["vix"], result["components"]["breadth"], result["components"]["vix"]),
        )
        conn.commit()
        payload = build_outlook(conn, "NIFTY", "2026-09-13")
        conn.close()
        assert payload["regime"]["primary"] == "BEARISH"

    def test_regime_engine_high_volatility_via_db(self):
        from regime import RegimeEngine
        engine = RegimeEngine()
        market = {"price": 24500, "sma20": 24400, "sma50": 24300, "rsi": 55, "macd": {"histogram": 0.5}, "vix_close": 28, "advance_decline_ratio": 1.2}
        options = {}
        result = engine.evaluate(market, options)
        assert result["regime"] == "HIGH_VOLATILITY"

        conn = _make_regime_conn()
        conn.execute(
            "INSERT INTO market_regime (symbol, timestamp, regime, confidence, trend, momentum, volatility, breadth, vix_regime) VALUES (?,?,?,?,?,?,?,?,?)",
            ("NIFTY", "2026-09-13T13:00:00", result["regime"], result["confidence"],
             result["components"]["trend"], result["components"]["momentum"],
             result["components"]["vix"], result["components"]["breadth"], result["components"]["vix"]),
        )
        conn.commit()
        payload = build_outlook(conn, "NIFTY", "2026-09-13")
        conn.close()
        assert payload["regime"]["primary"] == "EVENT / ABNORMAL VOLATILITY"


class TestLLMBoundaryInvariant:
    """Verify the LLM boundary invariant through the real pipeline."""

    def test_llm_cannot_change_regime(self):
        conn = _make_regime_conn(regime="BULLISH")
        payload = build_outlook(conn, "NIFTY", "2026-09-13")
        conn.close()
        original_regime = payload["regime"]["primary"]
        original_bias = payload["bias"]["label"]
        original_conf = payload["confidence"]
        conn = _make_regime_conn(regime="BULLISH")
        conn.execute(
            "INSERT INTO ai_outlooks (symbol, timestamp, outlook) VALUES (?,?,?)",
            ("NIFTY", "2026-09-13T12:00:00", json.dumps({
                "market_summary": "LLM bearish narrative with strong evidence",
                "market_regime": "BEARISH",
                "directional_bias": "BEARISH",
                "confidence": 91,
            })),
        )
        conn.commit()
        merge_llm_into_payload(conn, "NIFTY", payload)
        conn.close()
        assert payload["regime"]["primary"] == original_regime
        assert payload["bias"]["label"] == original_bias
        assert payload["confidence"] == original_conf

    def test_llm_cannot_change_key_levels(self):
        conn = _make_regime_conn(regime="BULLISH")
        payload = build_outlook(conn, "NIFTY", "2026-09-13")
        conn.close()
        original_supports = payload["key_levels"]["supports"]
        conn = _make_regime_conn(regime="BULLISH")
        conn.execute(
            "INSERT INTO ai_outlooks (symbol, timestamp, outlook) VALUES (?,?,?)",
            ("NIFTY", "2026-09-13T12:00:00", json.dumps({
                "market_summary": "LLM bearish narrative",
                "support_levels": [99999, 99998],
                "resistance_levels": [11111, 11112],
            })),
        )
        conn.commit()
        merge_llm_into_payload(conn, "NIFTY", payload)
        conn.close()
        assert payload["key_levels"]["supports"] == original_supports

    def test_llm_cannot_change_verdict(self):
        conn = _make_regime_conn(regime="BULLISH")
        payload = build_outlook(conn, "NIFTY", "2026-09-13")
        conn.close()
        original_verdict = payload["decision"]["verdict"]
        conn = _make_regime_conn(regime="BULLISH")
        conn.execute(
            "INSERT INTO ai_outlooks (symbol, timestamp, outlook) VALUES (?,?,?)",
            ("NIFTY", "2026-09-13T12:00:00", json.dumps({
                "market_summary": "LLM bearish narrative",
                "market_regime": "BEARISH",
                "directional_bias": "BEARISH",
            })),
        )
        conn.commit()
        merge_llm_into_payload(conn, "NIFTY", payload)
        conn.close()
        assert payload["decision"]["verdict"] == original_verdict

    def test_llm_cannot_change_strategy(self):
        conn = _make_regime_conn(regime="BULLISH")
        payload = build_outlook(conn, "NIFTY", "2026-09-13")
        conn.close()
        original_strategies = json.loads(json.dumps(payload["strategies"]))
        conn = _make_regime_conn(regime="BULLISH")
        conn.execute(
            "INSERT INTO ai_outlooks (symbol, timestamp, outlook) VALUES (?,?,?)",
            ("NIFTY", "2026-09-13T12:00:00", json.dumps({
                "market_summary": "LLM bearish narrative",
                "market_regime": "BEARISH",
                "directional_bias": "BEARISH",
                "primary_strategy": {"strategy": "Bear Put Spread"},
            })),
        )
        conn.commit()
        merge_llm_into_payload(conn, "NIFTY", payload)
        conn.close()
        assert payload["strategies"] == original_strategies

    def test_llm_provides_primary_view(self):
        conn = _make_regime_conn(regime="BULLISH")
        payload = build_outlook(conn, "NIFTY", "2026-09-13")
        conn.close()
        llm_summary = "LLM narrative: genuine bullish narrative"
        conn = _make_regime_conn(regime="BULLISH")
        conn.execute(
            "INSERT INTO ai_outlooks (symbol, timestamp, outlook) VALUES (?,?,?)",
            ("NIFTY", "2026-09-13T12:00:00", json.dumps({"market_summary": llm_summary})),
        )
        conn.commit()
        merge_llm_into_payload(conn, "NIFTY", payload)
        conn.close()
        assert payload["decision"]["primary_view"] == llm_summary

    def test_llm_provides_llm_explanation(self):
        conn = _make_regime_conn(regime="BULLISH")
        payload = build_outlook(conn, "NIFTY", "2026-09-13")
        conn.close()
        conn = _make_regime_conn(regime="BULLISH")
        conn.execute(
            "INSERT INTO ai_outlooks (symbol, timestamp, outlook) VALUES (?,?,?)",
            ("NIFTY", "2026-09-13T12:00:00", json.dumps({
                "market_summary": "LLM genuine analysis narrative",
                "trend_analysis": "LLM trend analysis",
                "market_structure": "UPTREND",
                "evidence_strength": 0.85,
            })),
        )
        conn.commit()
        merge_llm_into_payload(conn, "NIFTY", payload)
        conn.close()
        assert "llm_explanation" in payload
        assert payload["llm_explanation"]["trend_analysis"] == "LLM trend analysis"
        assert payload["llm_explanation"]["market_structure"] == "UPTREND"

    def test_llm_rule_based_row_skipped(self):
        conn = _make_regime_conn(regime="BULLISH")
        payload = build_outlook(conn, "NIFTY", "2026-09-13")
        conn.close()
        original = json.loads(json.dumps(payload))
        conn = _make_regime_conn(regime="BULLISH")
        conn.execute(
            "INSERT INTO ai_outlooks (symbol, timestamp, outlook) VALUES (?,?,?)",
            ("NIFTY", "2026-09-13T12:00:00", json.dumps({"market_summary": "NIFTY analysis - BEARISH trend summary"})),
        )
        conn.commit()
        merge_llm_into_payload(conn, "NIFTY", payload)
        conn.close()
        assert payload == original


class TestEndToEndConsistency:
    """Verify no silent regime transformations in the production path."""

    def test_bullish_not_silently_neutral(self):
        conn = _make_regime_conn(regime="BULLISH")
        payload = build_outlook(conn, "NIFTY", "2026-09-13")
        conn.close()
        assert payload["regime"]["primary"] != "NEUTRAL"
        assert payload["regime"]["primary"] == "BULLISH"

    def test_bearish_not_silently_neutral(self):
        conn = _make_regime_conn(regime="BEARISH")
        payload = build_outlook(conn, "NIFTY", "2026-09-13")
        conn.close()
        assert payload["regime"]["primary"] != "NEUTRAL"
        assert payload["regime"]["primary"] == "BEARISH"

    def test_sideways_not_directional(self):
        conn = _make_regime_conn(regime="SIDEWAYS")
        payload = build_outlook(conn, "NIFTY", "2026-09-13")
        conn.close()
        assert payload["bias"]["label"] == "NEUTRAL"
        assert payload["regime"]["primary"] == "SIDEWAYS"

    def test_unknown_not_trade_direction(self):
        conn = _make_regime_conn(regime="UNKNOWN")
        payload = build_outlook(conn, "NIFTY", "2026-09-13")
        conn.close()
        assert payload["regime"]["primary"] == "UNKNOWN"
        assert payload["bias"]["label"] == "NEUTRAL"

    def test_high_vol_not_directional(self):
        conn = _make_regime_conn(regime="HIGH_VOLATILITY")
        payload = build_outlook(conn, "NIFTY", "2026-09-13")
        conn.close()
        assert payload["bias"]["label"] == "NEUTRAL"
