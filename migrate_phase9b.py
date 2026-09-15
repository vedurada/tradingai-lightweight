#!/usr/bin/env python3
"""Phase 9B — Migration for expanded comparison engine."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.migration import get_connection, ensure_migration_table, apply_migration

VERSION = "9B.1"
DESCRIPTION = "Expanded comparison: lifecycle, timestamps, readiness, outcome fields"


def main():
    conn = get_connection()
    try:
        ensure_migration_table(conn)
        applied = apply_migration(
            conn, VERSION, DESCRIPTION,
            [
                "ALTER TABLE trade_journal ADD COLUMN tradingai_trade_readiness TEXT",
                "ALTER TABLE trade_journal ADD COLUMN entry_window_start TEXT",
                "ALTER TABLE trade_journal ADD COLUMN entry_window_end TEXT",
                "ALTER TABLE trade_journal ADD COLUMN confirmation_at TEXT",
                "ALTER TABLE trade_journal ADD COLUMN invalidation_at TEXT",
                "ALTER TABLE trade_journal ADD COLUMN actual_entry_at TEXT",
                "ALTER TABLE trade_journal ADD COLUMN actual_exit_at TEXT",
                "ALTER TABLE trade_journal ADD COLUMN tradingai_predicted_outcome TEXT",
            ],
        )
        conn.close()
        if applied:
            print("Migration 9B.1 applied successfully")
        else:
            print("Migration 9B.1 already applied, skipping")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
