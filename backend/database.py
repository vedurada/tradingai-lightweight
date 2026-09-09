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
        c.execute("""
            CREATE TABLE IF NOT EXISTS portfolio (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT,
                strategy TEXT,
                entry_price REAL,
                quantity INTEGER,
                direction TEXT CHECK(direction IN ('LONG', 'SHORT')),
                entry_date TEXT,
                exit_price REAL,
                exit_date TEXT,
                points REAL,
                result TEXT CHECK(result IN ('WIN', 'LOSS', 'FLAT', 'OPEN')),
                created_at TEXT
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT,
                date TEXT,
                locked_price REAL,
                closed_price REAL,
                points REAL,
                result TEXT CHECK(result IN ('WIN', 'LOSS', 'FLAT', 'OPEN')),
                strategy TEXT,
                market_regime TEXT,
                directional_bias TEXT,
                confidence REAL,
                market_summary TEXT,
                evidence_strength REAL DEFAULT 0,
                volatility_classification TEXT,
                market_structure TEXT,
                no_trade_conditions TEXT,
                strategy_environment TEXT,
                invalidation TEXT,
                created_at TEXT,
                UNIQUE(symbol, date)
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS history_archive (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT,
                date TEXT,
                locked_price REAL,
                closed_price REAL,
                points REAL,
                result TEXT,
                strategy TEXT,
                market_regime TEXT,
                directional_bias TEXT,
                confidence REAL,
                market_summary TEXT,
                evidence_strength REAL,
                volatility_classification TEXT,
                market_structure TEXT,
                no_trade_conditions TEXT,
                strategy_environment TEXT,
                invalidation TEXT,
                created_at TEXT,
                archived_at TEXT
            )
        """)
        conn.commit()
        self._migrate(conn)
        self._create_indexes(conn)
        conn.close()

    def _migrate(self, conn) -> None:
        c = conn.cursor()
        try:
            c.execute("PRAGMA table_info(history)")
            cols = {row[1] for row in c.fetchall()}
            additions = [
                ("evidence_strength", "REAL DEFAULT 0"),
                ("volatility_classification", "TEXT"),
                ("market_structure", "TEXT"),
                ("no_trade_conditions", "TEXT"),
                ("strategy_environment", "TEXT"),
                ("invalidation", "TEXT"),
            ]
            for col_name, col_type in additions:
                if col_name not in cols:
                    c.execute(f"ALTER TABLE history ADD COLUMN {col_name} {col_type}")
            c.execute("PRAGMA table_info(history_archive)")
            archive_cols = {row[1] for row in c.fetchall()}
            for col_name, col_type in additions:
                if col_name not in archive_cols:
                    c.execute(f"ALTER TABLE history_archive ADD COLUMN {col_name} {col_type}")
            conn.commit()
        except Exception as e:
            logger = __import__("logging").getLogger("tradingai.db")
            logger.warning(f"Migration skipped: {e}")

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

    def _create_indexes(self, conn) -> None:
        c = conn.cursor()
        c.execute("CREATE INDEX IF NOT EXISTS idx_history_symbol_date ON history(symbol, date DESC)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_history_regime ON history(market_regime)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_history_result ON history(result)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_history_archive_symbol_date ON history_archive(symbol, date DESC)")
        conn.commit()

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

    def save_history(self, symbol: str, date: str, locked_price: float, closed_price: float | None = None,
                     strategy: str = "", market_regime: str = "", directional_bias: str = "",
                     confidence: float = 0, market_summary: str = "", evidence_strength: float = 0,
                     volatility_classification: str = "", market_structure: str = "",
                     no_trade_conditions: str = "", strategy_environment: str = "",
                     invalidation: str = "") -> None:
        points = None
        result = None
        if closed_price:
            diff = round(closed_price - locked_price, 2)
            points = diff
            result = "WIN" if diff > 0 else ("LOSS" if diff < 0 else "FLAT")
        conn = self._conn()
        c = conn.cursor()
        c.execute("""
            INSERT INTO history (symbol, date, locked_price, closed_price, points, result, strategy,
                market_regime, directional_bias, confidence, market_summary, evidence_strength,
                volatility_classification, market_structure, no_trade_conditions, strategy_environment,
                invalidation, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(symbol, date) DO UPDATE SET
                locked_price=excluded.locked_price, closed_price=excluded.closed_price,
                points=excluded.points, result=excluded.result, strategy=excluded.strategy,
                market_regime=excluded.market_regime, directional_bias=excluded.directional_bias,
                confidence=excluded.confidence, market_summary=excluded.market_summary,
                evidence_strength=excluded.evidence_strength,
                volatility_classification=excluded.volatility_classification,
                market_structure=excluded.market_structure,
                no_trade_conditions=excluded.no_trade_conditions,
                strategy_environment=excluded.strategy_environment,
                invalidation=excluded.invalidation
        """, (symbol, date, locked_price, closed_price, points, result, strategy,
              market_regime, directional_bias, confidence, market_summary, evidence_strength,
              volatility_classification, market_structure, no_trade_conditions,
              strategy_environment, invalidation))
        conn.commit()
        conn.close()

    def get_history(self, symbol: str, days: int = 30) -> list[dict]:
        conn = self._conn()
        c = conn.cursor()
        c.execute("""
            SELECT symbol, date, locked_price, closed_price, points, result, strategy,
                   market_regime, directional_bias, confidence, market_summary,
                   evidence_strength, volatility_classification, market_structure,
                   no_trade_conditions, strategy_environment, invalidation, created_at
            FROM history WHERE symbol = ? AND date >= date('now', '-' || ? || ' days')
            ORDER BY date DESC
        """, (symbol, days))
        rows = c.fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_all_history(self, days: int = 30) -> dict[str, list[dict]]:
        conn = self._conn()
        c = conn.cursor()
        c.execute("""
            SELECT symbol, date, locked_price, closed_price, points, result, strategy,
                   market_regime, directional_bias, confidence, market_summary,
                   evidence_strength, volatility_classification, market_structure,
                   no_trade_conditions, strategy_environment, invalidation, created_at
            FROM history WHERE date >= date('now', '-' || ? || ' days')
            ORDER BY symbol, date DESC
        """, (days,))
        rows = c.fetchall()
        conn.close()
        result: dict[str, list[dict]] = {}
        for r in rows:
            sym = r["symbol"]
            result.setdefault(sym, []).append(dict(r))
        return result

    def archive_history(self, weekly: bool = True, monthly: bool = False) -> int:
        conn = self._conn()
        c = conn.cursor()
        archived = 0
        if weekly:
            c.execute("""
                INSERT INTO history_archive (symbol, date, locked_price, closed_price, points, result,
                    strategy, market_regime, directional_bias, confidence, market_summary,
                    evidence_strength, volatility_classification, market_structure,
                    no_trade_conditions, strategy_environment, invalidation, created_at, archived_at)
                SELECT symbol, date, locked_price, closed_price, points, result, strategy,
                    market_regime, directional_bias, confidence, market_summary,
                    evidence_strength, volatility_classification, market_structure,
                    no_trade_conditions, strategy_environment, invalidation, created_at, datetime('now')
                FROM history WHERE closed_price IS NOT NULL AND date <= date('now', '-7 days')
            """)
            archived += c.rowcount
            c.execute("DELETE FROM history WHERE closed_price IS NOT NULL AND date <= date('now', '-7 days')")
        if monthly:
            c.execute("""
                INSERT INTO history_archive (symbol, date, locked_price, closed_price, points, result,
                    strategy, market_regime, directional_bias, confidence, market_summary,
                    evidence_strength, volatility_classification, market_structure,
                    no_trade_conditions, strategy_environment, invalidation, created_at, archived_at)
                SELECT symbol, date, locked_price, closed_price, points, result, strategy,
                    market_regime, directional_bias, confidence, market_summary,
                    evidence_strength, volatility_classification, market_structure,
                    no_trade_conditions, strategy_environment, invalidation, created_at, datetime('now')
                FROM history WHERE closed_price IS NOT NULL AND date <= date('now', '-30 days')
            """)
            archived += c.rowcount
            c.execute("DELETE FROM history WHERE closed_price IS NOT NULL AND date <= date('now', '-30 days')")
        conn.commit()
        conn.close()
        return archived

    def save_portfolio(self, symbol: str, strategy: str, entry_price: float, quantity: int,
                       direction: str, entry_date: str) -> None:
        conn = self._conn()
        c = conn.cursor()
        c.execute("""
            INSERT INTO portfolio (symbol, strategy, entry_price, quantity, direction, entry_date, created_at)
            VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
        """, (symbol, strategy, entry_price, quantity, direction, entry_date))
        conn.commit()
        conn.close()

    def close_portfolio(self, portfolio_id: int, exit_price: float, exit_date: str) -> None:
        conn = self._conn()
        c = conn.cursor()
        c.execute("SELECT * FROM portfolio WHERE id = ?", (portfolio_id,))
        row = c.fetchone()
        if row:
            points = round((exit_price - row["entry_price"]) * row["quantity"], 2) if row["direction"] == "LONG" else round((row["entry_price"] - exit_price) * row["quantity"], 2)
            result = "WIN" if points > 0 else ("LOSS" if points < 0 else "FLAT")
            c.execute("""
                UPDATE portfolio SET exit_price = ?, exit_date = ?, points = ?, result = ?
                WHERE id = ?
            """, (exit_price, exit_date, points, result, portfolio_id))
        conn.commit()
        conn.close()

    def get_portfolio(self, symbol: str = "") -> list[dict]:
        conn = self._conn()
        c = conn.cursor()
        if symbol:
            c.execute("SELECT * FROM portfolio WHERE symbol = ? ORDER BY entry_date DESC", (symbol,))
        else:
            c.execute("SELECT * FROM portfolio ORDER BY entry_date DESC")
        rows = c.fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_portfolio_summary(self) -> dict[str, Any]:
        conn = self._conn()
        c = conn.cursor()
        c.execute("SELECT COUNT(*) as total, SUM(points) as total_points, SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END) as wins, SUM(CASE WHEN result='LOSS' THEN 1 ELSE 0 END) as losses, SUM(CASE WHEN result='FLAT' THEN 1 ELSE 0 END) as flats FROM portfolio")
        row = c.fetchone()
        conn.close()
        return dict(row) if row else {}