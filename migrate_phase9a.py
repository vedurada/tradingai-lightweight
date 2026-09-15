#!/usr/bin/env python3
"""Phase 9A — Database migration for Trade Journal tables."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.migration import get_connection, ensure_migration_table, apply_migration

VERSION = "9A.1"
DESCRIPTION = "Trade Journal: trade_journal, trade_journal_events, user_feedback tables"


def main():
    conn = get_connection()
    try:
        ensure_migration_table(conn)
        applied = apply_migration(
            conn,
            VERSION,
            DESCRIPTION,
            [
                """CREATE TABLE IF NOT EXISTS trade_journal (
                    journal_id TEXT PRIMARY KEY,
                    tradingai_setup_id TEXT,
                    date TEXT NOT NULL,
                    instrument TEXT NOT NULL,
                    strategy TEXT,
                    direction TEXT,
                    planned_entry REAL,
                    actual_entry REAL,
                    stop REAL,
                    target REAL,
                    actual_exit REAL,
                    quantity INTEGER,
                    risk_planned REAL,
                    risk_actual REAL,
                    market_regime TEXT,
                    tradingai_evidence_score REAL,
                    tradingai_confidence REAL,
                    user_action TEXT NOT NULL DEFAULT 'PENDING',
                    user_reason TEXT,
                    result TEXT,
                    mistake TEXT,
                    notes TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )""",
                """CREATE INDEX IF NOT EXISTS idx_journal_date ON trade_journal(date)""",
                """CREATE INDEX IF NOT EXISTS idx_journal_instrument ON trade_journal(instrument)""",
                """CREATE INDEX IF NOT EXISTS idx_journal_setup_id ON trade_journal(tradingai_setup_id)""",
                """CREATE INDEX IF NOT EXISTS idx_journal_action ON trade_journal(user_action)""",
                """CREATE TABLE IF NOT EXISTS trade_journal_events (
                    event_id TEXT PRIMARY KEY,
                    journal_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    field_name TEXT,
                    old_value TEXT,
                    new_value TEXT,
                    created_at TEXT NOT NULL
                )""",
                """CREATE INDEX IF NOT EXISTS idx_journal_events_journal ON trade_journal_events(journal_id)""",
                """CREATE TABLE IF NOT EXISTS user_feedback (
                    feedback_id TEXT PRIMARY KEY,
                    journal_id TEXT NOT NULL,
                    rating INTEGER CHECK(rating >= 1 AND rating <= 5),
                    category TEXT,
                    comment TEXT,
                    created_at TEXT NOT NULL
                )""",
                """CREATE INDEX IF NOT EXISTS idx_feedback_journal ON user_feedback(journal_id)""",
            ],
        )
        conn.close()
        if applied:
            print(f"Migration {VERSION} applied successfully")
        else:
            print(f"Migration {VERSION} already applied, skipping")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
