#!/usr/bin/env python3
"""Phase 9A — Immutable Trade Journal.

Components:
- TradeJournal: insert, get, list with immutable core fields
- JournalEvent: append-only event log per journal entry
- UserFeedback: feedback on a journaled trade
- Minimum sample-size protection at query time
- AI excluded from all journal calculations
"""
import os
import sys
import json
import uuid
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sql_guard import assert_table_name

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "database", "tradingai.db")
MIN_SAMPLE_SIZE = 10


class TradeJournalRecord:
    __slots__ = [
        "journal_id", "tradingai_setup_id", "date", "instrument", "strategy",
        "direction", "planned_entry", "actual_entry", "stop", "target",
        "actual_exit", "quantity", "risk_planned", "risk_actual",
        "market_regime", "tradingai_evidence_score", "tradingai_confidence",
        "user_action", "user_reason", "result", "mistake", "notes",
        "created_at", "updated_at",
    ]

    def __init__(self, **kwargs):
        for field in self.__slots__:
            setattr(self, field, kwargs.get(field))

    @classmethod
    def from_row(cls, row):
        if row is None:
            return None
        return cls(**dict(row)) if hasattr(row, "keys") else cls(**dict(zip(
            cls.__slots__, row)))

    @classmethod
    def from_db_row(cls, row):
        if row is None:
            return None
        return cls(**dict(row))


class JournalEvent:
    __slots__ = ["event_id", "journal_id", "event_type", "field_name",
                  "old_value", "new_value", "created_at"]

    def __init__(self, **kwargs):
        for field in self.__slots__:
            setattr(self, field, kwargs.get(field))

    @classmethod
    def from_row(cls, row):
        if row is None:
            return None
        return cls(**dict(row)) if hasattr(row, "keys") else cls(**dict(zip(
            cls.__slots__, row)))

    @classmethod
    def from_db_row(cls, row):
        if row is None:
            return None
        return cls(**dict(row))


class UserFeedback:
    __slots__ = ["feedback_id", "journal_id", "rating", "category", "comment", "created_at"]

    def __init__(self, **kwargs):
        for field in self.__slots__:
            setattr(self, field, kwargs.get(field))

    @classmethod
    def from_row(cls, row):
        if row is None:
            return None
        return cls(**dict(row)) if hasattr(row, "keys") else cls(**dict(zip(
            cls.__slots__, row)))

    @classmethod
    def from_db_row(cls, row):
        if row is None:
            return None
        return cls(**dict(row))


def _conn():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


