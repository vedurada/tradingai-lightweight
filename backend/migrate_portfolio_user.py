"""B.2 migration — add user_id column to portfolio table."""

import os
import sys
import sqlite3

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "database", "tradingai.db")


def run_migration():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    try:
        # Check if user_id already exists
        columns = [row[1] for row in conn.execute("PRAGMA table_info(portfolio)").fetchall()]
        if "user_id" in columns:
            print("SKIP: user_id column already exists")
            return

        # Add user_id column (nullable during migration)
        conn.execute("ALTER TABLE portfolio ADD COLUMN user_id INTEGER")

        # Create default user if not exists
        row = conn.execute("SELECT id FROM users WHERE username='default'").fetchone()
        if row:
            default_user_id = row[0]
        else:
            cursor = conn.execute("INSERT INTO users (username, created_at) VALUES ('default', datetime('now'))")
            default_user_id = cursor.lastrowid

        # Assign all existing entries to default user
        conn.execute("UPDATE portfolio SET user_id = ? WHERE user_id IS NULL", (default_user_id,))

        conn.commit()
        print(f"MIGRATION OK: assigned all entries to default user (id={default_user_id})")
    except Exception as e:
        conn.rollback()
        print(f"MIGRATION FAILED: {e}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    run_migration()
