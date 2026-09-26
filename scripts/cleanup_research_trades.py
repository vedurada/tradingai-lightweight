#!/usr/bin/env python3
import sys, os, json, sqlite3
sys.path.insert(0, '/opt/tradingai_new')
from datetime import datetime
from zoneinfo import ZoneInfo
from app.core.db import get_conn

_IST = ZoneInfo('Asia/Kolkata')

conn = get_conn()
qt = conn.execute("SELECT COUNT(*) FROM qualified_trades").fetchone()[0]
pt = conn.execute("SELECT COUNT(*) FROM paper_trades").fetchone()[0]
locks = conn.execute("SELECT COUNT(*) FROM daily_trade_locks").fetchone()[0]
bt_runs = conn.execute("SELECT COUNT(*) FROM backtest_runs").fetchone()[0]

print(f"Before cleanup: qualified_trades={qt}, paper_trades={pt}, locks={locks}, bt_runs={bt_runs}")

# Remove trades created by backtest testing (no daily lock consumed = from research)
conn.execute("DELETE FROM qualified_trades WHERE daily_lock_consumed = 0")
conn.execute("DELETE FROM daily_trade_locks WHERE status = 'CONSUMED' AND trade_id NOT IN (SELECT trade_id FROM qualified_trades WHERE daily_lock_consumed = 1)")
conn.commit()

qt2 = conn.execute("SELECT COUNT(*) FROM qualified_trades").fetchone()[0]
pt2 = conn.execute("SELECT COUNT(*) FROM paper_trades").fetchone()[0]
locks2 = conn.execute("SELECT COUNT(*) FROM daily_trade_locks").fetchone()[0]
conn.close()

print(f"After cleanup: qualified_trades={qt2}, paper_trades={pt2}, locks={locks2}")
