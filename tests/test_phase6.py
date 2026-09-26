import sys, os, json, sqlite3, unittest, uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

sys.path.insert(0, '/opt/tradingai')
sys.path.insert(0, '/opt/tradingai/scripts')

from app.core.db import get_conn
from app.live.engine import completed_candle_ts, floor_5m
from app.paper_trade.engine import PaperTradeEngine
from app.paper_trade.performance import record_performance, get_performance

_IST = ZoneInfo('Asia/Kolkata')


class TestPointInTimeCandles(unittest.TestCase):
    """Section 5: Point-in-time data integrity."""

    def test_candles_exist(self):
        conn = get_conn()
        nifty = conn.execute("SELECT COUNT(*) FROM market_candles_5m WHERE instrument_id='NIFTY'").fetchone()[0]
        bank = conn.execute("SELECT COUNT(*) FROM market_candles_5m WHERE instrument_id='BANKNIFTY'").fetchone()[0]
        vix = conn.execute("SELECT COUNT(*) FROM market_candles_5m WHERE instrument_id='INDIA_VIX'").fetchone()[0]
        conn.close()
        self.assertGreater(nifty, 0, "No NIFTY candles")
        self.assertGreater(bank, 0, "No BANKNIFTY candles")
        self.assertGreater(vix, 0, "No INDIA_VIX candles")

    def test_no_future_candles(self):
        conn = get_conn()
        now = datetime.now(_IST)
        future = conn.execute("SELECT COUNT(*) FROM market_candles_5m WHERE timestamp > ?", (now.isoformat(),)).fetchone()[0]
        conn.close()
        self.assertEqual(future, 0, "Future candles found")

    def test_candle_uniqueness(self):
        conn = get_conn()
        dupes = conn.execute("SELECT COUNT(*) FROM (SELECT instrument_id, timestamp, COUNT(*) c FROM market_candles_5m GROUP BY instrument_id, timestamp HAVING c > 1)").fetchone()[0]
        conn.close()
        self.assertEqual(dupes, 0, "Duplicate candles found")

    def test_completed_candle_cutoff(self):
        now = datetime.now(_IST)
        cutoff = completed_candle_ts(now)
        if cutoff is None:
            self.skipTest("No completed candle yet")
        conn = get_conn()
        rows = conn.execute("SELECT DISTINCT timestamp FROM market_candles_5m WHERE instrument_id='NIFTY' AND timestamp > ?", (cutoff.isoformat(),)).fetchall()
        conn.close()
        self.assertEqual(len(rows), 0, "Candles after cutoff found")


class TestCollector(unittest.TestCase):
    """Section 4: Market-data collector."""

    def test_collector_exists(self):
        from app.market.collector import SYMBOL_MAP, get_completed_cutoff
        self.assertIn('NIFTY', SYMBOL_MAP)
        self.assertIn('BANKNIFTY', SYMBOL_MAP)
        self.assertIn('INDIA_VIX', SYMBOL_MAP)

    def test_cutoff_logic(self):
        # At 09:18 - candle 09:15 still forming, no completed candles
        now = datetime(2026, 9, 23, 9, 18, 0, tzinfo=_IST)
        result = completed_candle_ts(now)
        self.assertIsNone(result, 'No completed candles at 09:18')

        # At 09:21 - candle 09:15 completed
        now = datetime(2026, 9, 23, 9, 21, 0, tzinfo=_IST)
        result = completed_candle_ts(now)
        self.assertEqual(result.hour, 9)
        self.assertEqual(result.minute, 15)

        # At 09:26 - candle 09:20 completed (09:25 still forming)
        now = datetime(2026, 9, 23, 9, 26, 0, tzinfo=_IST)
        result = completed_candle_ts(now)
        self.assertEqual(result.hour, 9)
        self.assertEqual(result.minute, 20)

        # At 09:31 - candle 09:25 completed
        now = datetime(2026, 9, 23, 9, 31, 0, tzinfo=_IST)
        result = completed_candle_ts(now)
        self.assertEqual(result.hour, 9)
        self.assertEqual(result.minute, 25)

        # Before market open - no completed candles
        now = datetime(2026, 9, 23, 9, 10, 0, tzinfo=_IST)
        result = completed_candle_ts(now)
        self.assertIsNone(result)


class TestPaperTradeLifecycle(unittest.TestCase):
    """Section 11: Paper trade lifecycle."""

    def setUp(self):
        self.engine = PaperTradeEngine()

    def test_create_paper_trade(self):
        qt = {
            'instrument_id': 'NIFTY',
            'scenario': 'BREAKOUT',
            'strategy': 'Bull Put Spread',
            'objective': 'Directional',
            'direction': 'BEARISH',
            'entry': 23400.0,
            'stop': 23166.0,
            'target': 23868.0,
            'max_risk': 1.0,
            'expected_reward': 2.0,
        }
        trade_id = self.engine.create_paper_trade(qt)
        self.assertTrue(trade_id.startswith('PT-'))
        conn = get_conn()
        row = conn.execute("SELECT * FROM paper_trades WHERE trade_id=?", (trade_id,)).fetchone()
        conn.close()
        self.assertIsNotNone(row, 'Trade not in DB')
        self.assertEqual(row['status'], 'ACTIVE')

    def test_monitor(self):
        trades = self.engine.monitor('NIFTY')
        self.assertIsInstance(trades, list)

    def test_duplicate_monitor_no_dup_records(self):
        conn = get_conn()
        closed = conn.execute("SELECT trade_id FROM paper_trades WHERE status='CLOSED' LIMIT 1").fetchall()
        conn.close()
        if not closed:
            self.skipTest('No closed trades')
        tid = closed[0]['trade_id']
        id1 = record_performance(tid)
        id2 = record_performance(tid)
        self.assertEqual(id1, id2, 'Duplicate performance record')


