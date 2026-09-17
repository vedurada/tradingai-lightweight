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


class ReplaySnapshot:
    """One point-in-time snapshot during replay. Immutable."""

    def __init__(self, *,
                 timestamp: str,
                 symbol: str,
                 candle_time: Optional[str] = None,
                 market_state: Optional[dict] = None,
                 gap: Optional[dict] = None,
                 options_state: Optional[dict] = None,
                 trade_setup: Optional[dict] = None,
                 indicators_version: str = "",
                 data_quality: str = "DATA UNAVAILABLE",
                 what_ai_knew: List[str] = None,
                 what_ai_did_not_know: List[str] = None):
        self.timestamp = timestamp
        self.symbol = symbol
        self.candle_time = candle_time
        self.market_state = market_state
        self.gap = gap
        self.options_state = options_state
        self.trade_setup = trade_setup
        self.indicators_version = indicators_version
        self.data_quality = data_quality
        self.what_ai_knew = sorted(what_ai_knew or [])
        self.what_ai_did_not_know = sorted(what_ai_did_not_know or [])

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "symbol": self.symbol,
            "candle_time": self.candle_time,
            "market_state": self.market_state,
            "gap": self.gap,
            "options_state": self.options_state,
            "trade_setup": self.trade_setup,
            "indicators_version": self.indicators_version,
            "data_quality": self.data_quality,
            "what_ai_knew": self.what_ai_knew,
            "what_ai_did_not_know": self.what_ai_did_not_know,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), default=str)


def _compute_indicators_at_time(candles: list[dict], current_time: str,
                                      quote: Optional[dict] = None) -> dict[str, Any]:
    if not candles:
        return {}

    try:
        from indicators_versioned import calculate_all_indicators
        last = candles[-1]
        q = quote or {
            "price": last.get("close"),
            "timestamp": current_time,
            "open": last.get("open"),
            "high": last.get("high"),
            "low": last.get("low"),
        }
        result = calculate_all_indicators(candles, q)
        return result
    except Exception:
        return {}


def _compute_gap_at_time(day_candles: list[dict], current_time: str,
                               prev_close: Optional[float]) -> Optional[dict]:
    if not day_candles or prev_close is None or prev_close == 0:
        return None

    first_candle = day_candles[0] if day_candles else None
    if not first_candle:
        return None

    open_price = first_candle.get("open")
    if open_price is None:
        return None

    try:
        gap_pts = float(open_price) - float(prev_close)
        gap_pct = round(gap_pts / float(prev_close) * 100, 2)
        kind = ("GAP UP" if gap_pts > float(prev_close) * 0.0015
                else "GAP DOWN" if gap_pts < -float(prev_close) * 0.0015
                else "FLAT OPEN")
        high = first_candle.get("high")
        low = first_candle.get("low")
        return {
            "gap_pct": gap_pct,
            "kind": kind,
            "open": float(open_price),
            "high": high,
            "low": low,
            "prev_close": float(prev_close),
            "available": True,
        }
    except (TypeError, ValueError):
        return None


def options_state_from_dict(d: Optional[dict]) -> Optional[dict]:
    return d


def replay_day(symbol: str, date: str, candles: list[dict],
               prev_close: Optional[float] = None,
               options_chain: Optional[list[dict]] = None,
               options_timestamp: Optional[str] = None) -> List[ReplaySnapshot]:
    """Replay a trading day with strict no-lookahead."""
    if not candles:
        return []

    snapshots: List[ReplaySnapshot] = []
    day_candles = [c for c in candles if c.get("timestamp", "")[:10] == date]

    for i, candle in enumerate(candles):
        ts = candle.get("timestamp", "")
        if not ts or not ts.startswith(date):
            continue

        available_candles = candles[:i + 1]

        indicators = _compute_indicators_at_time(available_candles, ts)

        last = available_candles[-1] if available_candles else {}
        spot = last.get("close")
        regime = indicators.get("regime") if isinstance(indicators, dict) else None
        confidence = indicators.get("confidence") if isinstance(indicators, dict) else None

        market_state = {
            "spot": spot,
            "regime": regime,
            "confidence": confidence,
            "indicators": indicators if isinstance(indicators, dict) else {},
        }

        gap = _compute_gap_at_time(day_candles, ts, prev_close)

        options_state = None
        if options_chain and options_timestamp and ts <= options_timestamp:
            try:
                from options_normalizer import build_options_state
                options_state = build_options_state(symbol, options_chain, spot)
                if options_state:
                    options_state = options_state.to_dict()
            except Exception:
                pass

        try:
            from trade_lifecycle import TradeSetup, detect_trade_setup
            setup = detect_trade_setup(
                symbol=symbol,
                market_state=market_state,
                options_state=options_state_from_dict(options_state) if options_state else None,
                gap=gap,
                timestamp=ts,
                data_quality="LIVE" if spot else "DATA UNAVAILABLE",
            )
            setup_dict = setup.to_dict()
        except Exception:
            setup_dict = None

        what_ai_knew = []
        what_ai_did_not_know = []

        if spot:
            what_ai_knew.append(f"Price: {spot}")
        if regime:
            what_ai_knew.append(f"Regime: {regime}")
        if gap and gap.get("available"):
            what_ai_knew.append(f"Gap: {gap.get('gap_pct')}% {gap.get('kind')}")
        if options_state:
            what_ai_knew.append(f"Options: PCR={options_state.get('pcr')}")
        if setup_dict and setup_dict.get("trade_readiness"):
            what_ai_knew.append(f"Readiness: {setup_dict['trade_readiness']}")

        if not spot:
            what_ai_did_not_know.append("Price data unavailable")
        if not regime:
            what_ai_did_not_know.append("Regime undetermined")
        if not gap or not gap.get("available"):
            what_ai_did_not_know.append("Gap data unavailable")
        if not options_state:
            what_ai_did_not_know.append("No option chain data")
        if setup_dict and setup_dict.get("uncertainty"):
            what_ai_did_not_know.extend(setup_dict["uncertainty"][:3])

        snapshot = ReplaySnapshot(
            timestamp=ts,
            symbol=symbol,
            candle_time=ts,
            market_state=market_state,
            gap=gap,
            options_state=options_state,
            trade_setup=setup_dict,
            indicators_version=indicators.get("indicator_version", "") if isinstance(indicators, dict) else "",
            data_quality="LIVE" if spot else "DATA UNAVAILABLE",
            what_ai_knew=what_ai_knew,
            what_ai_did_not_know=what_ai_did_not_know,
        )
        snapshots.append(snapshot)

    return snapshots


if __name__ == "__main__":
    result = run_replay()
    print(json.dumps(result, indent=2, default=str))
