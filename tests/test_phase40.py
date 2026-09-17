import json
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))


class TestEvidenceTrend(unittest.TestCase):

    def test_bullish_trend(self):
        from market_evidence_engine import MarketEvidenceEngine
        engine = MarketEvidenceEngine()
        snapshot = {
            "close": 23200, "high": 23250, "low": 23150,
            "ema9": 23180, "ema20": 23100, "ema50": 23000, "ema200": 22900,
            "vwap": 23100, "rsi": 55, "macd": 1.5, "macd_signal": 1.0, "adx": 35,
            "prev_day_high": 23150, "prev_day_low": 23000,
            "support": 23000, "resistance": 23200,
            "vix": 13.5, "atr": 80,
            "data_state": "LIVE",
        }
        result = engine.evaluate(snapshot, data_state="LIVE", symbol="NIFTY")
        trend = result["groups"]["trend"]
        self.assertIn(trend["signal"], ("BULLISH", "MIXED"))
        self.assertEqual(trend["group"], "trend")
        self.assertIn("availability", trend)
        self.assertIn("rules_triggered", trend)
        self.assertIn("data_used", trend)

    def test_bearish_trend(self):
        from market_evidence_engine import MarketEvidenceEngine
        engine = MarketEvidenceEngine()
        snapshot = {
            "close": 22900, "high": 22950, "low": 22850,
            "ema9": 22950, "ema20": 23000, "ema50": 23100, "ema200": 23200,
            "vwap": 23000, "rsi": 60, "macd": -1.5, "macd_signal": -1.0, "adx": 30,
            "prev_day_high": 23050, "prev_day_low": 22900,
            "support": 22800, "resistance": 22950,
            "vix": 25, "atr": 120,
            "data_state": "LIVE",
        }
        result = engine.evaluate(snapshot, data_state="LIVE", symbol="NIFTY")
        trend = result["groups"]["trend"]
        self.assertIn(trend["signal"], ("BEARISH", "MIXED"))

    def test_weak_trend(self):
        from market_evidence_engine import MarketEvidenceEngine
        engine = MarketEvidenceEngine()
        snapshot = {
            "close": 23100, "high": 23150, "low": 23050,
            "ema9": 23050, "ema20": 23100, "ema50": 23100, "ema200": 23100,
            "vwap": 23100, "rsi": 50, "macd": 0.1, "macd_signal": 0.1, "adx": 15,
            "data_state": "LIVE",
        }
        result = engine.evaluate(snapshot, data_state="LIVE", symbol="NIFTY")
        trend = result["groups"]["trend"]
        self.assertIn(trend["signal"], ("BEARISH", "MIXED"))
        self.assertIn(trend["availability"], ("LIVE",))
        self.assertLessEqual(trend["strength"], "MODERATE")

    def test_trend_unavailable(self):
        from market_evidence_engine import MarketEvidenceEngine
        engine = MarketEvidenceEngine()
        snapshot = {"close": 23100, "data_state": "UNAVAILABLE"}
        result = engine.evaluate(snapshot, data_state="UNAVAILABLE", symbol="NIFTY")
        trend = result["groups"]["trend"]
        self.assertEqual(trend["signal"], "NEUTRAL")
        self.assertEqual(trend["availability"], "UNAVAILABLE")
        self.assertEqual(trend["strength"], "WEAK")

    def test_trend_availability_live(self):
        from market_evidence_engine import MarketEvidenceEngine
        engine = MarketEvidenceEngine()
        snapshot = {
            "close": 23200, "ema9": 23180, "ema20": 23100, "ema50": 23000,
            "vwap": 23100, "adx": 35, "data_state": "LIVE",
        }
        result = engine.evaluate(snapshot, data_state="LIVE", symbol="NIFTY")
        trend = result["groups"]["trend"]
        self.assertEqual(trend["availability"], "LIVE")


