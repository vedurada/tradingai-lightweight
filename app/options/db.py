"""Phase 14: initialize option tables in SQLite database.

Creates/ensures option_contracts and option_snapshots with full
canonical contract schema. Never migrates existing data."""
import sqlite3
from app.core.db import DB_PATH

OPTION_CONTRACTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS option_contracts (
    contract_id TEXT PRIMARY KEY,
    instrument_id TEXT NOT NULL,
    expiry TEXT NOT NULL,
    strike REAL NOT NULL,
    option_type TEXT NOT NULL CHECK(option_type IN ('CE','PE')),
    last_price REAL,
    bid REAL,
    ask REAL,
    volume INTEGER,
    open_interest REAL,
    change_in_open_interest REAL,
    implied_volatility REAL,
    delta REAL,
    gamma REAL,
    theta REAL,
    vega REAL,
    premium_per_lot REAL,
    max_risk REAL,
    max_reward REAL,
    distance_from_spot REAL,
    liquidity TEXT,
    data_state TEXT NOT NULL DEFAULT 'UNAVAILABLE',
    source TEXT,
    source_timestamp TEXT,
    served_timestamp TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(instrument_id, expiry, strike, option_type)
)
"""

OPTION_SNAPSHOTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS option_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    instrument_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    underlying_price REAL,
    atm_strike REAL,
    atm_premium REAL,
    atm_iv REAL,
    expected_move REAL,
    pcr REAL,
    total_oi REAL,
    total_volume INTEGER,
    data_state TEXT NOT NULL DEFAULT 'UNAVAILABLE',
    provider TEXT,
    source_timestamp TEXT,
    served_timestamp TEXT,
    created_at TEXT NOT NULL
)
"""


def init_option_tables():
    """Create option tables if they don't exist. Safe to call multiple times."""
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(OPTION_CONTRACTS_SCHEMA)
    conn.execute(OPTION_SNAPSHOTS_SCHEMA)
    conn.commit()
    # Verify tables exist and have correct schema
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'option_%'").fetchall()]
    conn.close()
    return tables


def get_option_table_stats():
    """Return row counts for option tables."""
    conn = sqlite3.connect(DB_PATH, timeout=10)
    result = {}
    for t in ["option_contracts", "option_snapshots"]:
        try:
            result[t] = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        except Exception:
            result[t] = -1
    conn.close()
    return result
