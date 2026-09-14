"""Authentication module — API key generation, validation, and user lookup."""

import os
import sys
import sqlite3
import secrets
import hashlib
import hmac
import logging
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logger = logging.getLogger("tradingai")
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "database", "tradingai.db")


def _get_db():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_schema():
    conn = _get_db()
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL)")
        conn.execute("CREATE TABLE IF NOT EXISTS api_keys (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, key_hash TEXT NOT NULL UNIQUE, key_salt TEXT NOT NULL, key_prefix TEXT NOT NULL, label TEXT DEFAULT 'default', is_active INTEGER DEFAULT 1, created_at TEXT NOT NULL, last_used_at TEXT, revoked_at TEXT, FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE)")
        conn.commit()
    finally:
        conn.close()


def generate_api_key():
    raw_key = secrets.token_urlsafe(32)
    salt = secrets.token_hex(16)
    key_hash = hashlib.sha256((raw_key + salt).encode()).hexdigest()
    key_prefix = key_hash[:8]
    return raw_key, key_hash, salt, key_prefix


def store_api_key(user_id, raw_key, label="default"):
    raw_key, key_hash, salt, key_prefix = generate_api_key()
    conn = _get_db()
    try:
        conn.execute("INSERT INTO api_keys (user_id, key_hash, key_salt, key_prefix, label, created_at) VALUES (?,?,?,?,?,?)", (user_id, key_hash, salt, key_prefix, label, datetime.now(timezone.utc).isoformat()))
        conn.commit()
    finally:
        conn.close()
    return raw_key


def verify_api_key(api_key):
    if not api_key or len(api_key) < 10:
        return None
    try:
        conn = _get_db()
        keys = conn.execute("SELECT id, user_id, key_hash, key_salt, key_prefix, is_active, revoked_at FROM api_keys WHERE is_active = 1").fetchall()
        for k in keys:
            candidate_hash = hashlib.sha256((api_key + k["key_salt"]).encode()).hexdigest()
            if hmac.compare_digest(candidate_hash, k["key_hash"]):
                if k["revoked_at"] is not None:
                    continue
                conn.execute("UPDATE api_keys SET last_used_at = ? WHERE id = ?", (datetime.now(timezone.utc).isoformat(), k["id"]))
                conn.commit()
                conn.close()
                return {"user_id": k["user_id"], "key_id": k["id"], "key_prefix": k["key_prefix"]}
        conn.close()
    except Exception:
        logger.error("API key verification failed", exc_info=True)
    return None


def get_user_id_for_key(api_key):
    result = verify_api_key(api_key)
    if result is None:
        return None
    return result["user_id"]


def revoke_api_key_by_id(key_id):
    conn = _get_db()
    try:
        conn.execute("UPDATE api_keys SET revoked_at = ?, is_active = 0 WHERE id = ?", (datetime.now(timezone.utc).isoformat(), key_id))
        conn.commit()
    finally:
        conn.close()
