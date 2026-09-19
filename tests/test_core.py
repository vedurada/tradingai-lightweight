import unittest, sys, os, json, sqlite3
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.core.config import settings, instruments
from app.core.qualification import QualificationEngine
from app.strategies.engine import StrategyEngine
from app.risk.engine import RiskEngine
from app.scenarios.engine import ScenarioEngine
from app.ai.explanation import AIExplanation
from app.research.backtest import BacktestEngine
from app.paper_trade.engine import PaperTradeEngine
from app.market.provider import MarketDataProvider

class TestConfig(unittest.TestCase):
    def test_instruments_loaded(self):
        self.assertTrue(len(instruments) > 0)
        ids = [i["instrument_id"] for i in instruments]
        self.assertIn("NIFTY", ids)
        self.assertIn("BANKNIFTY", ids)

    def test_settings_loaded(self):
        self.assertIn("market", settings)
        self.assertIn("database", settings)
        self.assertIn("risk", settings)

class TestStrategyEngine(unittest.TestCase):
    def test_bullish_high_vol(self):
        s = StrategyEngine()
        r = s.select_strategy("BULLISH_CONTINUATION", "BULLISH", "HIGH")
        self.assertEqual(r["strategy"], "Bull Call Spread")
        self.assertEqual(r["objective"], "DIRECTIONAL")

    def test_bearish_low_vol(self):
        s = StrategyEngine()
        r = s.select_strategy("BEARISH_CONTINUATION", "BEARISH", "NORMAL")
        self.assertEqual(r["strategy"], "Bear Call Spread")

    def test_range_theta(self):
        s = StrategyEngine()
        r = s.select_strategy("RANGE_PREMIUM_DECAY", "NEUTRAL", "LOW")
        self.assertEqual(r["strategy"], "Iron Condor")
        self.assertEqual(r["objective"], "THETA_DECAY")

    def test_options_unavailable(self):
        s = StrategyEngine()
        r = s.select_strategy("BULLISH_CONTINUATION", "BULLISH", "NORMAL", options_valid=False)
        self.assertEqual(r["status"], "NO_TRADE")

class TestRiskEngine(unittest.TestCase):
    def test_valid_trade(self):
        r = RiskEngine()
        ok, reasons = r.validate({"entry": 25000, "stop": 24750, "target": 25500})
        self.assertTrue(ok)

    def test_insufficient_rr(self):
        r = RiskEngine()
        ok, reasons = r.validate({"entry": 25000, "stop": 24900, "target": 25050})
        self.assertFalse(ok)

    def test_zero_risk(self):
        r = RiskEngine()
        ok, reasons = r.validate({"entry": 25000, "stop": 25000, "target": 25500})
        self.assertFalse(ok)

class TestAIExplanation(unittest.TestCase):
    def test_ai_explanation(self):
        ai = AIExplanation()
        result = ai.explain({"decision": "QUALIFIED_TRADE"})
        self.assertEqual(result["status"], "AI_AVAILABLE")

    def test_ai_independence(self):
        ai_enabled = AIExplanation()
        ai_disabled = AIExplanation()
        ai_disabled.enabled = False
        decision = {"decision": "NO_TRADE", "market_state": {}, "scenario": "N/A"}
        r1 = ai_enabled.explain(decision)
        r2 = ai_disabled.explain(decision)
        self.assertEqual(r1["status"], "AI_AVAILABLE")
        self.assertEqual(r2["status"], "AI_UNAVAILABLE")

class TestDatabase(unittest.TestCase):
    def test_tables_exist(self):
        from app.core.db import get_conn
        conn = get_conn()
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        conn.close()
        required = ["instruments", "trading_sessions", "market_candles_5m", "paper_trades",
                     "backtest_runs", "qualified_trades", "daily_trade_locks", "scenario_definitions"]
        for t in required:
            self.assertIn(t, tables, f"Missing table: {t}")

if __name__ == "__main__":
    unittest.main()
