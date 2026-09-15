#!/usr/bin/env python3
"""Database migration framework.

Principles:
- Never DROP tables
- Never recreate the DB
- Never delete historical data
- Never modify historical AI predictions
- Every schema change is a versioned migration
- Migrations are idempotent or safely tracked
- Migration status is inspectable
- DB is backed up before every migration
"""
import os
import sys
import sqlite3
import json
import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "database", "tradingai.db")
BACKUP_DIR = os.path.join(BASE_DIR, "backups")
MIGRATION_LOG = os.path.join(BASE_DIR, "logs", "migrations.log")


def ensure_dirs():
    os.makedirs(BACKUP_DIR, exist_ok=True)
    os.makedirs(os.path.dirname(MIGRATION_LOG), exist_ok=True)


def log(msg):
    ts = datetime.datetime.utcnow().isoformat() + "Z"
    line = ts + " " + msg
    with open(MIGRATION_LOG, "a") as f:
        f.write(line + "\n")
    print(line)


def get_connection(db_path=None):
    path = db_path or DB_PATH
    conn = sqlite3.connect(path, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


def ensure_migration_table(conn):
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


def get_applied_migrations(conn):
    rows = conn.execute("SELECT version FROM _migrations WHERE status='applied' ORDER BY version").fetchall()
    return {r[0] for r in rows}


def backup_db():
    ensure_dirs()
    timestamp = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    backup_path = os.path.join(BACKUP_DIR, "tradingai_" + timestamp + ".db")
    source = DB_PATH
    conn = sqlite3.connect(source)
    with open(backup_path, "wb") as f:
        for line in conn.iterdump():
            f.write(line.encode("utf-8"))
            f.write(b"\n")
    conn.close()
    log("BACKUP: created " + backup_path)
    if not os.path.exists(backup_path) or os.path.getsize(backup_path) == 0:
        log("BACKUP FAILED: backup file is empty or missing")
        raise RuntimeError("Backup failed")
    verify_backup(backup_path)
    return backup_path


def verify_backup(backup_path):
    with open(backup_path, "r") as f:
        content = f.read()
    has_create_table = "CREATE TABLE" in content
    has_insert = "INSERT INTO" in content
    if not has_create_table:
        log("BACKUP VERIFY FAILED: no CREATE TABLE in backup")
        raise RuntimeError("Backup verification failed")
    log("BACKUP VERIFY: OK (has CREATE TABLE" + (" + INSERT" if has_insert else "") + ")")


def apply_migration(conn, version, description, sql_statements):
    applied = get_applied_migrations(conn)
    if version in applied:
        log("MIGRATION " + version + " already applied, skipping")
        return False
    log("MIGRATION " + version + ": " + description)
    log("MIGRATION " + version + ": backing up DB")
    backup_db()
    for sql in sql_statements:
        conn.execute(sql)
    conn.commit()
    conn.execute(
        "INSERT INTO _migrations (version, description, applied_at, sha256, status) VALUES (?, ?, ?, ?, 'applied')",
        (version, description, datetime.datetime.utcnow().isoformat() + "Z", ""),
    )
    conn.commit()
    log("MIGRATION " + version + ": applied successfully")
    return True


def rollback_last_migration(conn):
    row = conn.execute(
        "SELECT id, version FROM _migrations WHERE status='applied' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if not row:
        log("ROLLBACK: no migrations to rollback")
        return False
    mid, version = row
    log("ROLLBACK: migration " + version)
    conn.execute("UPDATE _migrations SET status='rolled_back', rolled_back_at=? WHERE id=?", (datetime.datetime.utcnow().isoformat() + "Z", mid))
    conn.commit()
    log("ROLLBACK: " + version + " marked rolled_back")
    log("ROLLBACK: restore from backup to fully revert")
    return True


def get_migration_status(conn):
    rows = conn.execute(
        "SELECT version, description, applied_at, status FROM _migrations ORDER BY version"
    ).fetchall()
    return [{"version": r[0], "description": r[1], "applied_at": r[2], "status": r[3]} for r in rows]


ensure_dirs()

if __name__ == "__main__":
    conn = get_connection()
    ensure_migration_table(conn)
    if len(sys.argv) > 1 and sys.argv[1] == "status":
        for row in get_migration_status(conn):
            print(row)
    elif len(sys.argv) > 1 and sys.argv[1] == "version":
        print("migration-framework: 1.0.0")
    else:
        print("Usage: python3 migration.py [status]")
    conn.close()