from __future__ import annotations

import json
import os
import sys
import logging
import sqlite3
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logger = logging.getLogger("tradingai.scheduler")

CRANDLE_BOUNDARIES = [
    "09:20", "09:25", "09:30", "09:35", "09:40", "09:45",
    "10:00", "10:05", "10:10", "10:15", "10:20", "10:25",
    "10:30", "10:35", "10:40", "10:45", "11:00", "11:05",
    "11:10", "11:15", "11:20", "11:25", "11:30", "11:35",
    "11:40", "11:45", "12:00", "12:05", "12:10", "12:15",
    "12:20", "12:25", "12:30", "12:35", "12:40", "12:45",
    "13:00", "13:05", "13:10", "13:15", "13:20", "13:25",
    "13:30", "13:35", "13:40", "13:45", "14:00", "14:05",
    "14:10", "14:15", "14:20", "14:25", "14:30", "14:35",
    "14:40", "14:45", "15:00", "15:05", "15:10", "15:15",
    "15:20", "15:25", "15:30",
]

MAX_AI_OUTLOOKS_PER_SESSION = 200
MIN_AI_INTERVAL_SECONDS = 120
MAX_OUTLOOK_AGE_MINUTES = 30
OUTLOOK_AGE_WARN_MINUTES = 15

PRIMARY_SYMBOLS = ["NIFTY", "BANKNIFTY"]
SUPPORT_SYMBOLS = ["SENSEX", "FINNIFTY"]


