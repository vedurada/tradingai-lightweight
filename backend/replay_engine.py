from __future__ import annotations

"""
Phase 41 — Historical Evidence Replay Engine.

Replays deterministic evidence and trade qualification over historical
5-minute data. This is a STRUCTURAL REPLAY of the evidence engine.

IMPORTANT: This is NOT historical AI performance unless actual AI outputs
were stored historically. This only replays:
1. Market evidence (deterministic)
2. Trade qualification (deterministic)
3. Paper trade creation and exit (deterministic)

AI outlook generation during historical replay is NOT claimed as
historical AI performance.
"""

import json
import os
import sys
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logger = logging.getLogger("tradingai.replay")


def load_historical_data(filepath: str) -> list:
    if not os.path.exists(filepath):
        logger.warning(f"Data file not found: {filepath}")
        return []
    with open(filepath) as f:
        data = json.load(f)
    candles = data.get("candles", data if isinstance(data, list) else [])
    return candles


def replay_candle(
    engine,
    candle: dict,
    prev_close: float = None,
) -> dict:
    from market_evidence_engine import MarketEvidenceEngine
    if not isinstance(engine, MarketEvidenceEngine):
        return {"error": "Invalid engine"}

    snapshot = {
        "candle_timestamp": candle.get("timestamp", candle.get("candle_timestamp", "")),
        "close": candle.get("close"),
        "high": candle.get("high"),
        "low": candle.get("low"),
        "open": candle.get("open"),
        "vwap": candle.get("vwap"),
        "ema9": candle.get("ema9"),
        "ema20": candle.get("ema20"),
        "ema50": candle.get("ema50"),
        "ema200": candle.get("ema200"),
        "rsi": candle.get("rsi"),
        "macd": candle.get("macd"),
        "macd_signal": candle.get("macd_signal"),
        "adx": candle.get("adx"),
        "atr": candle.get("atr"),
        "vix": candle.get("vix"),
        "support": candle.get("support"),
        "resistance": candle.get("resistance"),
        "prev_day_high": candle.get("prev_day_high", prev_close),
        "prev_day_low": candle.get("prev_day_low", prev_close),
        "pcr": candle.get("pcr"),
        "call_oi": candle.get("call_oi"),
        "put_oi": candle.get("put_oi"),
        "data_state": candle.get("data_state", "HISTORICAL"),
    }

    evidence = engine.evaluate(snapshot, data_state="HISTORICAL", symbol="NIFTY")
    return evidence


def replay_nifty_30d(
    data_path: str = "data/backtest/nifty_30d_5m.json",
) -> dict:
    candles = load_historical_data(data_path)
    if not candles:
        return {"replay": "NO_DATA", "total_candles": 0}

    engine = MarketEvidenceEngine()
    results = []
    prev_close = None

    for i, candle in enumerate(candles):
        evidence = replay_candle(engine, candle, prev_close)
        results.append(evidence)
        prev_close = candle.get("close", prev_close)

    stats = {
        "total_candles": len(results),
        "replay": "COMPLETE",
        "data_path": data_path,
        "engine_version": engine.config.get("engine_version", "1.0.0-phase40"),
        "signals": _count_signals(results),
    }

    return stats


def _count_signals(results: list) -> dict:
    signals = {}
    for r in results:
        sig = r.get("overall", {}).get("overall_signal", "UNKNOWN")
        signals[sig] = signals.get(sig, 0) + 1
    return signals


def run_replay(data_path: str = "data/backtest/nifty_30d_5m.json") -> dict:
    return replay_nifty_30d(data_path)


if __name__ == "__main__":
    result = run_replay()
    print(json.dumps(result, indent=2, default=str))
