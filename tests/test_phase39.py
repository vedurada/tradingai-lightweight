import json
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))


class TestOutlookChangeDetector(unittest.TestCase):

    def test_evaluate_returns_structure(self):
        from outlook_change_detector import evaluate
        with patch("outlook_change_detector.get_db") as mock_db:
            conn = MagicMock()
            conn.execute.return_value.fetchone.return_value = None
            mock_db.return_value = conn
            result = evaluate("NIFTY")

            self.assertIn("symbol", result)
            self.assertIn("current_state", result)
            self.assertIn("material_change", result)
            self.assertIn("change_reason", result)
            self.assertIn("changes", result)
            self.assertIn("regenerate_ai", result)
            self.assertIn("regenerate_reason", result)
            self.assertIn("ai_outlook_age_minutes", result)

    def test_evaluate_current_state_fields(self):
        from outlook_change_detector import evaluate
        with patch("outlook_change_detector.get_db") as mock_db:
            conn = MagicMock()
            conn.execute.return_value.fetchone.return_value = None
            mock_db.return_value = conn
            result = evaluate("NIFTY")
            cs = result["current_state"]
            for field in ("regime", "trend", "confidence", "price_vs_vwap", "vix", "rsi", "adx", "captured_at"):
                self.assertIn(field, cs, f"Missing field: {field}")

    def test_needs_ai_outlook_structure(self):
        from outlook_change_detector import needs_ai_outlook
        with patch("outlook_change_detector.should_regenerate_ai") as mock_regen:
            mock_regen.return_value = {
                "symbol": "NIFTY", "regenerate": True, "reason": "material_change",
                "material_changes": [], "ai_outlook_age_minutes": None, "max_age_minutes": 30,
            }
            result = needs_ai_outlook("NIFTY")
            self.assertTrue(result["needs_ai"])
            self.assertEqual(result["reason"], "material_change")
            self.assertIn("material_changes", result)

    def test_evaluate_material_change(self):
        from outlook_change_detector import evaluate
        with patch("outlook_change_detector.get_db") as mock_db:
            with patch("outlook_change_detector.is_material_change") as mock_change:
                with patch("outlook_change_detector.should_regenerate_ai") as mock_regen:
                    conn = MagicMock()
                    conn.execute.return_value.fetchone.return_value = None
                    mock_db.return_value = conn
                    mock_change.return_value = {
                        "material": True, "reason": "regime_change",
                        "changes": [{"type": "regime_change", "from": "BEARISH", "to": "BULLISH", "severity": "high"}],
                    }
                    mock_regen.return_value = {
                        "symbol": "NIFTY", "regenerate": True, "reason": "material_change",
                        "material_changes": [{"type": "regime_change"}],
                        "ai_outlook_age_minutes": 45, "max_age_minutes": 30,
                    }
                    result = evaluate("NIFTY")
                    self.assertTrue(result["material_change"])
                    self.assertEqual(len(result["changes"]), 1)
                    self.assertEqual(result["regenerate_ai"], True)

    def test_evaluate_no_material_change(self):
        from outlook_change_detector import evaluate
        with patch("outlook_change_detector.get_db") as mock_db:
            with patch("outlook_change_detector.is_material_change") as mock_change:
                with patch("outlook_change_detector.should_regenerate_ai") as mock_regen:
                    conn = MagicMock()
                    conn.execute.return_value.fetchone.return_value = None
                    mock_db.return_value = conn
                    mock_change.return_value = {"material": False, "reason": "no_significant_change", "changes": []}
                    mock_regen.return_value = {
                        "symbol": "NIFTY", "regenerate": False, "reason": "no_change",
                        "material_changes": [], "ai_outlook_age_minutes": 5, "max_age_minutes": 30,
                    }
                    result = evaluate("NIFTY")
                    self.assertFalse(result["material_change"])
                    self.assertEqual(result["regenerate_ai"], False)

    def test_evaluate_cleans_up_connection(self):
        from outlook_change_detector import evaluate
        mock_conn = MagicMock()
        with patch("outlook_change_detector.get_db", return_value=mock_conn):
            try:
                evaluate("NIFTY")
            except Exception:
                pass
            finally:
                mock_conn.close.assert_called_once()


