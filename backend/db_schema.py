from __future__ import annotations

import sqlite3
import os
from datetime import datetime, timezone

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "database", "tradingai.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS symbols (
    symbol TEXT PRIMARY KEY,
    name TEXT,
    yfinance_symbol TEXT,
    type TEXT CHECK(type IN ('index', 'stock', 'etf', 'vix')),
    category TEXT,
    active INTEGER DEFAULT 1,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS price_1m (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT,
    timestamp TEXT,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    volume INTEGER,
    UNIQUE(symbol, timestamp)
);
CREATE INDEX IF NOT EXISTS idx_price1m_symbol_ts ON price_1m(symbol, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_price1m_ts ON price_1m(timestamp DESC);

CREATE TABLE IF NOT EXISTS price_5m (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT,
    timestamp TEXT,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    volume INTEGER,
    UNIQUE(symbol, timestamp)
);
CREATE INDEX IF NOT EXISTS idx_price5m_symbol_ts ON price_5m(symbol, timestamp DESC);

CREATE TABLE IF NOT EXISTS price_15m (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT,
    timestamp TEXT,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    volume INTEGER,
    UNIQUE(symbol, timestamp)
);
CREATE INDEX IF NOT EXISTS idx_price15m_symbol_ts ON price_15m(symbol, timestamp DESC);

CREATE TABLE IF NOT EXISTS price_1d (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT,
    timestamp TEXT,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    volume INTEGER,
    adjusted_close REAL,
    UNIQUE(symbol, timestamp)
);
CREATE INDEX IF NOT EXISTS idx_price1d_symbol_ts ON price_1d(symbol, timestamp DESC);

CREATE TABLE IF NOT EXISTS vix_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    change REAL,
    change_pct REAL,
    UNIQUE(timestamp)
);
CREATE INDEX IF NOT EXISTS idx_vix_ts ON vix_data(timestamp DESC);

CREATE TABLE IF NOT EXISTS option_expiries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT,
    expiry TEXT,
    fetched_at TEXT,
    UNIQUE(symbol, expiry)
);

CREATE TABLE IF NOT EXISTS option_chain (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT,
    expiry TEXT,
    strike REAL,
    option_type TEXT,
    last_price REAL,
    bid REAL,
    ask REAL,
    volume INTEGER,
    open_interest INTEGER,
    change_in_oi INTEGER,
    implied_volatility REAL,
    bid_size INTEGER,
    ask_size INTEGER,
    fetched_at TEXT,
    UNIQUE(symbol, expiry, strike, option_type)
);
CREATE INDEX IF NOT EXISTS idx_opt_chain_symbol_expiry ON option_chain(symbol, expiry);
CREATE INDEX IF NOT EXISTS idx_opt_chain_strike ON option_chain(symbol, strike);

CREATE TABLE IF NOT EXISTS market_breadth (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT,
    advances INTEGER,
    declines INTEGER,
    unchanged INTEGER,
    advance_decline_ratio REAL,
    pct_above_ema20 REAL,
    pct_above_ema50 REAL,
    pct_above_ema200 REAL,
    UNIQUE(timestamp)
);
CREATE INDEX IF NOT EXISTS idx_breadth_ts ON market_breadth(timestamp DESC);

CREATE TABLE IF NOT EXISTS sector_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT,
    sector TEXT,
    symbol TEXT,
    change_pct REAL,
    volume INTEGER,
    UNIQUE(timestamp, sector)
);
CREATE INDEX IF NOT EXISTS idx_sector_ts ON sector_data(timestamp DESC);

CREATE TABLE IF NOT EXISTS market_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT,
    nifty REAL,
    banknifty REAL,
    finnifty REAL,
    sensex REAL,
    vix REAL,
    vix_change_pct REAL,
    nifty_regime TEXT,
    banknifty_regime TEXT,
    breadth REAL,
    UNIQUE(timestamp)
);
CREATE INDEX IF NOT EXISTS idx_snap_ts ON market_snapshots(timestamp DESC);