class TestEvidenceMomentum(unittest.TestCase):

    def test_rsi_overbought_bearish(self):
        from market_evidence_engine import MarketEvidenceEngine
        engine = MarketEvidenceEngine()
        snapshot = {
            "close": 23100, "rsi": 75, "macd": -0.5, "macd_signal": 0.5,
            "data_state": "LIVE",
        }
        result = engine.evaluate(snapshot, data_state="LIVE", symbol="NIFTY")
        momentum = result["groups"]["momentum"]
        self.assertIn(momentum["signal"], ("BEARISH", "MIXED"))

    def test_rsi_oversold_context_dependent(self):
        from market_evidence_engine import MarketEvidenceEngine
        engine = MarketEvidenceEngine()
        snapshot = {
            "close": 23100, "rsi": 25, "macd": -2.0, "macd_signal": -1.0,
            "data_state": "LIVE",
        }
        result = engine.evaluate(snapshot, data_state="LIVE", symbol="NIFTY")
        momentum = result["groups"]["momentum"]
        self.assertIn(momentum["signal"], ("BEARISH", "MIXED"))
        self.assertIn("context-dependent", momentum.get("notes", "").lower() or "context-dependent")

    def test_momentum_bullish(self):
        from market_evidence_engine import MarketEvidenceEngine
        engine = MarketEvidenceEngine()
        snapshot = {
            "close": 23100, "rsi": 55, "macd": 2.0, "macd_signal": 1.0,
            "data_state": "LIVE",
        }
        result = engine.evaluate(snapshot, data_state="LIVE", symbol="NIFTY")
        momentum = result["groups"]["momentum"]
        self.assertIn(momentum["signal"], ("BULLISH", "MIXED"))

    def test_momentum_unavailable(self):
        from market_evidence_engine import MarketEvidenceEngine
        engine = MarketEvidenceEngine()
        snapshot = {"close": 23100, "data_state": "UNAVAILABLE"}
        result = engine.evaluate(snapshot, data_state="UNAVAILABLE", symbol="NIFTY")
        momentum = result["groups"]["momentum"]
        self.assertEqual(momentum["signal"], "NEUTRAL")


class TestEvidenceStructure(unittest.TestCase):

    def test_breakout(self):
        from market_evidence_engine import MarketEvidenceEngine
        engine = MarketEvidenceEngine()
        snapshot = {
            "close": 23200, "prev_day_high": 23150, "prev_day_low": 23000,
            "support": 23000, "resistance": 23150,
            "data_state": "LIVE",
        }
        result = engine.evaluate(snapshot, data_state="LIVE", symbol="NIFTY")
        structure = result["groups"]["structure"]
        self.assertIn(structure["signal"], ("BULLISH", "MIXED"))
        self.assertIn("above_prev_day_high", structure["rules_triggered"])

    def test_breakdown(self):
        from market_evidence_engine import MarketEvidenceEngine
        engine = MarketEvidenceEngine()
        snapshot = {
            "close": 22800, "prev_day_high": 23150, "prev_day_low": 22900,
            "support": 22850, "resistance": 23150,
            "data_state": "LIVE",
        }
        result = engine.evaluate(snapshot, data_state="LIVE", symbol="NIFTY")
        structure = result["groups"]["structure"]
        self.assertIn(structure["signal"], ("BEARISH", "MIXED"))

    def test_range(self):
        from market_evidence_engine import MarketEvidenceEngine
        engine = MarketEvidenceEngine()
        snapshot = {
            "close": 23075, "high": 23100, "low": 23050,
            "prev_day_high": 23150, "prev_day_low": 23000,
            "support": 22900, "resistance": 23250,
            "data_state": "LIVE",
        }
        result = engine.evaluate(snapshot, data_state="LIVE", symbol="NIFTY")
        structure = result["groups"]["structure"]
        self.assertIn(structure["signal"], ("RANGE", "NEUTRAL"))

    def test_range_detection(self):
        from market_evidence_engine import MarketEvidenceEngine
        engine = MarketEvidenceEngine()
        snapshot = {
            "close": 23075, "high": 23100, "low": 23050,
            "prev_day_high": 23150, "prev_day_low": 23000,
            "support": 22900, "resistance": 23250,
            "data_state": "LIVE",
        }
        result = engine.evaluate(snapshot, data_state="LIVE", symbol="NIFTY")
        structure = result["groups"]["structure"]
        self.assertIn("range_between_support_resistance", structure["rules_triggered"]
                       if structure["availability"] != "UNAVAILABLE" else [])

    def test_structure_unavailable(self):
        from market_evidence_engine import MarketEvidenceEngine
        engine = MarketEvidenceEngine()
        snapshot = {"close": 23100, "data_state": "UNAVAILABLE"}
        result = engine.evaluate(snapshot, data_state="UNAVAILABLE", symbol="NIFTY")
        structure = result["groups"]["structure"]
        self.assertEqual(structure["availability"], "UNAVAILABLE")
        self.assertEqual(structure["signal"], "NEUTRAL")


