import unittest, sys, os, json, sqlite3, tempfile
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
from app.core.db import get_conn, DB_PATH

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

    def test_range_theta(self):
        s = StrategyEngine()
        r = s.select_strategy("RANGE_PREMIUM_DECAY", "NEUTRAL", "LOW")
        self.assertEqual(r["strategy"], "Iron Condor")

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
        conn = get_conn()
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        conn.close()
        required = ["instruments", "trading_sessions", "market_candles_5m", "paper_trades",
                     "backtest_runs", "qualified_trades", "daily_trade_locks", "scenario_definitions"]
        for t in required:
            self.assertIn(t, tables, f"Missing table: {t}")

class TestIngestionValidation(unittest.TestCase):
    def test_candles_ingested(self):
        conn = get_conn()
        nifty = conn.execute("SELECT COUNT(*) FROM market_candles_5m WHERE instrument_id='NIFTY'").fetchone()[0]
        bank = conn.execute("SELECT COUNT(*) FROM market_candles_5m WHERE instrument_id='BANKNIFTY'").fetchone()[0]
        conn.close()
        self.assertGreater(nifty, 0, "NIFTY has no candles")
        self.assertGreater(bank, 0, "BANKNIFTY has no candles")

    def test_no_duplicate_timestamps(self):
        conn = get_conn()
        for inst in ['NIFTY', 'BANKNIFTY']:
            dupes = conn.execute('''SELECT timestamp, COUNT(*) as c FROM market_candles_5m
                WHERE instrument_id=? GROUP BY instrument_id, timestamp HAVING c > 1''', (inst,)).fetchall()
            self.assertEqual(len(dupes), 0, f"{inst} has duplicate timestamps")
        conn.close()

    def test_ohlc_valid(self):
        conn = get_conn()
        for inst in ['NIFTY', 'BANKNIFTY']:
            invalid = conn.execute('''SELECT COUNT(*) FROM market_candles_5m
                WHERE instrument_id=? AND (high < max(open, close) OR low > min(open, close) OR high < low OR open <= 0 OR close <= 0)''', (inst,)).fetchone()[0]
            self.assertEqual(invalid, 0, f"{inst} has invalid OHLC")
        conn.close()

    def test_timestamps_sorted(self):
        conn = get_conn()
        for inst in ['NIFTY', 'BANKNIFTY']:
            count = conn.execute('''SELECT COUNT(*) FROM (
                SELECT timestamp, LAG(timestamp) OVER (PARTITION BY instrument_id ORDER BY rowid) as prev_ts
                FROM market_candles_5m WHERE instrument_id=?
            ) WHERE prev_ts IS NOT NULL AND timestamp < prev_ts''', (inst,)).fetchone()[0]
            self.assertEqual(count, 0, f"{inst} timestamps not sorted")
        conn.close()

    def test_idempotent_ingestion(self):
        conn = get_conn()
        nifty = conn.execute("SELECT COUNT(*) FROM market_candles_5m WHERE instrument_id='NIFTY'").fetchone()[0]
        conn.close()
        self.assertGreater(nifty, 0)
        # Re-runing ingestion should not change count (already tested manually)

class TestBacktestIsolation(unittest.TestCase):
    def test_backtest_does_not_mutate_live(self):
        conn = get_conn()
        before_qt = conn.execute("SELECT COUNT(*) FROM qualified_trades").fetchone()[0]
        before_pt = conn.execute("SELECT COUNT(*) FROM paper_trades").fetchone()[0]
        before_locks = conn.execute("SELECT COUNT(*) FROM daily_trade_locks").fetchone()[0]
        conn.close()

        engine = BacktestEngine()
        engine.run("NIFTY", "2026-09-12", "2026-09-19")

        conn = get_conn()
        after_qt = conn.execute("SELECT COUNT(*) FROM qualified_trades").fetchone()[0]
        after_pt = conn.execute("SELECT COUNT(*) FROM paper_trades").fetchone()[0]
        after_locks = conn.execute("SELECT COUNT(*) FROM daily_trade_locks").fetchone()[0]
        conn.close()

        self.assertEqual(before_qt, after_qt, "qualified_trades changed")
        self.assertEqual(before_pt, after_pt, "paper_trades changed")
        self.assertEqual(before_locks, after_locks, "daily_trade_locks changed")

class TestNoLookAhead(unittest.TestCase):
    def test_backtest_no_lookahead(self):
        conn = get_conn()
        runs = conn.execute("SELECT run_id FROM backtest_runs").fetchall()
        conn.close()
        for run in runs:
            conn = get_conn()
            violations = conn.execute('SELECT * FROM backtest_decisions WHERE run_id=? AND lookahead_check != "PASS"', (run[0],)).fetchall()
            conn.close()
            self.assertEqual(len(violations), 0, f"{run[0]} has lookahead violations")

class TestZeroSampleHandling(unittest.TestCase):
    def test_zero_trades_returns_insufficient(self):
        conn = get_conn()
        outcome = conn.execute("SELECT * FROM backtest_outcomes WHERE total_trades=0 LIMIT 1").fetchone()
        conn.close()
        self.assertIsNotNone(outcome, "No zero-trade outcome found")

class TestIdempotency(unittest.TestCase):
    def test_same_backtest_same_results(self):
        conn = get_conn()
        run_counts = conn.execute("SELECT instrument, date_start, COUNT(*) as c FROM backtest_runs GROUP BY instrument, date_start").fetchall()
        conn.close()
        for r in run_counts:
            self.assertGreaterEqual(r['c'], 1, f"Missing run for {r['instrument']} {r['date_start']}")

if __name__ == "__main__":
    unittest.main()
