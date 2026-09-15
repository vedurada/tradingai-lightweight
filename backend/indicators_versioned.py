from __future__ import annotations

"""Versioned indicator engine wrapper around frozen indicators.py.

Since backend/indicators.py is a frozen model file, this module provides:
1. Direct re-export of all indicator functions (unchanged logic)
2. A versioned calculate_all_indicators that fixes the timestamp bug
3. Version tracking for audit purposes
"""
import datetime
import hashlib
import os
import sys
from typing import Any, Dict, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from indicators import (
    calculate_ema,
    calculate_vwap,
    calculate_pivot,
    calculate_cpr,
    calculate_bollinger_bands,
    calculate_rsi,
    calculate_macd,
    calculate_adx,
    calculate_atr,
    calculate_support_resistance,
)

INDICATOR_VERSION = "2.0.0-phase2"

INDICATOR_HASH = hashlib.sha256(
    open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "indicators.py")).read().encode()
).hexdigest()[:16]


def calculate_all_indicators(ohlcv: list[dict], quote: dict, candle_timestamp: Optional[str] = None) -> dict[str, Any]:
    """Versioned wrapper around frozen calculate_all_indicators.

    Fixes: timestamp uses candle_timestamp (look-ahead protection) instead of datetime.now().
    """
    result = calculate_all_indicators.__wrapped__(ohlcv, quote) if hasattr(calculate_all_indicators, "__wrapped__") else None

    from indicators import calculate_all_indicators as _raw
    result = _raw(ohlcv, quote)

    ts = candle_timestamp or quote.get("timestamp") or quote.get("date") or ""
    if ts:
        from data_normalizer import to_utc
        normalized = to_utc(str(ts))
        if normalized:
            result["timestamp"] = normalized
    else:
        from data_normalizer import now_ist_str
        result["timestamp"] = now_ist_str()

    result["indicator_version"] = INDICATOR_VERSION
    result["indicator_hash"] = INDICATOR_HASH
    return result


def get_indicator_version() -> Dict[str, Any]:
    """Return version info for this indicator engine."""
    return {
        "version": INDICATOR_VERSION,
        "hash": INDICATOR_HASH,
        "source": "backend/indicators.py (frozen)",
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
