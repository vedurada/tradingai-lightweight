from __future__ import annotations

import json
import os
import sys
import sqlite3
import logging
from datetime import datetime, timezone
from typing import Any, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from market_change import is_material_change, get_current_state, get_previous_snapshot, should_regenerate_ai

logger = logging.getLogger("tradingai.outlook_detector")

DEFAULT_SYMBOLS = ["NIFTY", "BANKNIFTY"]
SUPPORT_SYMBOLS = ["SENSEX", "FINNIFTY"]

MATERIAL_THRESHOLDS = {
    "regime_change": True,
    "confidence_swing": 15.0,
    "vix_move_points": 5.0,
    "price_move_pct": 1.0,
    "bias_reversal": True,
    "vwap_cross": True,
    "level_break": True,
}

OUTLOOK_MAX_AGE_MINUTES = 30
OUTLOOK_AGE_WARN_MINUTES = 15


def get_db():
    from db_schema import DB_PATH
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


def evaluate(symbol: str = "NIFTY") -> dict:
    conn = get_db()
    try:
        current = get_current_state(conn, symbol)
        previous = get_previous_snapshot(conn, symbol)
        change = is_material_change(current, previous)

        regen = should_regenerate_ai(symbol)

        result = {
            "symbol": symbol,
            "current_state": {
                "regime": (current.get("regime") or {}).get("regime"),
                "trend": (current.get("regime") or {}).get("trend"),
                "confidence": (current.get("regime") or {}).get("confidence"),
                "price_vs_vwap": _price_vs_vwap(current),
                "vix": (current.get("vix") or {}).get("close"),
                "rsi": (current.get("indicators") or {}).get("rsi"),
                "adx": (current.get("indicators") or {}).get("adx"),
                "captured_at": current.get("captured_at"),
            },
            "material_change": change["material"],
            "change_reason": change["reason"],
            "changes": change["changes"],
            "regenerate_ai": regen["regenerate"],
            "regenerate_reason": regen["reason"],
            "ai_outlook_age_minutes": regen.get("ai_outlook_age_minutes"),
            "max_age_minutes": regen.get("max_age_minutes"),
        }

        logger.info(
            f"[{symbol}] material={change['material']} regen={regen['regenerate']} "
            f"reason={regen['reason']} changes={len(change['changes'])}"
        )
        return result
    finally:
        conn.close()


def _price_vs_vwap(state: dict) -> str:
    price = (state.get("price") or {}).get("close")
    vwap = (state.get("indicators") or {}).get("vwap")
    if price is None or vwap is None:
        return "UNKNOWN"
    diff_pct = (price - vwap) / vwap * 100 if vwap else 0
    if diff_pct > 0.5:
        return "ABOVE"
    elif diff_pct < -0.5:
        return "BELOW"
    return "NEAR"


def needs_ai_outlook(symbol: str = "NIFTY") -> dict:
    conn = get_db()
    try:
        regen = should_regenerate_ai(symbol)
        return {
            "symbol": symbol,
            "needs_ai": regen["regenerate"],
            "reason": regen["reason"],
            "material_changes": regen.get("material_changes", []),
        }
    finally:
        conn.close()
