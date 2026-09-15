#!/usr/bin/env python3
"""Phase 2 Migration: market_candles table.

Normalizes candles from price_1m/price_5m/price_15m/price_1d into a single
versioned, queryable candle store.

Principles:
- NEVER DROP tables or delete historical data
- Every schema change is versioned
- Migrations are idempotent
- DB is backed up before migration
"""
import os, sys, sqlite3, datetime, json

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "database", "tradingai.db")
BACKUP_DIR = os.path.join(BASE_DIR, "backups")
MIGRATION_LOG = os.path.join(BASE_DIR, "logs", "migrations.log")
MIGRATION_VERSION = "2.0.0-market_candles"


def ensure_dirs():
    os.makedirs(BACKUP_DIR, exist_ok=True)
    os.makedirs(os.path.dirname(MIGRATION_LOG), exist_ok=True)


def log(msg):
    ts = datetime.datetime.utcnow().isoformat() + "Z"
    line = ts + " " + msg
    with open(MIGRATION_LOG, "a") as f:
        f.write(line + "\n")
    print(line)


def get_connection():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


def backup_db():
    ensure_dirs()
    timestamp = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    backup_path = os.path.join(BACKUP_DIR, "tradingai_" + timestamp + ".db")
    conn = get_connection()
    with open(backup_path, "wb") as f:
        for line in conn.iterdump():
            f.write(line.encode("utf-8"))
            f.write(b"\n")
    conn.close()
    log("BACKUP: " + backup_path)
    if not os.path.exists(backup_path) or os.path.getsize(backup_path) == 0:
        raise RuntimeError("Backup failed")


def apply_migration(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS _migrations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            version TEXT UNIQUE NOT NULL,
            description TEXT NOT NULL,
            applied_at TEXT NOT NULL,
            sha256 TEXT,
            status TEXT DEFAULT 'applied',
            rolled_back_at TEXT
        )
    """)
    conn.commit()

    applied = set()
    rows = conn.execute("SELECT version FROM _migrations WHERE status='applied'").fetchall()
    for r in rows:
        applied.add(r[0])

    if MIGRATION_VERSION in applied:
        log("MIGRATION " + MIGRATION_VERSION + " already applied, skipping")
        return False

    log("MIGRATION " + MIGRATION_VERSION + ": creating market_candles table")
    backup_db()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS market_candles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume INTEGER,
            source TEXT DEFAULT 'yfinance',
            indicator_version TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now')),
            UNIQUE(symbol, timeframe, timestamp)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_mc_symbol_ts ON market_candles(symbol, timestamp DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_mc_timeframe ON market_candles(timeframe, symbol)")

    now = datetime.datetime.utcnow().isoformat() + "Z"
    conn.execute(
        "INSERT INTO _migrations (version, description, applied_at, sha256, status) VALUES (?, ?, ?, ?, 'applied')",
        (MIGRATION_VERSION, "market_candles normalized candle table", now, ""),
    )
    conn.commit()
    log("MIGRATION " + MIGRATION_VERSION + " applied successfully")
    return True


def backfill_candles(conn):
    """Backfill market_candles from existing price tables."""
    timeframes = [
        ("price_1m", "1m"),
        ("price_5m", "5m"),
        ("price_15m", "15m"),
        ("price_1d", "1d"),
    ]
    total = 0
    for table, tf in timeframes:
        try:
            rows = conn.execute(f"SELECT symbol, timestamp, open, high, low, close, volume FROM {table}").fetchall()
            for r in rows:
                try:
                    conn.execute(
                        "INSERT OR IGNORE INTO market_candles (symbol, timeframe, timestamp, open, high, low, close, volume, source, indicator_version) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (r[0], tf, r[1], r[2], r[3], r[4], r[5], r[6], "yfinance", ""),
                    )
                    total += 1
                except Exception:
                    continue
            log("BACKFILL: " + table + " (" + str(len(rows)) + " rows) -> market_candles")
        except Exception as e:
            log("BACKFILL SKIP " + table + ": " + str(e))
    conn.commit()
    log("BACKFILL TOTAL: " + str(total) + " candles")
    return total


if __name__ == "__main__":
    ensure_dirs()
    conn = get_connection()
    try:
        applied = apply_migration(conn)
        if applied:
            count = backfill_candles(conn)
            log("Migration " + MIGRATION_VERSION + " complete: " + str(count) + " candles backfilled")
        else:
            log("Migration " + MIGRATION_VERSION + " already applied, checking count...")
            count = conn.execute("SELECT COUNT(*) FROM market_candles").fetchone()[0]
            log("market_candles has " + str(count) + " rows")
    finally:
        conn.close()
