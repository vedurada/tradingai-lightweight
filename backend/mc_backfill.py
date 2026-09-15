#!/usr/bin/env python3
import sqlite3, os, sys
DB = "/opt/tradingai/database/tradingai.db"
if not os.path.exists(DB):
    print("DB not found"); sys.exit(1)
conn = sqlite3.connect(DB)
conn.execute("PRAGMA journal_mode=WAL")
conn.execute("""CREATE TABLE IF NOT EXISTS market_candles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL, timeframe TEXT NOT NULL, timestamp TEXT NOT NULL,
    open REAL, high REAL, low REAL, close REAL, volume INTEGER,
    source TEXT DEFAULT 'yfinance', indicator_version TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(symbol, timeframe, timestamp)
)""")
conn.execute("CREATE INDEX IF NOT EXISTS idx_mc_symbol_ts ON market_candles(symbol, timestamp DESC)")
conn.execute("CREATE INDEX IF NOT EXISTS idx_mc_timeframe ON market_candles(timeframe, symbol)")
conn.commit()
total = 0
for table, tf in [("price_1m", "1m"), ("price_5m", "5m"), ("price_1d", "1d")]:
    try:
        rows = conn.execute(f"SELECT symbol, timestamp, open, high, low, close, volume FROM {table}").fetchall()
        for r in rows:
            try:
                conn.execute("INSERT OR IGNORE INTO market_candles (symbol, timeframe, timestamp, open, high, low, close, volume, source, indicator_version) VALUES (?,?,?,?,?,?,?,?,?,?)", (r[0], tf, r[1], r[2], r[3], r[4], r[5], r[6], "yfinance", ""))
                total += 1
            except: continue
        print(f"{table}: {len(rows)} rows")
    except Exception as e:
        print(f"{table} skip: {e}")
conn.commit()
count = conn.execute("SELECT COUNT(*) FROM market_candles").fetchone()[0]
print(f"market_candles total: {count}")
conn.close()
print("Done")