#!/usr/bin/env python3
import sys
sys.path.insert(0, '/opt/tradingai_new')
from app.research.backtest import BacktestEngine

tests = [
    ('NIFTY', '2026-09-12', '2026-09-19'),
    ('NIFTY', '2026-08-21', '2026-09-19'),
    ('NIFTY', '2026-06-21', '2026-09-19'),
    ('BANKNIFTY', '2026-09-12', '2026-09-19'),
    ('BANKNIFTY', '2026-08-21', '2026-09-19'),
    ('BANKNIFTY', '2026-06-21', '2026-09-19'),
]

for inst, start, end in tests:
    engine = BacktestEngine()
    result = engine.run(inst, start, end)
    outcome = result['outcome']
    print(f"{inst} {start} to {end}: trades={outcome['total_trades']}, wins={outcome['wins']}, losses={outcome['losses']}")
    print(f"  Run ID: {result['run_id']}, Lookahead: {result['lookahead_check']}")

import sqlite3
conn = sqlite3.connect('/opt/tradingai_new/database/tradingai.db')
live_qt = conn.execute("SELECT COUNT(*) FROM qualified_trades").fetchone()[0]
live_pt = conn.execute("SELECT COUNT(*) FROM paper_trades").fetchone()[0]
live_locks = conn.execute("SELECT COUNT(*) FROM daily_trade_locks").fetchone()[0]
conn.close()
isolation = "PASS" if live_qt == 0 and live_pt == 0 and live_locks == 0 else "FAIL"
print(f"\nBacktest/Live Isolation: {isolation}")
