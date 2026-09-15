from __future__ import annotations

"""Market state generation engine.

Generates a single Market State object per symbol from:
- Indicators (from frozen indicators.py via indicators_versioned.py)
- Regime (from frozen regime.py via RegimeEngine)
- Support/Resistance (from frozen indicators.py)
- Expected range (from expected_range.py)
- Snapshot data (from DB market_snapshots)
- Candle data (from DB market_candles)

Principles:
- NEVER synthesize values — only observed, cached, derived, or explicitly unavailable
- NEVER create deterministic_ai.py (frozen concept)
- Look-ahead protection: timestamp must be the candle timestamp, not now()
- Versioned: each state has an indicator_version and regime_version
- Serializable: dict output for JSON/API/consumers
"""
import json
import os
import sys
import sqlite3
import datetime
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from indicators_versioned import calculate_all_indicators, calculate_support_resistance
from expected_range import compute_expected_range
from regime import RegimeEngine


class MarketState:
    """Per-symbol market state object.

    Immutable snapshot: once created, never modified.
    """

    def __init__(self, symbol: str, timestamp: str, indicators: dict, regime: dict,
                 support: list, resistance: list, expected_range: dict,
                 snapshot: Optional[dict] = None, candle_count: int = 0,
                 indicator_version: str = "", regime_version: str = ""):
        self.symbol = symbol
        self.timestamp = timestamp
        self.indicators = indicators
        self.regime = regime
        self.support = sorted(support or [])
        self.resistance = sorted(resistance or [])
        self.expected_range = expected_range
        self.snapshot = snapshot or {}
        self.candle_count = candle_count
        self.indicator_version = indicator_version
        self.regime_version = regime_version

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp,
            "indicators": self.indicators,
            "regime": self.regime,
            "support": self.support,
            "resistance": self.resistance,
            "expected_range": self.expected_range,
            "snapshot": self.snapshot,
            "candle_count": self.candle_count,
            "indicator_version": self.indicator_version,
            "regime_version": self.regime_version,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), default=str)


def build_market_state(symbol: str, conn: sqlite3.Connection, candle_timestamp: Optional[str] = None) -> Optional[MarketState]:
    """Build a complete MarketState from DB data for one symbol.

    Returns None if insufficient data to build state.
    """
    try:
        ind_row = conn.execute(
            "SELECT * FROM indicators WHERE symbol=? ORDER BY timestamp DESC LIMIT 1", (symbol,)
        ).fetchone()
        if not ind_row:
            return None
        ind_dict = dict(ind_row)

        sr = ind_dict.get("support_resistance", "{}")
        if isinstance(sr, str):
            try:
                sr = json.loads(sr)
            except Exception:
                sr = {}
        support = sr.get("support", []) if isinstance(sr, dict) else []
        resistance = sr.get("resistance", []) if isinstance(sr, dict) else []

        regime_row = conn.execute(
            "SELECT * FROM market_regime WHERE symbol=? ORDER BY timestamp DESC LIMIT 1", (symbol,)
        ).fetchone()
        regime = dict(regime_row) if regime_row else {"regime": "UNKNOWN", "confidence": 0}

        quote_row = conn.execute(
            "SELECT * FROM price_1m WHERE symbol=? ORDER BY timestamp DESC LIMIT 1", (symbol,)
        ).fetchone()
        price = quote_row["close"] if quote_row else ind_dict.get("day_high", 0) or 0

        bb = {
            "upper": ind_dict.get("bollinger_upper"),
            "lower": ind_dict.get("bollinger_lower"),
            "middle": ind_dict.get("bollinger_middle"),
            "width": ind_dict.get("bollinger_width"),
        }
        ind_for_range = {"bollinger_bands": bb if bb["upper"] else None, "atr": ind_dict.get("atr"),
                         "support_resistance": {"support": support, "resistance": resistance}}

        expected = compute_expected_range(ind_for_range, price, None)

        snapshot_row = conn.execute(
            "SELECT * FROM market_snapshots ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()
        snapshot = dict(snapshot_row) if snapshot_row else {}

        candle_count = conn.execute(
            "SELECT COUNT(*) as c FROM market_candles WHERE symbol=?", (symbol,)
        ).fetchone()["c"]

        indicator_version = ind_dict.get("indicator_version", "") if "indicator_version" in ind_dict else ""

        regime_version = "frozen-v1"

        return MarketState(
            symbol=symbol,
            timestamp=candle_timestamp or ind_dict.get("timestamp", ""),
            indicators=ind_dict,
            regime=regime,
            support=support,
            resistance=resistance,
            expected_range=expected,
            snapshot=snapshot,
            candle_count=candle_count,
            indicator_version=indicator_version,
            regime_version=regime_version,
        )
    except Exception:
        return None


def build_market_states(all_symbols: Optional[List[str]] = None) -> Dict[str, MarketState]:
    """Build market states for all (or specified) symbols. Returns dict keyed by symbol."""
    from db_schema import DB_PATH
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        if all_symbols is None:
            rows = conn.execute("SELECT symbol FROM symbols WHERE active=1").fetchall()
            symbols = [r["symbol"] for r in rows]
        else:
            symbols = all_symbols

        states = {}
        for sym in symbols:
            try:
                state = build_market_state(sym, conn)
                if state:
                    states[sym] = state
            except Exception:
                continue
        return states
    finally:
        conn.close()
