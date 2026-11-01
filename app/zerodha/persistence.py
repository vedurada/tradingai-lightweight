"""Isolated persistence for zerodha_execution.db — transactions, unique constraints."""
import sqlite3, os
from app.zerodha import config

def get_db():
    conn = sqlite3.connect(config.DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_schema():
    conn = get_db()
    conn.execute("CREATE TABLE IF NOT EXISTS zerodha_signals (signal_id TEXT PRIMARY KEY, symbol TEXT, direction TEXT, candle_ts TEXT, status TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS zerodha_paper_trades (trade_id TEXT PRIMARY KEY, signal_id TEXT UNIQUE, symbol TEXT, option_type TEXT, expiry TEXT, strike REAL, entry_price REAL, status TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS zerodha_trade_events (event_id INTEGER PRIMARY KEY AUTOINCREMENT, trade_id TEXT, event_type TEXT, ts TEXT, note TEXT)")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_trade_sig ON zerodha_paper_trades(signal_id)")
    conn.commit()
    conn.close()

def init_shadow_schema():
    conn = get_db()
    conn.execute("CREATE TABLE IF NOT EXISTS zerodha_shadow_signals (signal_id TEXT PRIMARY KEY, symbol TEXT, direction TEXT, candle_start TEXT, candle_end TEXT, pattern TEXT, status TEXT, quote_fresh TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS zerodha_shadow_contracts (select_id TEXT PRIMARY KEY, signal_id TEXT, option_type TEXT, expiry TEXT, strike REAL, symbol TEXT, token TEXT, lot_size INTEGER)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_shadow_sig ON zerodha_shadow_signals(signal_id)")
    conn.commit(); conn.close()