class TestAIOutlookGenerator5m(unittest.TestCase):

    def test_generate_basic_structure(self):
        from ai_outlook_5m import AIOutlookGenerator5m
        generator = AIOutlookGenerator5m()
        market_state = {
            "regime": {"regime": "BEARISH", "trend": "BEARISH", "confidence": 70},
            "captured_at": "2026-09-15T10:00:00Z",
        }
        result = generator.generate("NIFTY", market_state)

        required = ("outlook_id", "instrument", "generated_at", "candle_timestamp",
                     "model", "model_version", "prompt_version", "bias", "confidence",
                     "market_regime", "summary", "evidence", "trade_state",
                     "expected_horizon_minutes", "data_state")
        for field in required:
            self.assertIn(field, result, f"Missing: {field}")
        self.assertEqual(result["instrument"], "NIFTY")

    def test_validate_bias_normalization(self):
        from ai_outlook_5m import AIOutlookGenerator5m
        generator = AIOutlookGenerator5m()
        invalid = {"bias": "INVALID", "confidence": "abc", "trade_state": "INVALID"}
        result = generator._validate(invalid, "NIFTY", "2026-09-15T10:00:00Z")
        self.assertEqual(result["bias"], "MIXED")
        self.assertEqual(result["confidence"], 0)
        self.assertEqual(result["trade_state"], "NO_TRADE")

    def test_validate_confidence_clamping(self):
        from ai_outlook_5m import AIOutlookGenerator5m
        generator = AIOutlookGenerator5m()
        self.assertEqual(generator._validate({"confidence": 150}, "NIFTY", "")["confidence"], 100)
        self.assertEqual(generator._validate({"confidence": -20}, "NIFTY", "")["confidence"], 0)
        self.assertEqual(generator._validate({"confidence": 75.5}, "NIFTY", "")["confidence"], 75)

    def test_fallback_outlook(self):
        from ai_outlook_5m import AIOutlookGenerator5m
        generator = AIOutlookGenerator5m()
        result = generator._fallback_outlook()
        self.assertEqual(result["trade_state"], "NO_TRADE")
        self.assertEqual(result["bias"], "MIXED")
        self.assertEqual(result["summary"], "AI outlook temporarily unavailable")

    def test_generate_with_material_changes(self):
        from ai_outlook_5m import AIOutlookGenerator5m
        generator = AIOutlookGenerator5m()
        market_state = {
            "regime": {"regime": "BULLISH", "trend": "BULLISH", "confidence": 80},
            "captured_at": "2026-09-15T10:00:00Z",
        }
        changes = [{"type": "regime_change", "from": "BEARISH", "to": "BULLISH"}]
        result = generator.generate("NIFTY", market_state, changes)
        self.assertEqual(result["material_changes"], changes)
        self.assertEqual(result["data_state"], "LIVE")


class TestMarketStateEngine(unittest.TestCase):

    def test_evaluate_basic(self):
        from market_state_engine import MarketStateEngine
        engine = MarketStateEngine()
        snapshot = {
            "close": 23100,
            "indicators": {
                "ema9": 23050, "ema21": 23030, "ema20": 23010, "ema200": 22950,
                "rsi": 55, "adx": 35, "vwap": 23080, "atr": 80,
                "bollinger_bands": {"width": 1.5}, "macd": {"macd": 1.5, "signal": 1.0},
            },
        }
        result = engine.evaluate("NIFTY", snapshot)
        self.assertEqual(result["symbol"], "NIFTY")
        self.assertIn(result["market_regime"], ("BULLISH", "MIXED", "RANGE"))
        self.assertIn(result["trend_state"], ("UP", "STRONG_UP", "NEUTRAL", "DOWN"))
        self.assertIn(result["price_vs_vwap"], ("ABOVE", "NEAR", "BELOW", "UNKNOWN"))
        self.assertIn(result["volatility_state"], ("LOW", "NORMAL", "HIGH"))
        self.assertIn(result["trade_state"], ("TRADE", "WAIT", "NO_TRADE"))

    def test_evaluate_unavailable(self):
        from market_state_engine import MarketStateEngine
        engine = MarketStateEngine()
        result = engine.evaluate("NIFTY", {})
        self.assertEqual(result["market_regime"], "UNAVAILABLE")
        self.assertEqual(result["trade_state"], "NO_TRADE")

    def test_deterministic_same_input(self):
        from market_state_engine import MarketStateEngine
        engine = MarketStateEngine()
        snapshot = {
            "close": 23100,
            "indicators": {
                "ema9": 23050, "ema21": 23030, "ema20": 23010, "ema200": 22950,
                "rsi": 55, "adx": 35, "vwap": 23080, "atr": 80,
                "bollinger_bands": {"width": 1.5}, "macd": {"macd": 1.5, "signal": 1.0},
            },
        }
        r1 = engine.evaluate("NIFTY", snapshot)
        r2 = engine.evaluate("NIFTY", snapshot)
        self.assertEqual(r1["market_regime"], r2["market_regime"])
        self.assertEqual(r1["trend_state"], r2["trend_state"])
        self.assertEqual(r1["trade_state"], r2["trade_state"])


class TestMarketSnapshot(unittest.TestCase):

    def test_price_vs_vwap(self):
        from market_snapshot import _price_vs_vwap
        self.assertEqual(_price_vs_vwap(23000, 23150), "ABOVE")
        self.assertEqual(_price_vs_vwap(23000, 22850), "BELOW")
        self.assertEqual(_price_vs_vwap(23000, 23050), "NEAR")
        self.assertEqual(_price_vs_vwap(23000, 23049), "NEAR")
        self.assertEqual(_price_vs_vwap(None, 23100), "UNKNOWN")
        self.assertEqual(_price_vs_vwap(23000, None), "UNKNOWN")
        self.assertEqual(_price_vs_vwap(0, 23100), "UNKNOWN")