def init_tables():
    conn = _conn()
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS trade_journal (
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
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS trade_journal_events (
            event_id TEXT PRIMARY KEY,
            journal_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            field_name TEXT,
            old_value TEXT,
            new_value TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (journal_id) REFERENCES trade_journal(journal_id)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS user_feedback (
            feedback_id TEXT PRIMARY KEY,
            journal_id TEXT NOT NULL,
            rating INTEGER CHECK(rating >= 1 AND rating <= 5),
            category TEXT,
            comment TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (journal_id) REFERENCES trade_journal(journal_id)
        )
    """)
    c.execute("""
        CREATE INDEX IF NOT EXISTS idx_journal_date ON trade_journal(date)
    """)
    c.execute("""
        CREATE INDEX IF NOT EXISTS idx_journal_instrument ON trade_journal(instrument)
    """)
    c.execute("""
        CREATE INDEX IF NOT EXISTS idx_journal_setup_id ON trade_journal(tradingai_setup_id)
    """)
    c.execute("""
        CREATE INDEX IF NOT EXISTS idx_journal_action ON trade_journal(user_action)
    """)
    c.execute("""
        CREATE INDEX IF NOT EXISTS idx_journal_events_journal ON trade_journal_events(journal_id)
    """)
    c.execute("""
        CREATE INDEX IF NOT EXISTS idx_feedback_journal ON user_feedback(journal_id)
    """)
    conn.commit()
    conn.close()


def insert_journal(
    date: str,
    instrument: str,
    strategy: str = None,
    direction: str = None,
    planned_entry: float = None,
    actual_entry: float = None,
    stop: float = None,
    target: float = None,
    actual_exit: float = None,
    quantity: int = None,
    risk_planned: float = None,
    risk_actual: float = None,
    market_regime: str = None,
    tradingai_evidence_score: float = None,
    tradingai_confidence: float = None,
    user_action: str = "PENDING",
    user_reason: str = None,
    result: str = None,
    mistake: str = None,
    notes: str = None,
    tradingai_setup_id: str = None,
) -> TradeJournalRecord:
    """Insert a new immutable journal entry.

    Core fields (planned/actual entry, stop, target, exit, risk) are immutable
    after insertion. Only notes, mistake, and user_action can be updated
    (creating audit events).
    """
    conn = _conn()
    try:
        now = datetime.now(timezone.utc).isoformat()
        journal_id = "J-" + str(uuid.uuid4())[:12]
        c = conn.cursor()
        c.execute("""
            INSERT INTO trade_journal (
                journal_id, tradingai_setup_id, date, instrument, strategy,
                direction, planned_entry, actual_entry, stop, target,
                actual_exit, quantity, risk_planned, risk_actual,
                market_regime, tradingai_evidence_score, tradingai_confidence,
                user_action, user_reason, result, mistake, notes,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            journal_id, tradingai_setup_id, date, instrument.upper(), strategy,
            direction.upper() if direction else None, planned_entry, actual_entry,
            stop, target, actual_exit, quantity, risk_planned, risk_actual,
            market_regime, tradingai_evidence_score, tradingai_confidence,
            user_action.upper(), user_reason, result, mistake, notes,
            now, now,
        ))
        conn.commit()
        return get_journal(journal_id)
    finally:
        conn.close()


def get_journal(journal_id: str) -> Optional[TradeJournalRecord]:
    conn = _conn()
    try:
        row = conn.execute(
            "SELECT * FROM trade_journal WHERE journal_id = ?", (journal_id,)
        ).fetchone()
        return TradeJournalRecord.from_db_row(row)
    finally:
        conn.close()


def list_journals(
    instrument: str = None,
    date_from: str = None,
    date_to: str = None,
    user_action: str = None,
    limit: int = 50,
    offset: int = 0,
) -> List[TradeJournalRecord]:
    conn = _conn()
    try:
        query = "SELECT * FROM trade_journal WHERE 1=1"
        params = []
        if instrument:
            query += " AND instrument = ?"
            params.append(instrument.upper())
        if date_from:
            query += " AND date >= ?"
            params.append(date_from)
        if date_to:
            query += " AND date <= ?"
            params.append(date_to)
        if user_action:
            query += " AND user_action = ?"
            params.append(user_action.upper())
        query += " ORDER BY date DESC, created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        rows = conn.execute(query, params).fetchall()
        return [TradeJournalRecord.from_db_row(row) for row in rows]
    finally:
        conn.close()


def update_journal_notes(journal_id: str, notes: str = None, mistake: str = None,
                          user_action: str = None, user_reason: str = None) -> Optional[TradeJournalRecord]:
    """Update only mutable fields (notes, mistake, user_action, user_reason).

    Creates audit events for tracking. Core trade fields remain immutable.
    """
    conn = _conn()
    try:
        now = datetime.now(timezone.utc).isoformat()
        existing = get_journal(journal_id)
        if existing is None:
            return None

        updates = []
        params = []
        events = []

        if notes is not None and notes != existing.notes:
            updates.append("notes = ?")
            params.append(notes)
            events.append(("NOTES_UPDATE", "notes", existing.notes, notes))

        if mistake is not None and mistake != existing.mistake:
            updates.append("mistake = ?")
            params.append(mistake)
            events.append(("MISTAKE_UPDATE", "mistake", existing.mistake, mistake))

        if user_action is not None and user_action != existing.user_action:
            updates.append("user_action = ?")
            params.append(user_action.upper())
            events.append(("ACTION_UPDATE", "user_action", existing.user_action, user_action.upper()))

        if user_reason is not None and user_reason != existing.user_reason:
            updates.append("user_reason = ?")
            params.append(user_reason)
            events.append(("REASON_UPDATE", "user_reason", existing.user_reason, user_reason))

        if not updates:
            return existing

        updates.append("updated_at = ?")
        params.append(now)
        params.append(journal_id)

        c = conn.cursor()
        c.execute(f"UPDATE trade_journal SET {', '.join(updates)} WHERE journal_id = ?", params)

        for event_type, field_name, old_val, new_val in events:
            event_id = "JE-" + str(uuid.uuid4())[:12]
            c.execute("""
                INSERT INTO trade_journal_events (event_id, journal_id, event_type, field_name, old_value, new_value, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (event_id, journal_id, event_type, field_name,
                  str(old_val) if old_val else None, str(new_val) if new_val else None, now))

        conn.commit()
        return get_journal(journal_id)
    finally:
        conn.close()


def get_events(journal_id: str) -> List[JournalEvent]:
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT * FROM trade_journal_events WHERE journal_id = ? ORDER BY created_at",
            (journal_id,),
        ).fetchall()
        return [JournalEvent.from_db_row(row) for row in rows]
    finally:
        conn.close()


def add_feedback(journal_id: str, rating: int, category: str = None,
                   comment: str = None) -> Optional[UserFeedback]:
    conn = _conn()
    try:
        feedback_id = "FB-" + str(uuid.uuid4())[:12]
        now = datetime.now(timezone.utc).isoformat()
        c = conn.cursor()
        c.execute("""
            INSERT INTO user_feedback (feedback_id, journal_id, rating, category, comment, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (feedback_id, journal_id, rating, category, comment, now))
        conn.commit()
        c.execute("SELECT * FROM user_feedback WHERE feedback_id = ?", (feedback_id,))
        return UserFeedback.from_db_row(c.fetchone())
    finally:
        conn.close()


def get_feedback(journal_id: str) -> List[UserFeedback]:
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT * FROM user_feedback WHERE journal_id = ? ORDER BY created_at",
            (journal_id,),
        ).fetchall()
        return [UserFeedback.from_db_row(row) for row in rows]
    finally:
        conn.close()


def get_trade_count(instrument: str = None, strategy: str = None,
                     date_from: str = None, date_to: str = None) -> int:
    conn = _conn()
    try:
        query = "SELECT COUNT(*) FROM trade_journal WHERE 1=1"
        params = []
        if instrument:
            query += " AND instrument = ?"
            params.append(instrument.upper())
        if strategy:
            query += " AND strategy = ?"
            params.append(strategy)
        if date_from:
            query += " AND date >= ?"
            params.append(date_from)
        if date_to:
            query += " AND date <= ?"
            params.append(date_to)
        row = conn.execute(query, params).fetchone()
        return row[0]
    finally:
        conn.close()


def has_minimum_sample(instrument: str = None, strategy: str = None,
                         date_from: str = None, date_to: str = None) -> bool:
    count = get_trade_count(instrument=instrument, strategy=strategy,
                             date_from=date_from, date_to=date_to)
    return count >= MIN_SAMPLE_SIZE


def get_comparison(journal_id: str) -> Optional[Dict[str, Any]]:
    """Get TradingAI plan vs actual trader action comparison."""
    record = get_journal(journal_id)
    if record is None:
        return None
    return {
        "journal_id": record.journal_id,
        "tradingai_setup_id": record.tradingai_setup_id,
        "date": record.date,
        "instrument": record.instrument,
        "strategy": record.strategy,
        "direction": record.direction,
        "tradingai_plan": {
            "planned_entry": record.planned_entry,
            "planned_stop": record.stop,
            "planned_target": record.target,
            "risk_planned": record.risk_planned,
            "market_regime": record.market_regime,
            "tradingai_evidence_score": record.tradingai_evidence_score,
            "tradingai_confidence": record.tradingai_confidence,
        },
        "actual_action": {
            "actual_entry": record.actual_entry,
            "actual_exit": record.actual_exit,
            "actual_stop": record.stop,
            "actual_target": record.target,
            "actual_quantity": record.quantity,
            "risk_actual": record.risk_actual,
            "user_action": record.user_action,
            "user_reason": record.user_reason,
        },
        "differences": _compute_differences(record),
        "outcome": {
            "result": record.result,
            "mistake": record.mistake,
        },
    }


def _compute_differences(record: TradeJournalRecord) -> List[str]:
    diffs = []
    if record.actual_entry is not None and record.planned_entry is not None:
        if record.direction == "LONG":
            if record.actual_entry > record.planned_entry * 1.001:
                diffs.append("entered_high")
            elif record.actual_entry < record.planned_entry * 0.999:
                diffs.append("entered_low")
            elif record.planned_entry == record.actual_entry:
                pass
            else:
                diffs.append("entered_different_price")
        elif record.direction == "SHORT":
            if record.actual_entry < record.planned_entry * 0.999:
                diffs.append("entered_high")
            elif record.actual_entry > record.planned_entry * 1.001:
                diffs.append("entered_low")
            else:
                diffs.append("entered_different_price")

    if record.user_action and record.tradingai_confidence is not None:
        action = record.user_action.upper()
        if action == "TRADED" and record.tradingai_confidence == 0:
            diffs.append("took_trade_with_zero_confidence")

    if record.risk_actual is not None and record.risk_planned is not None:
        if record.risk_actual > record.risk_planned * 1.05:
            diffs.append("exceeded_planned_risk")
        elif record.risk_actual < record.risk_planned * 0.95:
            diffs.append("under_planned_risk")

    if record.result and record.result.upper() in ("WIN", "PROFIT"):
        pass
    elif record.result and record.result.upper() in ("LOSS", "FAIL"):
        if record.mistake:
            diffs.append("mistake_recorded: " + record.mistake.lower().replace(" ", "_"))
    return diffs


def get_deterministic_stats(instrument: str = None, strategy: str = None,
                              date_from: str = None, date_to: str = None) -> Dict[str, Any]:
    """Compute deterministic statistics. Requires minimum sample size."""
    has_sample = has_minimum_sample(instrument=instrument, strategy=strategy,
                                     date_from=date_from, date_to=date_to)
    if not has_sample:
        return {
            "insufficient_data": True,
            "message": f"INSUFFICIENT_DATA: need {MIN_SAMPLE_SIZE} trades, have {get_trade_count(instrument=instrument, strategy=strategy, date_from=date_from, date_to=date_to)}",
            "sample_size": get_trade_count(instrument=instrument, strategy=strategy, date_from=date_from, date_to=date_to),
            "minimum_required": MIN_SAMPLE_SIZE,
        }

    conn = _conn()
    try:
        query = """
            SELECT 
                COUNT(*) as total_trades,
                SUM(CASE WHEN result = 'WIN' OR result = 'PROFIT' THEN 1 ELSE 0 END) as wins,
                SUM(CASE WHEN result = 'LOSS' OR result = 'FAIL' THEN 1 ELSE 0 END) as losses,
                AVG(risk_actual) as avg_risk,
                AVG(risk_planned) as avg_planned_risk,
                SUM(CASE WHEN user_action = 'TRADED' THEN 1 ELSE 0 END) as took_trade,
                SUM(CASE WHEN user_action = 'SKIPPED' THEN 1 ELSE 0 END) as skipped,
                SUM(CASE WHEN user_action = 'PAPER' THEN 1 ELSE 0 END) as paper_traded
            FROM trade_journal
            WHERE 1=1
        """
        params = []
        if instrument:
            query += " AND instrument = ?"
            params.append(instrument.upper())
        if strategy:
            query += " AND strategy = ?"
            params.append(strategy)
        if date_from:
            query += " AND date >= ?"
            params.append(date_from)
        if date_to:
            query += " AND date <= ?"
            params.append(date_to)

        row = conn.execute(query, params).fetchone()
        total = row[0] or 0
        wins = row[1] or 0
        losses = row[2] or 0

        result = {
            "insufficient_data": False,
            "sample_size": total,
            "minimum_required": MIN_SAMPLE_SIZE,
            "total_trades": total,
            "wins": wins,
            "losses": losses,
            "win_rate": round(wins / total * 100, 2) if total > 0 else 0,
            "avg_risk_actual": round(row[3], 2) if row[3] else None,
            "avg_risk_planned": round(row[4], 2) if row[4] else None,
            "took_trade": row[5] or 0,
            "skipped": row[6] or 0,
            "paper_traded": row[7] or 0,
        }

        regime_query = """
            SELECT market_regime, COUNT(*) as cnt,
                SUM(CASE WHEN result = 'WIN' OR result = 'PROFIT' THEN 1 ELSE 0 END) as wins
            FROM trade_journal
            WHERE market_regime IS NOT NULL AND user_action = 'TRADED'
        """
        regime_params = []
        if instrument:
            regime_query += " AND instrument = ?"
            regime_params.append(instrument.upper())
        regime_query += " GROUP BY market_regime"

        regime_rows = conn.execute(regime_query, regime_params).fetchall()
        regime_stats = {}
        for r in regime_rows:
            regime = r[0]
            regime_total = r[1]
            regime_wins = r[2] or 0
            regime_stats[regime] = {
                "trades": regime_total,
                "wins": regime_wins,
                "win_rate": round(regime_wins / regime_total * 100, 2) if regime_total > 0 else 0,
            }
        result["by_regime"] = regime_stats

        action_query = """
            SELECT 
                SUM(CASE WHEN planned_entry IS NOT NULL AND actual_entry IS NOT NULL 
                    AND ABS(planned_entry - actual_entry) > 0.01 THEN 1 ELSE 0 END) as entered_different,
                SUM(CASE WHEN stop IS NOT NULL AND actual_exit IS NOT NULL 
                    AND actual_exit < stop THEN 1 ELSE 0 END) as exited_before_stop,
                SUM(CASE WHEN target IS NOT NULL AND actual_exit IS NOT NULL 
                    AND actual_exit >= target THEN 1 ELSE 0 END) as exited_at_target
            FROM trade_journal
            WHERE user_action = 'TRADED'
        """
        action_params = []
        if instrument:
            action_query += " AND instrument = ?"
            action_params.append(instrument.upper())

        action_row = conn.execute(action_query, action_params).fetchone()
        result["timing"] = {
            "entered_different_than_planned": action_row[0] or 0,
            "exited_before_stop": action_row[1] or 0,
            "exited_at_target": action_row[2] or 0,
        }

        return result
    finally:
        conn.close()
