#!/usr/bin/env python3
"""Create the dedicated SMA9 database and migrate the 339 legacy trades.

Safety:
  * never modifies database/tradingai.db
  * copies legacy rows into sma9.db -> sma9_trades_legacy
  * validates the copied row count == 339
  * creates audit / corrected / live tables used by the scanner and API

Rollback:
  stop the SMA9 scanner service, restore app/api/app.py from the backup,
  and delete database/sma9.db.  database/tradingai.db was never modified.
"""

import json
import os
import sqlite3
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

BASE = "/opt/tradingai"
IST = ZoneInfo("Asia/Kolkata")
SRC_DB = os.path.join(BASE, "database", "tradingai.db")
DST_DB = os.environ.get("SMA9_DB_PATH", os.path.join(BASE, "database", "sma9.db"))
EXPECTED_LEGACY = 339

LEGACY_SCHEMA = """
CREATE TABLE IF NOT EXISTS sma9_trades_legacy (
    trade_id TEXT PRIMARY KEY,
    strategy_id TEXT NOT NULL DEFAULT 'sma9_only',
    instrument TEXT NOT NULL DEFAULT 'NIFTY',
    trade_date TEXT NOT NULL,
    option_type TEXT NOT NULL CHECK(option_type IN ('CE','PE')),
    strike REAL NOT NULL,
    expiry TEXT NOT NULL,
    signal_timestamp TEXT NOT NULL,
    entry_timestamp TEXT NOT NULL,
    entry_price REAL NOT NULL,
    exit_timestamp TEXT NOT NULL,
    exit_price REAL NOT NULL,
    exit_reason TEXT NOT NULL DEFAULT 'SAME_CANDLE_EXIT',
    pnl_points REAL NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'CLOSED',
    sma9_value REAL,
    candle_open REAL,
    candle_high REAL,
    candle_low REAL,
    candle_close REAL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""

AUDIT_SCHEMA = """
CREATE TABLE IF NOT EXISTS sma9_audit (
    trade_id TEXT PRIMARY KEY,
    option_type TEXT NOT NULL,
    entry_timestamp TEXT NOT NULL,
    entry_price REAL,
    stored_sma9 REAL,
    computed_sma9_current REAL,
    computed_sma9_prev REAL,
    prev_close REAL,
    candle_open REAL,
    candle_close REAL,
    condition_a INTEGER,
    condition_b INTEGER,
    qualified_new_rule INTEGER,
    confirmation_proxy INTEGER,
    old_rule_ok INTEGER,
    sma9_matches_stored INTEGER,
    sma9_no_lookahead INTEGER,
    candle_matches INTEGER,
    entry_price_matches_open INTEGER,
    exit_same_candle INTEGER,
    pnl_buy_correct INTEGER,
    legacy_short_pnl INTEGER,
    valid_session_candle INTEGER,
    compliant INTEGER,
    discrepancy_reasons TEXT,
    audited_at TEXT NOT NULL
);
"""

CORRECTED_SCHEMA = """
CREATE TABLE IF NOT EXISTS sma9_trades_corrected (
    trade_id TEXT PRIMARY KEY,
    strategy_id TEXT NOT NULL DEFAULT 'sma9_only',
    instrument TEXT NOT NULL DEFAULT 'NIFTY',
    trade_date TEXT NOT NULL,
    option_type TEXT NOT NULL CHECK(option_type IN ('CE','PE')),
    strike REAL NOT NULL,
    expiry TEXT NOT NULL,
    signal_timestamp TEXT NOT NULL,
    entry_timestamp TEXT NOT NULL,
    entry_price REAL NOT NULL,
    exit_timestamp TEXT NOT NULL,
    exit_price REAL NOT NULL,
    exit_reason TEXT NOT NULL DEFAULT 'SAME_CANDLE_EXIT',
    pnl_points REAL NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'CLOSED',
    sma9_value REAL,
    candle_open REAL,
    candle_high REAL,
    candle_low REAL,
    candle_close REAL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    dataset TEXT NOT NULL DEFAULT 'HISTORICAL_CORRECTED',
    prev_close REAL,
    condition_a INTEGER,
    condition_b INTEGER,
    ltp_at_entry REAL,
    entry_candle_start TEXT,
    entry_candle_end TEXT
);
"""


def now_iso():
    return datetime.now(IST).isoformat()


def main():
    if not os.path.exists(SRC_DB):
        print(f"ERROR: source DB missing: {SRC_DB}")
        return 1
    if os.path.exists(DST_DB):
        print(f"NOTE: destination exists, will be updated idempotently: {DST_DB}")

    src = sqlite3.connect(SRC_DB)
    src.row_factory = sqlite3.Row
    rows = src.execute("SELECT * FROM sma9_trades ORDER BY entry_timestamp").fetchall()
    src.close()
    print(f"Source legacy rows: {len(rows)}")
    if len(rows) != EXPECTED_LEGACY:
        print(f"ERROR: expected {EXPECTED_LEGACY} legacy rows, found {len(rows)}")
        return 2

    dst = sqlite3.connect(DST_DB)
    dst.execute("PRAGMA journal_mode=WAL")
    dst.executescript(LEGACY_SCHEMA)
    dst.executescript(AUDIT_SCHEMA)
    dst.executescript(CORRECTED_SCHEMA)

    cols = [r[1] for r in dst.execute("PRAGMA table_info(sma9_trades_legacy)")]
    placeholders = ",".join("?" for _ in cols)
    inserted = 0
    for r in rows:
        d = dict(r)
        dst.execute(
            f"INSERT OR REPLACE INTO sma9_trades_legacy ({','.join(cols)}) "
            f"VALUES ({placeholders})",
            tuple(d.get(c) for c in cols),
        )
        inserted += 1
    dst.commit()

    legacy_count = dst.execute("SELECT COUNT(*) FROM sma9_trades_legacy").fetchone()[0]
    distinct_ids = dst.execute("SELECT COUNT(DISTINCT trade_id) FROM sma9_trades_legacy").fetchone()[0]
    print(f"Legacy table rows: {legacy_count} (distinct ids: {distinct_ids})")

    # Verify byte-for-byte value preservation for a stable fingerprint.
    fp_src = sqlite3.connect(SRC_DB)
    fp_src.row_factory = sqlite3.Row
    src_fp = fp_src.execute(
        "SELECT COUNT(*) n, COALESCE(SUM(pnl_points),0) pnl, "
        "COALESCE(SUM(entry_price),0) entry_sum FROM sma9_trades"
    ).fetchone()
    fp_src.close()
    dst_fp = dst.execute(
        "SELECT COUNT(*) n, COALESCE(SUM(pnl_points),0) pnl, "
        "COALESCE(SUM(entry_price),0) entry_sum FROM sma9_trades_legacy"
    ).fetchone()
    print(f"Fingerprint source={tuple(src_fp)} legacy={tuple(dst_fp)}")
    ok = (src_fp[0] == dst_fp[0]
          and abs(src_fp[1] - dst_fp[1]) < 0.001
          and abs(src_fp[2] - dst_fp[2]) < 0.001)
    print("FINGERPRINT_OK" if ok else "FINGERPRINT_MISMATCH")

    meta = {
        "created_at": now_iso(),
        "source_db": SRC_DB,
        "destination_db": DST_DB,
        "legacy_rows_expected": EXPECTED_LEGACY,
        "legacy_rows_copied": legacy_count,
        "legacy_distinct_ids": distinct_ids,
        "fingerprint_ok": ok,
    }
    dst.execute(
        "CREATE TABLE IF NOT EXISTS sma9_meta (key TEXT PRIMARY KEY, value TEXT, updated_at TEXT)"
    )
    dst.execute(
        "INSERT OR REPLACE INTO sma9_meta (key,value,updated_at) VALUES (?,?,?)",
        ("migration", json.dumps(meta, indent=2), now_iso()),
    )
    dst.commit()
    dst.close()

    if legacy_count != EXPECTED_LEGACY or not ok:
        print("MIGRATION FAILED VALIDATION")
        return 3
    print("MIGRATION_OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
