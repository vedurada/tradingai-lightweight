from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import Database

logger = logging.getLogger("tradingai.history")

_db = None

def _get_db() -> Database:
    global _db
    if _db is None:
        db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "database", "tradingai.db")
        _db = Database(db_path)
    return _db

import json

def _to_str(v) -> str:
    if v is None:
        return ""
    if isinstance(v, (list, dict)):
        return json.dumps(v)
    return str(v)

def save_outlook(symbol: str, ai_outlook: dict[str, Any], quote_price: float = 0, strategy_name: str = "") -> None:
    db = _get_db()
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    _strategy_name = strategy_name or (ai_outlook.get("primary_strategy", {}).get("strategy", "") if isinstance(ai_outlook.get("primary_strategy"), dict) else "")
    db.save_history(
        symbol=symbol,
        date=date_str,
        locked_price=quote_price,
        strategy=_strategy_name,
        market_regime=ai_outlook.get("market_regime", "UNKNOWN"),
        directional_bias=ai_outlook.get("directional_bias", "UNKNOWN"),
        confidence=ai_outlook.get("confidence", 0),
        market_summary=ai_outlook.get("market_summary", ""),
        evidence_strength=ai_outlook.get("evidence_strength", 0),
        volatility_classification=ai_outlook.get("volatility_classification", ""),
        market_structure=_to_str(ai_outlook.get("market_structure", "")),
        no_trade_conditions=_to_str(ai_outlook.get("no_trade_conditions", "")),
        strategy_environment=_to_str(ai_outlook.get("strategy_environment", "")),
        invalidation=_to_str(ai_outlook.get("invalidation", "")),
    )
    logger.info(f"Saved outlook for {symbol} on {date_str} at {quote_price}")

def close_outlook(symbol: str, quote_price: float) -> None:
    db = _get_db()
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    db.save_history(symbol=symbol, date=date_str, locked_price=0, closed_price=quote_price)
    logger.info(f"Closed outlook for {symbol} on {date_str} at {quote_price}")

def get_history(symbol: str, days: int = 30) -> list[dict]:
    db = _get_db()
    return db.get_history(symbol, days)

def get_all_history(days: int = 30) -> dict[str, list[dict]]:
    db = _get_db()
    return db.get_all_history(days)

def archive_history(weekly: bool = True, monthly: bool = False) -> int:
    db = _get_db()
    return db.archive_history(weekly=weekly, monthly=monthly)