from __future__ import annotations

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

"""Historical AI Replay Engine.

Replays Phase 2 + Phase 3 + Phase 4 logic timestamp by timestamp
with strict no-lookahead: at time T, only uses data available at or before T.

Input: symbol, date, 5-minute candles up to that date
Output: list of ReplaySnapshot at each 5-minute step

Each snapshot preserves:
- timestamp (when this snapshot was taken)
- market_state (computed from candles ≤ T)
- gap (opening vs previous close)
- options_state (if available at T, else None)
- trade_setup (from detect_trade_setup)
- what_ai_knew (evidence summary)
- what_ai_did_not_know (uncertainty summary)

Key principle: NOTHING is overwritten. Every snapshot is immutable.
"""
import json
from typing import Any, Dict, List, Optional

from trade_lifecycle import TradeSetup, detect_trade_setup


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
    """Compute indicators using only candles ≤ current_time.

    Uses frozen indicators engine via indicators_versioned wrapper.
    """
    if not candles:
        return {}

    try:
        from indicators_versioned import calculate_all_indicators
        # Use last candle as quote
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
    """Compute gap using open price at current_time vs prev_close."""
    if not day_candles or prev_close is None or prev_close == 0:
        return None

    # Find the first candle of the current day (09:15 IST)
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


def replay_day(symbol: str, date: str, candles: list[dict],
               prev_close: Optional[float] = None,
               options_chain: Optional[list[dict]] = None,
               options_timestamp: Optional[str] = None) -> List[ReplaySnapshot]:
    """Replay a trading day with strict no-lookahead.

    Args:
        symbol: e.g. "NIFTY"
        date: date string, e.g. "2026-09-15"
        candles: ALL 5-minute candles for the day (sorted by timestamp)
        prev_close: Previous day's close (for gap calculation)
        options_chain: Option chain data available at start of day (or None)
        options_timestamp: When options data was fetched (or None)

    Returns:
        List of ReplaySnapshot at each 5-minute step, in chronological order.
        Each snapshot uses ONLY data available at that timestamp.
    """
    if not candles:
        return []

    snapshots: List[ReplaySnapshot] = []

    # Day candles for gap (only first candle matters)
    day_candles = [c for c in candles if c.get("timestamp", "")[:10] == date]

    for i, candle in enumerate(candles):
        ts = candle.get("timestamp", "")
        if not ts or not ts.startswith(date):
            continue

        # Use ONLY candles up to and including current timestamp
        available_candles = candles[:i + 1]

        # Compute market state from available candles
        indicators = _compute_indicators_at_time(available_candles, ts)

        # Get last candle's data as quote
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

        # Compute gap (only from opening candle, doesn't change intraday)
        gap = _compute_gap_at_time(day_candles, ts, prev_close)

        # Options state (if available)
        options_state = None
        if options_chain and options_timestamp and ts <= options_timestamp:
            try:
                from options_normalizer import build_options_state
                options_state = build_options_state(symbol, options_chain, spot)
                if options_state:
                    options_state = options_state.to_dict()
            except Exception:
                pass

        # Trade setup from market state + gap + options
        try:
            setup = detect_trade_setup(
                symbol=symbol,
                market_state=market_state,
                options_state=options_states_from_dict(options_state) if options_state else None,
                gap=gap,
                timestamp=ts,
                data_quality="LIVE" if spot else "DATA UNAVAILABLE",
            )
            setup_dict = setup.to_dict()
        except Exception:
            setup_dict = None

        # What AI knew vs didn't know
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


def options_state_from_dict(d: Optional[dict]) -> Optional[dict]:
    """Helper to pass options state dict through trade setup engine."""
    return d