class OutlookScheduler:
    def __init__(self):
        self._last_ai_call_time: Dict[str, float] = {}
        self._session_ai_count: Dict[str, int] = {}

    def run(self, dry_run: bool = False) -> dict:
        """Run one full processing cycle for all primary symbols."""
        from db_schema import DB_PATH, init_database
        init_database(DB_PATH)

        results = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "symbols_processed": [],
            "total_snapshots": 0,
            "total_ai_generated": 0,
            "total_changes_detected": 0,
            "errors": [],
        }

        for symbol in PRIMARY_SYMBOLS:
            try:
                symbol_result = self._process_symbol(symbol, dry_run)
                results["symbols_processed"].append(symbol_result)
                results["total_snapshots"] += symbol_result.get("snapshots", 0)
                results["total_ai_generated"] += symbol_result.get("ai_generated", 0)
                results["total_changes_detected"] += symbol_result.get("changes", 0)
            except Exception as e:
                logger.error(f"Error processing {symbol}: {e}")
                results["errors"].append({"symbol": symbol, "error": str(e)})

        for symbol in SUPPORT_SYMBOLS:
            try:
                symbol_result = self._process_symbol(symbol, dry_run)
                results["symbols_processed"].append(symbol_result)
            except Exception as e:
                logger.error(f"Error processing {symbol}: {e}")
                results["errors"].append({"symbol": symbol, "error": str(e)})

        logger.info(
            f"Scheduler run: {results['total_snapshots']} snapshots, "
            f"{results['total_ai_generated']} AI generated, "
            f"{results['total_changes_detected']} changes"
        )
        return results

    def _process_symbol(self, symbol: str, dry_run: bool = False) -> dict:
        result = {
            "symbol": symbol,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "snapshots": 0,
            "ai_generated": 0,
            "changes": 0,
            "candle_timestamp": None,
            "trigger_reason": None,
            "ai_generation_required": False,
            "ai_generation_result": "SKIPPED",
        }

        candle_timestamp = self._get_current_candle_timestamp()
        if not candle_timestamp:
            logger.info(f"[{symbol}] Market closed or pre-open, skipping")
            result["trigger_reason"] = "market_closed"
            return result

        result["candle_timestamp"] = candle_timestamp

        if self._is_duplicate(symbol, candle_timestamp):
            logger.info(f"[{symbol}] Duplicate candle {candle_timestamp}, skipping")
            result["trigger_reason"] = "duplicate_candle"
            result["ai_generation_result"] = "DUPLICATE_SKIPPED"
            return result

        from market_snapshot import create_snapshot, get_latest_snapshot
        snapshot = create_snapshot(symbol, candle_timestamp)
        if snapshot:
            result["snapshots"] = 1

        current_state = get_latest_snapshot(symbol)
        if not current_state:
            logger.info(f"[{symbol}] No snapshot data available")
            result["trigger_reason"] = "insufficient_data"
            return result

        from outlook_change_detector import evaluate as evaluate_change
        from outlook_change_detector import needs_ai_outlook

        change_result = evaluate_change(symbol)
        result["changes"] = 1 if change_result.get("material_change") else 0

        ai_needs = needs_ai_outlook(symbol)
        result["ai_generation_required"] = ai_needs["needs_ai"]
        result["trigger_reason"] = ai_needs["reason"]

        if ai_needs["needs_ai"] and not dry_run:
            ai_result = self._generate_ai_outlook(symbol, current_state, change_result.get("changes", []))
            result["ai_generated"] = 1 if ai_result else 0
            result["ai_generation_result"] = "SUCCESS" if ai_result else "FAILED"

        return result

    def _get_current_candle_timestamp(self) -> Optional[str]:
        now_utc = datetime.now(timezone.utc)
        ist = now_utc + timedelta(hours=5, minutes=30)
        time_str = ist.strftime("%H:%M")

        if time_str in CRANDLE_BOUNDARIES:
            return ist.strftime("%Y-%m-%dT%H:%M:%SZ")

        return None

    def _is_duplicate(self, symbol: str, candle_timestamp: str) -> bool:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM market_snapshots_5m WHERE symbol=? AND candle_timestamp=?",
                (symbol, candle_timestamp),
            ).fetchone()
            return row[0] > 0
        finally:
            conn.close()

    def _generate_ai_outlook(self, symbol: str, snapshot: dict, changes: list) -> Optional[dict]:
        now = time.time()
        key = symbol

        last_call = self._last_ai_call_time.get(key, 0)
        if now - last_call < MIN_AI_INTERVAL_SECONDS:
            logger.info(f"[{symbol}] AI minimum interval not met, skipping")
            return None

        if self._session_ai_count.get(key, 0) >= MAX_AI_OUTLOOKS_PER_SESSION:
            logger.info(f"[{symbol}] Max AI outlook session count reached")
            return None

        from ai_outlook_5m import AIOutlookGenerator5m
        generator = AIOutlookGenerator5m()

        try:
            outlook = generator.generate(symbol, snapshot, changes)
            self._store_outlook(outlook)
            self._last_ai_call_time[key] = now
            self._session_ai_count[key] = self._session_ai_count.get(key, 0) + 1
            logger.info(f"[{symbol}] AI outlook stored: {outlook['outlook_id']}")
            return outlook
        except Exception as e:
            logger.error(f"[{symbol}] AI generation failed: {e}")
            return None

    def _store_outlook(self, outlook: dict) -> None:
        from db_schema import DB_PATH
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute(
                """INSERT OR REPLACE INTO ai_outlooks_5m
                   (outlook_id, instrument, candle_timestamp, generated_at, model,
                    model_version, prompt_version, bias, confidence, market_regime,
                    summary, evidence_json, watch_levels_json, confirmation_json,
                    invalidation_json, risk_json, trade_state, expected_horizon_minutes,
                    material_changes_json, data_state, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    outlook["outlook_id"], outlook["instrument"], outlook["candle_timestamp"],
                    outlook["generated_at"], outlook["model"], outlook["model_version"],
                    outlook["prompt_version"], outlook["bias"], outlook["confidence"],
                    outlook["market_regime"], outlook["summary"],
                    json.dumps(outlook.get("evidence", [])),
                    json.dumps(outlook.get("watch_levels", [])),
                    json.dumps(outlook.get("confirmation_conditions", [])),
                    json.dumps(outlook.get("invalidation_conditions", [])),
                    json.dumps(outlook.get("risk_conditions", [])),
                    outlook["trade_state"], outlook["expected_horizon_minutes"],
                    json.dumps(outlook.get("material_changes", [])),
                    outlook.get("data_state", "LIVE"),
                    outlook["generated_at"],
                ),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            logger.info(f"Outlook {outlook['outlook_id']} already exists (idempotent)")
        finally:
            conn.close()


def run_scheduler(dry_run: bool = False) -> dict:
    scheduler = OutlookScheduler()
    return scheduler.run(dry_run=dry_run)


def get_current_candle_timestamp() -> Optional[str]:
    scheduler = OutlookScheduler()
    return scheduler._get_current_candle_timestamp()


def is_market_open() -> dict:
    now_utc = datetime.now(timezone.utc)
    ist = now_utc + timedelta(hours=5, minutes=30)
    time_str = ist.strftime("%H:%M")
    weekday = ist.weekday()

    market_open = weekday < 5 and "09:15" <= time_str <= "15:30"
    session = "LIVE" if market_open else "CLOSED"

    return {
        "market_open": market_open,
        "session": session,
        "ist_time": ist.strftime("%H:%M:%S IST"),
        "ist_date": ist.strftime("%d %b %Y"),
        "current_candle": get_current_candle_timestamp(),
    }