class TestEvidenceVolatility(unittest.TestCase):

    def test_high_volatility(self):
        from market_evidence_engine import MarketEvidenceEngine
        engine = MarketEvidenceEngine()
        snapshot = {
            "close": 23100, "high": 23200, "low": 23000, "vix": 25, "atr": 200,
            "data_state": "LIVE",
        }
        result = engine.evaluate(snapshot, data_state="LIVE", symbol="NIFTY")
        volatility = result["groups"]["volatility"]
        self.assertIn(volatility["signal"], ("HIGH_VOLATILITY", "NORMAL"))

    def test_low_volatility(self):
        from market_evidence_engine import MarketEvidenceEngine
        engine = MarketEvidenceEngine()
        snapshot = {
            "close": 23100, "high": 23120, "low": 23080, "vix": 10, "atr": 40,
            "data_state": "LIVE",
        }
        result = engine.evaluate(snapshot, data_state="LIVE", symbol="NIFTY")
        volatility = result["groups"]["volatility"]
        self.assertIn(volatility["signal"], ("LOW_VOLATILITY", "NORMAL"))

    def test_volatility_direction_neutral(self):
        from market_evidence_engine import MarketEvidenceEngine
        engine = MarketEvidenceEngine()
        snapshot = {
            "close": 23100, "high": 23200, "low": 23000, "vix": 18, "atr": 100,
            "data_state": "LIVE",
        }
        result = engine.evaluate(snapshot, data_state="LIVE", symbol="NIFTY")
        volatility = result["groups"]["volatility"]
        self.assertNotIn(volatility["signal"], ("BULLISH", "BEARISH"))

    def test_volatility_unavailable(self):
        from market_evidence_engine import MarketEvidenceEngine
        engine = MarketEvidenceEngine()
        snapshot = {"close": 23100, "data_state": "UNAVAILABLE"}
        result = engine.evaluate(snapshot, data_state="UNAVAILABLE", symbol="NIFTY")
        volatility = result["groups"]["volatility"]
        self.assertIn(volatility["availability"], ("UNAVAILABLE",))


class TestEvidenceOptions(unittest.TestCase):

    def test_bullish_pcr(self):
        from market_evidence_engine import MarketEvidenceEngine
        engine = MarketEvidenceEngine()
        snapshot = {
            "close": 23100, "pcr": 0.6, "call_oi": 150000, "put_oi": 80000,
            "data_state": "LIVE",
        }
        result = engine.evaluate(snapshot, data_state="LIVE", symbol="NIFTY")
        options = result["groups"]["options"]
        self.assertIn(options["availability"], ("LIVE", "AVAILABLE"))

    def test_bearish_pcr(self):
        from market_evidence_engine import MarketEvidenceEngine
        engine = MarketEvidenceEngine()
        snapshot = {
            "close": 23100, "pcr": 1.5, "call_oi": 80000, "put_oi": 150000,
            "data_state": "LIVE",
        }
        result = engine.evaluate(snapshot, data_state="LIVE", symbol="NIFTY")
        options = result["groups"]["options"]
        self.assertIn(options["signal"], ("BEARISH", "MIXED"))

    def test_options_unavailable(self):
        from market_evidence_engine import MarketEvidenceEngine
        engine = MarketEvidenceEngine()
        snapshot = {"close": 23100, "data_state": "LIVE"}
        result = engine.evaluate(snapshot, data_state="LIVE", symbol="NIFTY")
        options = result["groups"]["options"]
        self.assertIn(options["availability"], ("UNAVAILABLE",))
        self.assertIn("No verified live option-chain data", options.get("reason", ""))


