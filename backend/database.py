from __future__ import annotations

import sqlite3
import os
import json
from datetime import datetime, timezone
from typing import Any, Optional


class Database:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_tables()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_tables(self) -> None:
        conn = self._conn()
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS instruments (
                symbol TEXT PRIMARY KEY,
                name TEXT,
                yfinance_symbol TEXT,
                type TEXT CHECK(type IN ('index', 'stock')),
                page TEXT,
                active INTEGER DEFAULT 1,
                created_at TEXT
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS prices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT,
                timestamp TEXT,
                open REAL,
                high REAL,
                low REAL,
                close REAL,
                volume INTEGER,
                previous_close REAL,
                UNIQUE(symbol, timestamp)
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS indicators (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT,
                timestamp TEXT,
                ema20 REAL,
                ema50 REAL,
                ema100 REAL,
                ema200 REAL,
                rsi REAL,
                macd REAL,
                macd_signal REAL,
                macd_histogram REAL,
                atr REAL,
                adx REAL,
                vwap REAL,
                bb_upper REAL,
                bb_middle REAL,
                bb_lower REAL,
                pivot REAL,
                r1 REAL, s1 REAL, r2 REAL, s2 REAL, r3 REAL, s3 REAL,
                bc REAL, tc REAL, cpr_width REAL, cpr_classification TEXT,
                support_levels TEXT,
                resistance_levels TEXT,
                UNIQUE(symbol, timestamp)
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS market_structure (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT,
                timestamp TEXT,
                prev_high REAL,
                prev_low REAL,
                prev_close REAL,
                pivot REAL,
                r1 REAL, s1 REAL, r2 REAL, s2 REAL, r3 REAL, s3 REAL,
                bc REAL, tc REAL,
                cpr_type TEXT,
                cpr_width REAL,
                support TEXT,
                resistance TEXT,
                UNIQUE(symbol, timestamp)
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS volatility (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT,
                timestamp TEXT,
                vix_price REAL,
                atr REAL,
                atr_pct REAL,
                historical_volatility REAL,
                intraday_range REAL,
                opening_range REAL,
                expected_move REAL,
                UNIQUE(symbol, timestamp)
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS options (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT,
                expiry TEXT,
                timestamp TEXT,
                atm_strike REAL,
                call_ltp REAL,
                put_ltp REAL,
                call_volume INTEGER,
                put_volume INTEGER,
                call_oi INTEGER,
                put_oi INTEGER,
                call_oi_change INTEGER,
                put_oi_change INTEGER,
                call_iv REAL,
                put_iv REAL,
                pcr REAL,
                max_pain REAL,
                data_quality TEXT,
                UNIQUE(symbol, expiry, timestamp)
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS regimes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT,
                timestamp TEXT,
                regime TEXT,
                confidence REAL,
                evidence TEXT,
                trend TEXT,
                momentum TEXT,
                volatility TEXT,
                UNIQUE(symbol, timestamp)
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS scenarios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT,
                timestamp TEXT,
                bullish_trigger TEXT,
                bullish_confirmation TEXT,
                bullish_target TEXT,
                bullish_invalidation TEXT,
                bearish_trigger TEXT,
                bearish_confirmation TEXT,
                bearish_target TEXT,
                bearish_invalidation TEXT,
                range_condition TEXT,
                range_strategy TEXT,
                range_invalidation TEXT,
                UNIQUE(symbol, timestamp)
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS strategies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT,
                timestamp TEXT,
                strategy TEXT,
                market_condition TEXT,
                expiry TEXT,
                legs TEXT,
                entry_trigger TEXT,
                maximum_profit TEXT,
                maximum_loss TEXT,
                breakeven TEXT,
                stop_loss TEXT,
                target TEXT,
                adjustment TEXT,
                exit TEXT,
                time_based_exit TEXT,
                UNIQUE(symbol, timestamp)
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS ai_outlooks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT,
                timestamp TEXT,
                outlook TEXT,
                data_quality TEXT,
                UNIQUE(symbol, timestamp)
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT,
                timestamp TEXT,
                alert_type TEXT,
                message TEXT,
                read INTEGER DEFAULT 0
            )
        """)
        conn.commit()
        conn.close()

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        conn = self._conn()
        c = conn.cursor()
        c.execute(sql, params)
        conn.commit()
        conn.close()
        return c

    def fetchone(self, sql: str, params: tuple = ()) -> Optional[sqlite3.Row]:
        conn = self._conn()
        c = conn.cursor()
        c.execute(sql, params)
        row = c.fetchone()
        conn.close()
        return row

    def fetchall(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        conn = self._conn()
        c = conn.cursor()
        c.execute(sql, params)
        rows = c.fetchall()
        conn.close()
        return rows

    def upsert(self, table: str, data: dict, conflict_columns: str) -> None:
        cols = ", ".join(data.keys())
        placeholders = ", ".join("?" for _ in data)
        update_set = ", ".join(f"{k}=excluded.{k}" for k in data if k != "id")
        sql = f"""
            INSERT INTO {table} ({cols}) VALUES ({placeholders})
            ON CONFLICT({conflict_columns}) DO UPDATE SET {update_set}
        """
        self.execute(sql, tuple(data.values()))

    def get_latest(self, table: str, symbol: str) -> Optional[dict]:
        row = self.fetchone(f"SELECT * FROM {table} WHERE symbol = ? ORDER BY timestamp DESC LIMIT 1", (symbol,))
        return dict(row) if row else None

    def cleanup_old_data(self, retention: dict) -> int:
        conn = self._conn()
        c = conn.cursor()
        deleted = 0
        minute_ago = datetime.now(timezone.utc).timestamp() - retention.get("minute_data_hours", 24) * 3600
        five_min_ago = datetime.now(timezone.utc).timestamp() - retention.get("five_minute_data_days", 90) * 86400
        daily_ago = datetime.now(timezone.utc).timestamp() - retention.get("daily_data_years", 5) * 86400

        for table, cutoff in [("prices", minute_ago), ("indicators", five_min_ago), ("market_structure", five_min_ago)]:
            c.execute(f"DELETE FROM {table} WHERE strftime('%s', timestamp) < ?", (cutoff,))
            deleted += c.rowcount

        conn.commit()
        conn.close()
        return deleted