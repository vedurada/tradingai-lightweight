from __future__ import annotations

import json
import os
import sqlite3
import sys
import logging
import uuid
import hashlib
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from db_schema import DB_PATH, init_database

logger = logging.getLogger("tradingai.research")

ENGINE_VERSION = "1.0.0-phase42a"
DATA_QUALITY_STATES = {"LIVE", "STALE", "MISSING", "PARTIAL", "UNAVAILABLE", "INVALID"}
IST = "Asia/Kolkata"


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _now_ist() -> str:
    from datetime import time as _time, timedelta as _td
    utc_now = datetime.now(timezone.utc)
    ist = utc_now + _td(hours=5, minutes=30)
    return ist.strftime("%Y-%m-%dT%H:%M:%S+05:30")


def _trading_date_ist() -> str:
    from datetime import timedelta as _td
    utc_now = datetime.now(timezone.utc)
    ist = utc_now + _td(hours=5, minutes=30)
    return ist.strftime("%Y-%m-%d")


def generate_setup_id(instrument: str, candle_timestamp: str, direction: str = "") -> str:
    raw = f"{instrument}|{candle_timestamp}|{direction}" if direction else f"{instrument}|{candle_timestamp}"
    return f"SETUP-{hashlib.sha256(raw.encode()).hexdigest()[:16].upper()}"


def generate_setup_fingerprint(
    instrument: str,
    trading_date: str,
    direction: str,
    regime: str,
    trade_state: str,
    strategy: str,
    evidence_state: str = "",
    ai_outlook_id: str = "",
) -> str:
    raw = "|".join([
        instrument,
        trading_date,
        direction or "NEUTRAL",
        regime or "UNKNOWN",
        trade_state or "UNKNOWN",
        strategy or "NONE",
        evidence_state or "",
        ai_outlook_id or "",
    ])
    return hashlib.sha256(raw.encode()).hexdigest()[:24].upper()