CREATE TABLE IF NOT EXISTS indicators (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT,
    timestamp TEXT,
    ema9 REAL,
    ema20 REAL,
    ema50 REAL,
    ema100 REAL,
    ema200 REAL,
    sma20 REAL,
    sma50 REAL,
    sma200 REAL,
    vwap REAL,
    rsi REAL,
    macd REAL,
    macd_signal REAL,
    macd_histogram REAL,
    atr REAL,
    adx REAL,
    di_plus REAL,
    di_minus REAL,
    bollinger_upper REAL,
    bollinger_middle REAL,
    bollinger_lower REAL,
    bollinger_width REAL,
    pivot REAL,
    r1 REAL, s1 REAL, r2 REAL, s2 REAL, r3 REAL, s3 REAL,
    cpr_classification TEXT,
    day_high REAL,
    day_low REAL,
    prev_day_high REAL,
    prev_day_low REAL,
    prev_day_close REAL,
    open_range_high REAL,
    open_range_low REAL,
    UNIQUE(symbol, timestamp)
);
CREATE INDEX IF NOT EXISTS idx_ind_symbol_ts ON indicators(symbol, timestamp DESC);

CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT,
    timestamp TEXT,
    signal_type TEXT,
    signal_value TEXT,
    confidence REAL,
    UNIQUE(symbol, timestamp, signal_type)
);
CREATE INDEX IF NOT EXISTS idx_sig_symbol_ts ON signals(symbol, timestamp DESC);

CREATE TABLE IF NOT EXISTS market_regime (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT,
    timestamp TEXT,
    regime TEXT,
    confidence REAL,
    trend TEXT,
    momentum TEXT,
    volatility TEXT,
    breadth TEXT,
    vix_regime TEXT,
    evidence TEXT,
    UNIQUE(symbol, timestamp)
);
CREATE INDEX IF NOT EXISTS idx_regime_symbol_ts ON market_regime(symbol, timestamp DESC);

CREATE TABLE IF NOT EXISTS fundamentals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT,
    timestamp TEXT,
    data TEXT,
    UNIQUE(symbol, timestamp)
);
CREATE INDEX IF NOT EXISTS idx_fund_symbol_ts ON fundamentals(symbol, timestamp DESC);

CREATE TABLE IF NOT EXISTS news (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT,
    symbol TEXT,
    headline TEXT,
    publisher TEXT,
    url TEXT,
    UNIQUE(timestamp, symbol, headline)
);
CREATE INDEX IF NOT EXISTS idx_news_ts ON news(timestamp DESC);

CREATE TABLE IF NOT EXISTS corporate_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT,
    timestamp TEXT,
    action_type TEXT,
    value REAL,
    UNIQUE(symbol, timestamp, action_type)
);

CREATE TABLE IF NOT EXISTS data_status (
    symbol TEXT PRIMARY KEY,
    last_fetch TEXT,
    last_1m_fetch TEXT,
    last_5m_fetch TEXT,
    last_15m_fetch TEXT,
    last_options_fetch TEXT,
    last_breadth_fetch TEXT,
    last_vix_fetch TEXT,
    status TEXT,
    error_count INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS etf_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT,
    timestamp TEXT,
    close REAL,
    change_pct REAL,
    volume INTEGER,
    UNIQUE(symbol, timestamp)
);
CREATE INDEX IF NOT EXISTS idx_etf_symbol_ts ON etf_data(symbol, timestamp DESC);
"""

def init_database(db_path: str = DB_PATH) -> None:
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.executescript(SCHEMA)
    _migrate_indicators(conn)
    conn.commit()
    conn.close()
    print(f"Database initialized: {db_path}")

def _migrate_indicators(conn: sqlite3.Connection) -> None:
    c = conn.cursor()
    c.execute("PRAGMA table_info(indicators)")
    cols = {row[1] for row in c.fetchall()}
    additions = {
        "ema9": "REAL", "sma20": "REAL", "sma50": "REAL", "sma200": "REAL",
        "bollinger_width": "REAL", "pivot": "REAL", "r1": "REAL", "s1": "REAL",
        "r2": "REAL", "s2": "REAL", "r3": "REAL", "s3": "REAL",
        "cpr_classification": "TEXT", "day_high": "REAL", "day_low": "REAL",
        "prev_day_high": "REAL", "prev_day_low": "REAL", "prev_day_close": "REAL",
        "open_range_high": "REAL", "open_range_low": "REAL", "di_plus": "REAL",
        "di_minus": "REAL",
    }
    for col_name, col_type in additions.items():
        if col_name not in cols:
            try:
                c.execute(f"ALTER TABLE indicators ADD COLUMN {col_name} {col_type}")
                print(f"  Added column: indicators.{col_name}")
            except Exception as e:
                print(f"  Could not add {col_name}: {e}")
    conn.commit()

if __name__ == "__main__":
    init_database()