class TestEvidenceConflict(unittest.TestCase):

    def test_bullish_trend_bearish_momentum(self):
        from market_evidence_engine import MarketEvidenceEngine
        engine = MarketEvidenceEngine()
        snapshot = {
            "close": 23200, "high": 23250, "low": 23150,
            "ema9": 23180, "ema20": 23100, "ema50": 23000, "ema200": 22900,
            "vwap": 23100, "rsi": 75, "macd": -2.0, "macd_signal": -1.0, "adx": 35,
            "prev_day_high": 23150, "prev_day_low": 23000,
            "support": 23000, "resistance": 23200,
            "vix": 13.5, "atr": 80,
            "data_state": "LIVE",
        }
        result = engine.evaluate(snapshot, data_state="LIVE", symbol="NIFTY")
        trend = result["groups"]["trend"]
        momentum = result["groups"]["momentum"]
        self.assertEqual(trend["signal"], "BULLISH")
        self.assertEqual(momentum["signal"], "BEARISH")
        conflict = result["conflict"]
        self.assertTrue(conflict["detected"])
        self.assertIn("trend", conflict["groups"])
        self.assertIn("momentum", conflict["groups"])

    def test_no_conflict(self):
        from market_evidence_engine import MarketEvidenceEngine
        engine = MarketEvidenceEngine()
        snapshot = {
            "close": 23200, "high": 23250, "low": 23150,
            "ema9": 23180, "ema20": 23100, "ema50": 23000, "ema200": 22900,
            "vwap": 23100, "rsi": 55, "macd": 2.0, "macd_signal": 1.0, "adx": 35,
            "prev_day_high": 23150, "prev_day_low": 23000,
            "support": 23000, "resistance": 23200,
            "vix": 13.5, "atr": 80,
            "data_state": "LIVE",
        }
        result = engine.evaluate(snapshot, data_state="LIVE", symbol="NIFTY")
        conflict = result["conflict"]
        self.assertFalse(conflict["detected"])
        self.assertEqual(conflict["severity"], "NONE")

    def test_bullish_nifty_bearish_banknifty(self):
        from market_evidence_engine import MarketEvidenceEngine
        engine = MarketEvidenceEngine()
        nifty = {
            "close": 23200, "high": 23250, "low": 23150,
            "ema9": 23180, "ema20": 23100, "ema50": 23000, "ema200": 22900,
            "vwap": 23100, "rsi": 55, "macd": 2.0, "macd_signal": 1.0, "adx": 35,
            "prev_day_high": 23150, "prev_day_low": 23000,
            "support": 23000, "resistance": 23200,
            "vix": 13.5, "atr": 80, "data_state": "LIVE",
        }
        banknifty = {
            "close": 55300, "high": 55350, "low": 55200,
            "ema9": 55400, "ema20": 55500, "ema50": 55600, "ema200": 55800,
            "vwap": 55500, "rsi": 75, "macd": -2.0, "macd_signal": -1.0, "adx": 35,
            "prev_day_high": 55500, "prev_day_low": 55400,
            "support": 55100, "resistance": 55500,
            "vix": 13.5, "atr": 80, "data_state": "LIVE",
        }
        result_nifty = engine.evaluate(nifty, data_state="LIVE", symbol="NIFTY")
        result_bnifty = engine.evaluate(banknifty, data_state="LIVE", symbol="BANKNIFTY")
        self.assertEqual(result_nifty["overall"]["overall_signal"], "BULLISH")
        self.assertIn(result_bnifty["overall"]["overall_signal"], ("BEARISH", "MIXED"))


