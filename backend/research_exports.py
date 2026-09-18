from __future__ import annotations

import json
import os
import sys
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from db_schema import DB_PATH

logger = logging.getLogger("tradingai.research_export")


class ResearchExporter:
    def __init__(self, db_path: str = None):
        self.db_path = db_path or DB_PATH

    def _get_conn(self):
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=10000")
        return conn

    def export_setup_identity(
        self, instrument: str = "", limit: int = 500, as_json: bool = False
    ) -> Any:
        conn = self._get_conn()
        try:
            if instrument:
                rows = conn.execute(
                    "SELECT * FROM research_setup_identity WHERE instrument=? ORDER BY candle_timestamp DESC LIMIT ?",
                    (instrument, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM research_setup_identity ORDER BY candle_timestamp DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            result = [dict(r) for r in rows]
            if as_json:
                return json.dumps(result, indent=2, default=str)
            return result
        finally:
            conn.close()

    def export_reentry_log(
        self, instrument: str = "", limit: int = 500, as_json: bool = False
    ) -> Any:
        conn = self._get_conn()
        try:
            if instrument:
                rows = conn.execute(
                    "SELECT * FROM research_reentry_log WHERE instrument=? ORDER BY candle_timestamp DESC LIMIT ?",
                    (instrument, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM research_reentry_log ORDER BY candle_timestamp DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            result = [dict(r) for r in rows]
            if as_json:
                return json.dumps(result, indent=2, default=str)
            return result
        finally:
            conn.close()

    def export_ai_calls(
        self, instrument: str = "", limit: int = 500, as_json: bool = False
    ) -> Any:
        conn = self._get_conn()
        try:
            if instrument:
                rows = conn.execute(
                    "SELECT * FROM research_ai_call_log WHERE instrument=? ORDER BY call_timestamp DESC LIMIT ?",
                    (instrument, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM research_ai_call_log ORDER BY call_timestamp DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            result = [dict(r) for r in rows]
            if as_json:
                return json.dumps(result, indent=2, default=str)
            return result
        finally:
            conn.close()

    def export_outcomes(
        self, instrument: str = "", limit: int = 500, as_json: bool = False
    ) -> Any:
        conn = self._get_conn()
        try:
            if instrument:
                rows = conn.execute(
                    "SELECT * FROM research_outcome_tracking WHERE instrument=? ORDER BY candle_timestamp DESC LIMIT ?",
                    (instrument, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM research_outcome_tracking ORDER BY candle_timestamp DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            result = [dict(r) for r in rows]
            if as_json:
                return json.dumps(result, indent=2, default=str)
            return result
        finally:
            conn.close()

    def export_manifest(self, as_json: bool = False) -> Any:
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM research_manifest ORDER BY created_at DESC"
            ).fetchall()
            result = [dict(r) for r in rows]
            if as_json:
                return json.dumps(result, indent=2, default=str)
            return result
        finally:
            conn.close()

    def export_summary(self) -> dict:
        conn = self._get_conn()
        try:
            summary = self._get_conn()
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

            reentry_stats = conn.execute(
                "SELECT reentry_type, COUNT(*) as cnt FROM research_reentry_log GROUP BY reentry_type"
            ).fetchall()
            result["reentry_stats"] = {r["reentry_type"]: r["cnt"] for r in reentry_stats}

            ai_success = conn.execute(
                "SELECT success, COUNT(*) as cnt FROM research_ai_call_log GROUP BY success"
            ).fetchall()
            result["ai_call_success"] = {str(r["success"]): r["cnt"] for r in ai_success}

            return result
        finally:
            conn.close()

    def export_csv_row_format(self, table: str, instrument: str = "") -> List[dict]:
        conn = self._get_conn()
        try:
            if instrument:
                rows = conn.execute(
                    f"SELECT * FROM {table} WHERE instrument=? LIMIT 1",
                    (instrument,),
                ).fetchall()
            else:
                rows = conn.execute(f"SELECT * FROM {table} LIMIT 1").fetchall()
            if not rows:
                return []
            cols = [d[0] for d in rows[0].keys()] if hasattr(rows[0], 'keys') else []
            return [{"column": c, "type": "text"} for c in cols]
        finally:
            conn.close()

    def get_research_datasets_info(self) -> List[dict]:
        datasets = [
            {
                "name": "market_snapshot_research",
                "source_table": "market_snapshots_5m",
                "description": "5-minute market snapshots with data quality",
            },
            {
                "name": "evidence_research",
                "source_table": "market_evidence_5m",
                "description": "6-group evidence evaluation per candle",
            },
            {
                "name": "ai_outlook_research",
                "source_table": "ai_outlooks_5m",
                "description": "AI outlook generation log",
            },
            {
                "name": "qualification_research",
                "source_table": "paper_trades",
                "description": "Trade qualification decisions",
            },
            {
                "name": "paper_trade_research",
                "source_table": "paper_trades",
                "description": "Paper trade lifecycle",
            },
            {
                "name": "outcome_research",
                "source_table": "research_outcome_tracking",
                "description": "Future outcome tracking (5m/15m/30m/60m)"
            },
            {
                "name": "setup_research",
                "source_table": "research_setup_identity",
                "description": "Setup identity and fingerprint tracking",
            },
        ]
        conn = self._get_conn()
        try:
            for ds in datasets:
                table = ds["source_table"]
                try:
                    count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                    ds["row_count"] = count
                except Exception:
                    ds["row_count"] = 0
                ds["schema_version"] = "1.0.0-phase42a"
                ds["generated_timestamp"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                ds["engine_version"] = "1.0.0-phase42a"
        finally:
            conn.close()
        return datasets