class ResearchCollector:
    def __init__(self, db_path: str = None):
        self.db_path = db_path or DB_PATH
        init_database(self.db_path)

    def _get_conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=10000")
        return conn

    def _store(self, table: str, data: dict) -> bool:
        conn = self._get_conn()
        try:
            cols = ", ".join(data.keys())
            placeholders = ", ".join(["?"] * len(data))
            values = list(data.values())
            conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({placeholders})", values)
            conn.commit()
            return True
        except sqlite3.IntegrityError as e:
            logger.info(f"Duplicate research record in {table}: {e}")
            return False
        finally:
            conn.close()

    def record_setup_identity(
        self,
        instrument: str,
        candle_timestamp: str,
        direction: str,
        regime: str,
        trade_state: str,
        strategy: str,
        evidence_summary: dict = None,
        ai_outlook_id: str = "",
        qualification_id: str = "",
        setup_type: str = "NEW",
        is_duplicate_of: str = "",
        previous_setup_id: str = "",
        seconds_since_previous_same_direction: int = 0,
        regime_changed: int = 0,
        direction_changed: int = 0,
        evidence_changed: int = 0,
        outlook_changed: int = 0,
        data_quality: str = "LIVE",
        engine_version: str = ENGINE_VERSION,
    ) -> dict:
        setup_id = generate_setup_id(instrument, candle_timestamp, direction)
        trading_date = candle_timestamp[:10] if len(candle_timestamp) >= 10 else candle_timestamp

        fingerprint = generate_setup_fingerprint(
            instrument=instrument,
            trading_date=trading_date,
            direction=direction,
            regime=regime,
            trade_state=trade_state,
            strategy=strategy,
            evidence_state=json.dumps(evidence_summary or {}) if evidence_summary else "",
            ai_outlook_id=ai_outlook_id,
        )

        record = {
            "setup_id": setup_id,
            "setup_fingerprint": fingerprint,
            "instrument": instrument,
            "candle_timestamp": candle_timestamp,
            "trading_date": trading_date,
            "direction": direction,
            "regime": regime,
            "trade_state": trade_state,
            "strategy": strategy,
            "evidence_summary": json.dumps(evidence_summary or {}),
            "ai_outlook_id": ai_outlook_id,
            "qualification_id": qualification_id,
            "setup_type": setup_type,
            "is_duplicate_of": is_duplicate_of,
            "previous_setup_id": previous_setup_id,
            "seconds_since_previous_same_direction": seconds_since_previous_same_direction,
            "regime_changed": regime_changed,
            "direction_changed": direction_changed,
            "evidence_changed": evidence_changed,
            "outlook_changed": outlook_changed,
            "data_quality": data_quality,
            "engine_version": engine_version,
            "created_at": _now_utc(),
        }

        success = self._store("research_setup_identity", record)
        logger.info(f"[{instrument}] Setup identity: {setup_id} fp={fingerprint[:8]}... type={setup_type}")
        return {"setup_id": setup_id, "setup_fingerprint": fingerprint, "created": success}

    def record_reentry(
        self,
        trade_id: str,
        instrument: str,
        candle_timestamp: str,
        setup_id: str,
        previous_trade_id: str = "",
        previous_exit_timestamp: str = "",
        seconds_since_previous_exit: int = 0,
        previous_direction: str = "",
        current_direction: str = "",
        previous_regime: str = "",
        current_regime: str = "",
        previous_setup_fingerprint: str = "",
        current_setup_fingerprint: str = "",
        same_setup_fingerprint: int = 0,
        direction_changed: int = 0,
        regime_changed: int = 0,
        evidence_changed: int = 0,
        outlook_changed: int = 0,
        reentry_type: str = "UNKNOWN",
        data_quality: str = "LIVE",
        engine_version: str = ENGINE_VERSION,
    ) -> dict:
        record = {
            "trade_id": trade_id,
            "instrument": instrument,
            "candle_timestamp": candle_timestamp,
            "setup_id": setup_id,
            "previous_trade_id": previous_trade_id,
            "previous_exit_timestamp": previous_exit_timestamp,
            "seconds_since_previous_exit": seconds_since_previous_exit,
            "previous_direction": previous_direction,
            "current_direction": current_direction,
            "previous_regime": previous_regime,
            "current_regime": current_regime,
            "previous_setup_fingerprint": previous_setup_fingerprint,
            "current_setup_fingerprint": current_setup_fingerprint,
            "same_setup_fingerprint": same_setup_fingerprint,
            "direction_changed": direction_changed,
            "regime_changed": regime_changed,
            "evidence_changed": evidence_changed,
            "outlook_changed": outlook_changed,
            "reentry_type": reentry_type,
            "data_quality": data_quality,
            "engine_version": engine_version,
            "created_at": _now_utc(),
        }

        success = self._store("research_reentry_log", record)
        logger.info(f"[{instrument}] Re-entry: {trade_id} type={reentry_type} same_fp={same_setup_fingerprint}")
        return {"recorded": success}

    def record_ai_call(
        self,
        instrument: str,
        candle_timestamp: str = "",
        trigger: str = "MATERIAL_CHANGE",
        model: str = "",
        provider: str = "",
        prompt_version: str = "",
        success: int = 0,
        latency_ms: int = None,
        token_usage: int = None,
        error: str = "",
        fallback_used: int = 0,
        outlook_id: str = "",
        data_version: str = "",
    ) -> dict:
        record = {
            "call_timestamp": _now_utc(),
            "instrument": instrument,
            "candle_timestamp": candle_timestamp,
            "trigger": trigger,
            "model": model,
            "provider": provider,
            "prompt_version": prompt_version,
            "success": success,
            "latency_ms": latency_ms,
            "token_usage": token_usage,
            "error": error,
            "fallback_used": fallback_used,
            "outlook_id": outlook_id,
            "data_version": data_version,
            "created_at": _now_utc(),
        }

        success = self._store("research_ai_call_log", record)
        logger.info(f"[{instrument}] AI call recorded: {instrument} success={success}")
        return {"recorded": success}

    def record_outcome(
        self,
        outlook_id: str,
        setup_id: str,
        instrument: str,
        candle_timestamp: str,
        outcome_5m: str = "PENDING",
        outcome_5m_timestamp: str = "",
        outcome_5m_price: float = None,
        outcome_5m_return_pct: float = None,
        outcome_5m_direction: str = "",
        outcome_15m: str = "PENDING",
        outcome_15m_timestamp: str = "",
        outcome_15m_price: float = None,
        outcome_15m_return_pct: float = None,
        outcome_15m_direction: str = "",
        outcome_30m: str = "PENDING",
        outcome_30m_timestamp: str = "",
        outcome_30m_price: float = None,
        outcome_30m_return_pct: float = None,
        outcome_30m_direction: str = "",
        outcome_60m: str = "PENDING",
        outcome_60m_timestamp: str = "",
        outcome_60m_price: float = None,
        outcome_60m_return_pct: float = None,
        outcome_60m_direction: str = "",
        evaluated_at: str = "",
        data_quality: str = "LIVE",
    ) -> dict:
        record = {
            "outlook_id": outlook_id,
            "setup_id": setup_id,
            "instrument": instrument,
            "candle_timestamp": candle_timestamp,
            "outcome_5m": outcome_5m,
            "outcome_5m_timestamp": outcome_5m_timestamp,
            "outcome_5m_price": outcome_5m_price,
            "outcome_5m_return_pct": outcome_5m_return_pct,
            "outcome_5m_direction": outcome_5m_direction,
            "outcome_15m": outcome_15m,
            "outcome_15m_timestamp": outcome_15m_timestamp,
            "outcome_15m_price": outcome_15m_price,
            "outcome_15m_return_pct": outcome_15m_return_pct,
            "outcome_15m_direction": outcome_15m_direction,
            "outcome_30m": outcome_30m,
            "outcome_30m_timestamp": outcome_30m_timestamp,
            "outcome_30m_price": outcome_30m_price,
            "outcome_30m_return_pct": outcome_30m_return_pct,
            "outcome_30m_direction": outcome_30m_direction,
            "outcome_60m": outcome_60m,
            "outcome_60m_timestamp": outcome_60m_timestamp,
            "outcome_60m_price": outcome_60m_price,
            "outcome_60m_return_pct": outcome_60m_return_pct,
            "outcome_60m_direction": outcome_60m_direction,
            "evaluated_at": evaluated_at,
            "data_quality": data_quality,
            "created_at": _now_utc(),
        }

        success = self._store("research_outcome_tracking", record)
        logger.info(f"[{instrument}] Outcome recorded: outlook={outlook_id[:16]}...")
        return {"recorded": success}

    def record_data_health(
        self,
        check_type: str,
        status: str,
        instrument: str = "",
        detail: str = "",
        details: dict = None,
    ) -> dict:
        record = {
            "check_timestamp": _now_utc(),
            "instrument": instrument,
            "check_type": check_type,
            "status": status,
            "detail": detail,
            "details_json": json.dumps(details or {}),
            "created_at": _now_utc(),
        }
        success = self._store("research_data_health", record)
        return {"recorded": success}

    def update_manifest(
        self,
        dataset_name: str,
        schema_version: str,
        source_tables: str,
        row_count: int,
        earliest_timestamp: str,
        latest_timestamp: str,
        instruments: list,
        missingness: dict,
        engine_version: str,
    ) -> dict:
        record = {
            "dataset_name": dataset_name,
            "schema_version": schema_version,
            "source_tables": source_tables,
            "row_count": row_count,
            "earliest_timestamp": earliest_timestamp,
            "latest_timestamp": latest_timestamp,
            "instruments": json.dumps(instruments),
            "missingness": json.dumps(missingness),
            "generated_timestamp": _now_utc(),
            "engine_version": engine_version,
            "data_quality": "LIVE",
            "created_at": _now_utc(),
        }
        conn = self._get_conn()
        try:
            conn.execute(
                "INSERT INTO research_manifest (dataset_name, schema_version, source_tables, row_count, earliest_timestamp, latest_timestamp, instruments, missingness, generated_timestamp, engine_version, data_quality, created_at) "
                "VALUES (:dataset_name, :schema_version, :source_tables, :row_count, :earliest_timestamp, :latest_timestamp, :instruments, :missingness, :generated_timestamp, :engine_version, :data_quality, :created_at) "
                "ON CONFLICT(dataset_name) DO UPDATE SET "
                "row_count=excluded.row_count, earliest_timestamp=excluded.earliest_timestamp, "
                "latest_timestamp=excluded.latest_timestamp, instruments=excluded.instruments, "
                "missingness=excluded.missingness, generated_timestamp=excluded.generated_timestamp",
                record,
            )
            conn.commit()
        finally:
            conn.close()
        return {"updated": True}

    def get_setup_by_fingerprint(self, fingerprint: str) -> Optional[dict]:
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM research_setup_identity WHERE setup_fingerprint=?",
                (fingerprint,),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def get_setups_by_instrument(
        self, instrument: str, limit: int = 100
    ) -> List[dict]:
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM research_setup_identity WHERE instrument=? ORDER BY candle_timestamp DESC LIMIT ?",
                (instrument, limit),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_reentry_stats(self, instrument: str = "") -> dict:
        conn = self._get_conn()
        try:
            if instrument:
                rows = conn.execute(
                    "SELECT reentry_type, COUNT(*) as cnt FROM research_reentry_log WHERE instrument=? GROUP BY reentry_type",
                    (instrument,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT reentry_type, COUNT(*) as cnt FROM research_reentry_log GROUP BY reentry_type"
                ).fetchall()
            return {r["reentry_type"]: r["cnt"] for r in rows}
        finally:
            conn.close()

    def get_research_summary(self) -> dict:
        conn = self._get_conn()
        try:
            result = {}
            for table in [
                "research_setup_identity",
                "research_reentry_log",
                "research_ai_call_log",
                "research_outcome_tracking",
                "research_data_health",
            ]:
                count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                result[table] = count

            earliest = conn.execute(
                "SELECT MIN(candle_timestamp) as ts FROM research_setup_identity"
            ).fetchone()[0]
            latest = conn.execute(
                "SELECT MAX(candle_timestamp) as ts FROM research_setup_identity"
            ).fetchone()[0]
            result["earliest_data"] = earliest
            result["latest_data"] = latest

            instruments = conn.execute(
                "SELECT DISTINCT instrument FROM research_setup_identity"
            ).fetchall()
            result["instruments"] = [r["instrument"] for r in instruments]

            return result
        finally:
            conn.close()