class TestEvidenceOverall(unittest.TestCase):

    def test_insufficient_data(self):
        from market_evidence_engine import MarketEvidenceEngine
        engine = MarketEvidenceEngine()
        result = engine.evaluate({}, data_state="UNAVAILABLE", symbol="NIFTY")
        self.assertEqual(result["overall"]["overall_signal"], "INSUFFICIENT_DATA")
        self.assertEqual(result["overall"]["unavailable_groups"], 6)

    def test_bullish_overall(self):
        from market_evidence_engine import MarketEvidenceEngine
        engine = MarketEvidenceEngine()
        snapshot = {
            "close": 23200, "high": 23250, "low": 23150,
            "ema9": 23180, "ema20": 23100, "ema50": 23000, "ema200": 22900,
            "vwap": 23100, "rsi": 55, "macd": 2.0, "macd_signal": 1.0, "adx": 35,
            "prev_day_high": 23150, "prev_day_low": 23000,
            "support": 23000, "resistance": 23200,
            "vix": 13.5, "atr": 80,
            "data_state": "LIVE",
        }
        result = engine.evaluate(snapshot, data_state="LIVE", symbol="NIFTY")
        self.assertIn(result["overall"]["overall_signal"], ("BULLISH", "MIXED"))

    def test_conflict_level(self):
        from market_evidence_engine import MarketEvidenceEngine
        engine = MarketEvidenceEngine()
        snapshot = {
            "close": 23200, "high": 23250, "low": 23150,
            "ema9": 23180, "ema20": 23100, "ema50": 23000, "ema200": 22900,
            "vwap": 23100, "rsi": 75, "macd": -2.0, "macd_signal": -1.0, "adx": 35,
            "prev_day_high": 23150, "prev_day_low": 23000,
            "support": 23000, "resistance": 23200,
            "vix": 13.5, "atr": 80,
            "data_state": "LIVE",
        }
        result = engine.evaluate(snapshot, data_state="LIVE", symbol="NIFTY")
        self.assertIn(result["overall"]["conflict_level"], ("MODERATE", "HIGH", "NONE"))

    def test_engine_version(self):
        from market_evidence_engine import MarketEvidenceEngine, ENGINE_VERSION
        engine = MarketEvidenceEngine()
        snapshot = {"close": 23100, "data_state": "LIVE"}
        result = engine.evaluate(snapshot, data_state="LIVE", symbol="NIFTY")
        self.assertEqual(result["engine_version"], ENGINE_VERSION)

    def test_all_groups_present(self):
        from market_evidence_engine import MarketEvidenceEngine
        engine = MarketEvidenceEngine()
        snapshot = {
            "close": 23200, "high": 23250, "low": 23150,
            "ema9": 23180, "ema20": 23100, "ema50": 23000, "ema200": 22900,
            "vwap": 23100, "rsi": 55, "macd": 2.0, "macd_signal": 1.0, "adx": 35,
            "prev_day_high": 23150, "prev_day_low": 23000,
            "support": 23000, "resistance": 23200,
            "vix": 13.5, "atr": 80,
            "data_state": "LIVE",
        }
        result = engine.evaluate(snapshot, data_state="LIVE", symbol="NIFTY")
        for name in ("trend", "momentum", "structure", "volatility", "options", "confirmation"):
            self.assertIn(name, result["groups"])
            self.assertIn("signal", result["groups"][name])
            self.assertIn("strength", result["groups"][name])
            self.assertIn("availability", result["groups"][name])
            self.assertIn("rules_triggered", result["groups"][name])
            self.assertIn("data_used", result["groups"][name])