class TestResearchLiveIsolation(unittest.TestCase):
    """Section 19: Research/Live isolation."""

    def test_live_does_not_modify_research(self):
        conn = get_conn()
        bt_before = conn.execute("SELECT COUNT(*) FROM backtest_trades").fetchone()[0]
        bo_before = conn.execute("SELECT COUNT(*) FROM backtest_outcomes").fetchone()[0]
        rd_before = conn.execute("SELECT COUNT(*) FROM research_daily_decisions").fetchone()[0]
        conn.close()

        engine = PaperTradeEngine()
        qt = {
            'instrument_id': 'NIFTY', 'scenario': 'BREAKOUT', 'strategy': 'Bull Put Spread',
            'objective': 'Directional', 'direction': 'BEARISH',
            'entry': 23400.0, 'stop': 23166.0, 'target': 23868.0,
            'max_risk': 1.0, 'expected_reward': 2.0,
        }
        trade_id = engine.create_paper_trade(qt)

        conn = get_conn()
        bt_after = conn.execute("SELECT COUNT(*) FROM backtest_trades").fetchone()[0]
        bo_after = conn.execute("SELECT COUNT(*) FROM backtest_outcomes").fetchone()[0]
        rd_after = conn.execute("SELECT COUNT(*) FROM research_daily_decisions").fetchone()[0]
        conn.close()
        self.assertEqual(bt_before, bt_after)
        self.assertEqual(bo_before, bo_after)
        self.assertEqual(rd_before, rd_after)

        conn = get_conn()
        conn.execute("DELETE FROM paper_trades WHERE trade_id=?", (trade_id,))
        conn.commit()
        conn.close()

    def test_backtest_no_live_trades(self):
        conn = get_conn()
        pt_b = conn.execute("SELECT COUNT(*) FROM paper_trades").fetchone()[0]
        qt_b = conn.execute("SELECT COUNT(*) FROM qualified_trades").fetchone()[0]
        dl_b = conn.execute("SELECT COUNT(*) FROM daily_trade_locks").fetchone()[0]
        pf_b = conn.execute("SELECT COUNT(*) FROM live_trade_performance").fetchone()[0]
        conn.close()

        from app.research.backtest import BacktestEngine
        engine = BacktestEngine()
        engine.run('NIFTY', '2026-09-01', '2026-09-19')

        conn = get_conn()
        pt_a = conn.execute("SELECT COUNT(*) FROM paper_trades").fetchone()[0]
        qt_a = conn.execute("SELECT COUNT(*) FROM qualified_trades").fetchone()[0]
        dl_a = conn.execute("SELECT COUNT(*) FROM daily_trade_locks").fetchone()[0]
        pf_a = conn.execute("SELECT COUNT(*) FROM live_trade_performance").fetchone()[0]
        conn.close()
        self.assertEqual(pt_b, pt_a)
        self.assertEqual(qt_b, qt_a)
        self.assertEqual(dl_b, dl_a)
        self.assertEqual(pf_b, pf_a)


class TestOneTradePerDay(unittest.TestCase):
    """Section 12: One-trade-per-day invariant."""

    def test_daily_lock_constraint(self):
        conn = get_conn()
        idxs = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='qualified_trades'").fetchall()]
        conn.close()
        has_daily = any('daily' in i.lower() or 'trade_lock' in i.lower() for i in idxs)
        self.assertTrue(has_daily, f'Daily lock index not found: {idxs}')


class TestAPISmoke(unittest.TestCase):
    """Section 14: Live performance API."""

    def test_health(self):
        import requests
        r = requests.get('https://tradingai.in/api/health', timeout=10)
        self.assertEqual(r.status_code, 200)

    def test_performance_endpoint(self):
        import requests
        r = requests.get('https://tradingai.in/api/performance/live/NIFTY', timeout=10)
        self.assertIn(r.status_code, [200, 404])
        if r.status_code == 200:
            data = r.json()
            self.assertIn('data', data)
            self.assertIn('total_trades', data['data'])

    def test_candles_completed_only(self):
        import requests
        r = requests.get('https://tradingai.in/api/NIFTY/candles', timeout=10)
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn('data', data)
        self.assertIn('candles', data['data'])
        self.assertIn('forming_excluded', data['data'])

    def test_get_never_creates_trade(self):
        import requests
        conn = get_conn()
        before = conn.execute("SELECT COUNT(*) FROM qualified_trades").fetchone()[0]
        conn.close()
        import requests as req
        req.get('https://tradingai.in/api/NIFTY/decision', timeout=10)
        conn = get_conn()
        after = conn.execute("SELECT COUNT(*) FROM qualified_trades").fetchone()[0]
        conn.close()
        self.assertEqual(before, after, 'GET created a trade')


if __name__ == '__main__':
    unittest.main(verbosity=2)