class TestOutcomeEngine(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        from outcome_engine import OutcomeEngine
        from db_schema import SCHEMA
        self.engine = OutcomeEngine(db_path=os.path.join(self.tmpdir, "test.db"))
        conn = __import__("sqlite3").connect(os.path.join(self.tmpdir, "test.db"))
        conn.executescript(SCHEMA)
        conn.close()

    def test_record_outcome_basic(self):
        result = self.engine.record_outcome("TEST-123", "NIFTY", 23100.0, 5)
        self.assertEqual(result["outlook_id"], "TEST-123")
        self.assertEqual(result["symbol"], "NIFTY")
        self.assertEqual(result["status"], "PENDING")

    def test_record_outcome_invalid_horizon(self):
        result = self.engine.record_outcome("TEST-123", "NIFTY", 23100.0, horizon_minutes=999)
        self.assertIn("error", result)

    def test_evaluate_outcome_not_found(self):
        result = self.engine.evaluate_outcome("NONEXISTENT", "NIFTY", 5)
        self.assertIsNone(result)

    def test_get_pending_evaluations_empty(self):
        result = self.engine.get_pending_evaluations()
        self.assertEqual(result, [])

    def test_get_aggregate_stats_insufficient(self):
        stats = self.engine.get_aggregate_stats(min_sample=10)
        self.assertEqual(stats["status"], "INSUFFICIENT_DATA")


class TestOutlookScheduler(unittest.TestCase):

    def test_is_market_open(self):
        from outlook_scheduler import is_market_open
        result = is_market_open()
        self.assertIn("market_open", result)
        self.assertIn("session", result)
        self.assertIn("ist_time", result)

    def test_get_current_candle(self):
        from outlook_scheduler import get_current_candle_timestamp
        ts = get_current_candle_timestamp()
        if ts is not None:
            self.assertIn("T", ts)
            self.assertTrue(ts.startswith("2026"))

    def test_scheduler_structure(self):
        from outlook_scheduler import OutlookScheduler
        scheduler = OutlookScheduler()
        self.assertTrue(hasattr(scheduler, "run"))
        self.assertTrue(hasattr(scheduler, "_process_symbol"))
        self.assertTrue(hasattr(scheduler, "_generate_ai_outlook"))
        self.assertTrue(hasattr(scheduler, "_store_outlook"))


class TestDbSchemaPhase39(unittest.TestCase):

    def test_tables_exist_in_schema(self):
        from db_schema import SCHEMA
        for table in ("ai_outlooks_5m", "ai_outcome_predictions", "market_snapshots_5m"):
            self.assertIn(table, SCHEMA, f"Table {table} not in schema")

    def test_ai_outlooks_columns(self):
        from db_schema import SCHEMA
        required = ("outlook_id", "instrument", "candle_timestamp", "generated_at",
                     "bias", "confidence", "market_regime", "trade_state", "data_state",
                     "model", "prompt_version")
        for col in required:
            self.assertIn(col, SCHEMA, f"Missing column: {col}")

    def test_outcome_columns(self):
        from db_schema import SCHEMA
        required = ("outlook_id", "symbol", "entry_price", "reference_price",
                     "horizon_minutes", "future_return_pct", "correct", "recorded_at", "status")
        for col in required:
            self.assertIn(col, SCHEMA, f"Missing column: {col}")

    def test_snapshot_columns(self):
        from db_schema import SCHEMA
        required = ("symbol", "candle_timestamp", "close", "vwap", "price_vs_vwap",
                     "trend_state", "volatility_state", "regime", "data_state")
        for col in required:
            self.assertIn(col, SCHEMA, f"Missing column: {col}")


class TestApiEndpoints(unittest.TestCase):

    def test_ai_outlook_endpoint_structure(self):
        from db_schema import init_database
        init_database("/tmp/test_phase39_db.sqlite")
        import api_server
        app = api_server.app
        client = app.test_client()
        with app.app_context():
            resp = client.get("/api/ai-outlook/NIFTY")
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertTrue(data["success"])
            self.assertIn("data", data)
            self.assertIn("instrument", data["data"])
            self.assertIn("current", data["data"])
            self.assertIn("previous", data["data"])
            self.assertIn("change", data["data"])
            self.assertIn("timeline", data["data"])
            self.assertIn("data_state", data["data"])
            self.assertIn("market_status", data["data"])

    def test_ai_outlook_scheduler_endpoint(self):
        import api_server
        app = api_server.app
        client = app.test_client()
        with app.app_context():
            resp = client.get("/api/ai-outlook/scheduler")
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertTrue(data["success"])
            self.assertIn("data", data)


if __name__ == "__main__":
    unittest.main()