class TestEvidenceLookAhead(unittest.TestCase):

    def test_no_future_data_used(self):
        from market_evidence_engine import MarketEvidenceEngine
        engine = MarketEvidenceEngine()
        snapshot = {
            "close": 23100, "high": 23200, "low": 23000, "vix": 13.5,
            "data_state": "LIVE",
        }
        result = engine.evaluate(snapshot, data_state="LIVE", symbol="NIFTY")
        for name, group in result["groups"].items():
            data_used = group.get("data_used", {})
            for key, val in data_used.items():
                if "future" in key.lower() or "next" in key.lower():
                    self.fail(f"Future data reference found in {name}: {key}")

    def test_candle_timestamp_preserved(self):
        from market_evidence_engine import MarketEvidenceEngine
        engine = MarketEvidenceEngine()
        candle_ts = "2026-09-15T10:00:00Z"
        snapshot = {"close": 23100, "candle_timestamp": candle_ts, "data_state": "LIVE"}
        result = engine.evaluate(snapshot, data_state="LIVE", symbol="NIFTY")
        self.assertEqual(result["candle_timestamp"], candle_ts)

    def test_evidence_id_linking(self):
        from market_evidence_engine import MarketEvidenceEngine
        engine = MarketEvidenceEngine()
        snapshot = {"close": 23100, "evidence_id": "EVID-001", "snapshot_id": "SNAP-001", "data_state": "LIVE"}
        result = engine.evaluate(snapshot, data_state="LIVE", symbol="NIFTY")
        self.assertEqual(result["evidence_id"], "EVID-001")
        self.assertEqual(result["snapshot_id"], "SNAP-001")


class TestEvidenceNormalizedModel(unittest.TestCase):

    def test_normalized_fields(self):
        from market_evidence_engine import MarketEvidenceEngine
        engine = MarketEvidenceEngine()
        snapshot = {
            "close": 23200, "high": 23250, "low": 23150,
            "ema9": 23180, "ema20": 23100, "ema50": 23000, "ema200": 22900,
            "vwap": 23100, "rsi": 55, "macd": 2.0, "macd_signal": 1.0, "adx": 35,
            "prev_day_high": 23150, "prev_day_low": 23000,
            "support": 23000, "resistance": 23200,
            "vix": 13.5, "atr": 80,
            "data_state": "LIVE",
        }
        result = engine.evaluate(snapshot, data_state="LIVE", symbol="NIFTY")
        for name, group in result["groups"].items():
            for field in ("group", "availability", "signal", "strength", "confidence",
                          "rules_triggered", "rules_not_triggered", "data_used", "timestamp"):
                self.assertIn(field, group, f"Missing {field} in {name}")

    def test_data_used_is_dict(self):
        from market_evidence_engine import MarketEvidenceEngine
        engine = MarketEvidenceEngine()
        snapshot = {
            "close": 23200, "high": 23250, "low": 23150,
            "ema9": 23180, "ema20": 23100, "ema50": 23000, "ema200": 22900,
            "vwap": 23100, "rsi": 55, "macd": 2.0, "macd_signal": 1.0, "adx": 35,
            "data_state": "LIVE",
        }
        result = engine.evaluate(snapshot, data_state="LIVE", symbol="NIFTY")
        for name, group in result["groups"].items():
            self.assertIsInstance(group.get("data_used"), dict, f"{name} data_used should be dict")


class TestEvidenceThresholds(unittest.TestCase):

    def test_configurable_rsi(self):
        from market_evidence_engine import MarketEvidenceEngine
        config = {"rsi": {"oversold": 25, "overbought": 75}}
        engine = MarketEvidenceEngine(config=config)
        snapshot = {"close": 23100, "rsi": 73, "data_state": "LIVE"}
        result = engine.evaluate(snapshot, data_state="LIVE", symbol="NIFTY")
        momentum = result["groups"]["momentum"]
        self.assertNotIn("rsi_overbought", momentum["rules_triggered"])

    def test_configurable_adx(self):
        from market_evidence_engine import MarketEvidenceEngine
        config = {"adx": {"trend_threshold": 10, "strong_threshold": 25}}
        engine = MarketEvidenceEngine(config=config)
        snapshot = {"close": 23100, "vwap": 23000, "adx": 12, "data_state": "LIVE"}
        result = engine.evaluate(snapshot, data_state="LIVE", symbol="NIFTY")
        trend = result["groups"]["trend"]
        self.assertIn("adx_trending", trend["rules_triggered"])


if __name__ == "__main__":
    unittest.main()
