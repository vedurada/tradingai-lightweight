#!/usr/bin/env python3
import json, sqlite3, sys, os
sys.path.insert(0, '/opt/tradingai_new')
from datetime import datetime
from zoneinfo import ZoneInfo
from app.research.backtest import BacktestEngine

_IST = ZoneInfo('Asia/Kolkata')

print("=== BACKTEST RUNS ===")
for inst, start, end in [
    ('NIFTY', '2026-09-12', '2026-09-19'),
    ('NIFTY', '2026-08-21', '2026-09-19'),
    ('NIFTY', '2026-06-21', '2026-09-19'),
    ('BANKNIFTY', '2026-09-12', '2026-09-19'),
    ('BANKNIFTY', '2026-08-21', '2026-09-19'),
]:
    print(f"\n{inst} {start} to {end}")
    try:
        engine = BacktestEngine()
        result = engine.run(inst, start, end)
        outcome = result['outcome']
        print(f"  Run ID: {result['run_id']}")
        print(f"  Decisions: {len(result['decisions'])}")
        print(f"  Trades: {len(result['trades'])}")
        print(f"  Outcome: {json.dumps(outcome, default=str)}")
        print(f"  Lookahead: {result['lookahead_check']}")
    except Exception as e:
        print(f"  ERROR: {e}")

print("\n=== DB VALIDATION ===")
conn = sqlite3.connect('/opt/tradingai_new/database/tradingai.db')
conn.row_factory = sqlite3.Row
bt_count = conn.execute('SELECT COUNT(*) FROM backtest_runs').fetchone()[0]
bt_dec = conn.execute('SELECT COUNT(*) FROM backtest_decisions').fetchone()[0]
bt_trd = conn.execute('SELECT COUNT(*) FROM backtest_trades').fetchone()[0]
candle_nifty = conn.execute("SELECT COUNT(*) FROM market_candles_5m WHERE instrument_id='NIFTY'").fetchone()[0]
candle_bank = conn.execute("SELECT COUNT(*) FROM market_candles_5m WHERE instrument_id='BANKNIFTY'").fetchone()[0]
live_qt = conn.execute("SELECT COUNT(*) FROM qualified_trades").fetchone()[0]
live_pt = conn.execute("SELECT COUNT(*) FROM paper_trades").fetchone()[0]
live_locks = conn.execute("SELECT COUNT(*) FROM daily_trade_locks").fetchone()[0]
conn.close()

print(f"Backtest runs: {bt_count}")
print(f"Backtest decisions: {bt_dec}")
print(f"Backtest trades: {bt_trd}")
print(f"NIFTY candles: {candle_nifty}")
print(f"BANKNIFTY candles: {candle_bank}")
print(f"Live qualified_trades: {live_qt}")
print(f"Live paper_trades: {live_pt}")
print(f"Live daily_trade_locks: {live_locks}")

isolation = "PASS" if live_qt == 0 and live_pt == 0 and live_locks == 0 else "FAIL"
print(f"Backtest/Live Isolation: {isolation}")
