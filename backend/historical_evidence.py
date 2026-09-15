from __future__ import annotations

import os
import sys
import sqlite3
from collections import namedtuple
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

SimilarityCondition = namedtuple("SimilarityCondition", [
    "regime",
    "gap_direction",
    "price_location",
    "vwap_position",
    "rsi_range_min", "rsi_range_max",
    "trade_readiness",
    "setup_type",
])

UnderlyingOutcome = namedtuple("UnderlyingOutcome", [
    "date",
    "open_to_close_pct",
    "high_to_low_pct",
    "subsequent_high_pct",
    "subsequent_low_pct",
    "subsequent_close_pct",
    "target_reached",
    "invalidation_reached",
    "subsequent_move_direction",
])

OptionsOutcome = namedtuple("OptionsOutcome", [
    "date",
    "has_option_data",
])

HistoricalEvidenceResult = namedtuple("HistoricalEvidenceResult", [
    "symbol",
    "query_date",
    "conditions",
    "match_count",
    "confirmed",
    "failed",
    "neutral",
    "confirmation_rate",
    "median_subsequent_move",
    "average_subsequent_move",
    "best_window",
    "underlying_outcomes",
    "options_outcomes",
    "option_data_available",
    "coverage",
    "insufficient_data",
    "message",
])


def _load_daily_candles(symbol: str, conn: sqlite3.Connection):
    rows = conn.execute(
        "SELECT timestamp, open, high, low, close, volume FROM price_1d "
        "WHERE symbol=? ORDER BY timestamp",
        (symbol,),
    ).fetchall()
    return [dict(r) for r in rows]


def _daily_gap(candle: dict, prev_candle: Optional[dict]) -> str:
    if prev_candle is None:
        return "NEUTRAL"
    prev_close = prev_candle["close"]
    curr_open = candle["open"]
    if prev_close == 0:
        return "NEUTRAL"
    gap_pct = (curr_open - prev_close) / prev_close
    if gap_pct > 0.003:
        return "UP"
    if gap_pct < -0.003:
        return "DOWN"
    return "NEUTRAL"


def _daily_regime(candle: dict, prev_candles: list) -> str:
    if len(prev_candles) < 2:
        return "UNKNOWN"
    closes = [c["close"] for c in prev_candles]
    returns = [(closes[i] - closes[i-1]) / closes[i-1] for i in range(1, len(closes))]
    if not returns:
        return "UNKNOWN"
    avg = sum(returns) / len(returns)
    highs = [c["high"] for c in prev_candles]
    lows = [c["low"] for c in prev_candles]
    atr = sum(max(h - l, abs(h - closes[-1]), abs(l - closes[-1])) for h, l in zip(highs, lows)) / max(1, len(prev_candles))
    if atr > 0.015:
        return "RANGING"
    if avg > 0.0003:
        return "TRENDING_UP"
    if avg < -0.0003:
        return "TRENDING_DOWN"
    return "RANGING"


def _daily_price_location(candle: dict, lookback_candles: list) -> str:
    if not lookback_candles:
        return "UNKNOWN"
    high = max(c["high"] for c in lookback_candles)
    low = min(c["low"] for c in lookback_candles)
    curr = candle["close"]
    range_size = high - low
    if range_size == 0:
        return "MID"
    pos = (curr - low) / range_size
    if pos > 0.85:
        return "NEAR_RESISTANCE"
    if pos < 0.15:
        return "NEAR_SUPPORT"
    return "MID"


def _daily_rsi(candles: list, idx: int, period: int = 14) -> float:
    start = max(0, idx - period)
    closes = [c["close"] for c in candles[start:idx + 1]]
    if len(closes) < period + 1:
        return 50.0
    gains = 0
    losses = 0
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i-1]
        if diff > 0:
            gains += diff
        else:
            losses += abs(diff)
    avg_gain = gains / period
    avg_loss = losses / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _generate_daily_conditions(candle: dict, prev_candles: list, idx: int) -> Dict[str, Any]:
    return {
        "regime": _daily_regime(candle, prev_candles),
        "gap_direction": _daily_gap(candle, prev_candles[-1] if prev_candles else None),
        "price_location": _daily_price_location(candle, prev_candles),
        "rsi": round(_daily_rsi(prev_candles + [candle], idx) if idx > 0 else 50.0),
        "vwap_position": "UNKNOWN",
        "trade_readiness": "UNKNOWN",
    }


def _matches(condition: Dict[str, Any], criteria: SimilarityCondition) -> bool:
    regime_map = {
        "TRENDING": ["TRENDING_UP", "TRENDING_DOWN"],
    }
    if criteria.regime and criteria.regime != "ANY":
        cond_regime = condition.get("regime", "")
        if criteria.regime in regime_map:
            if cond_regime not in regime_map[criteria.regime]:
                return False
        else:
            if cond_regime != criteria.regime:
                return False
    if criteria.gap_direction and criteria.gap_direction != "ANY":
        if condition.get("gap_direction") != criteria.gap_direction:
            return False
    if criteria.price_location and criteria.price_location != "ANY":
        if condition.get("price_location") != criteria.price_location:
            return False
    if criteria.vwap_position and criteria.vwap_position != "ANY":
        if condition.get("vwap_position") != criteria.vwap_position:
            return False
    if criteria.rsi_range_min is not None or criteria.rsi_range_max is not None:
        rsi = condition.get("rsi", 50)
        rmin = criteria.rsi_range_min if criteria.rsi_range_min is not None else 0
        rmax = criteria.rsi_range_max if criteria.rsi_range_max is not None else 100
        if not (rmin <= rsi <= rmax):
            return False
    return True


def run_historical_evidence(
    symbol: str,
    query_date: str,
    conditions: SimilarityCondition,
    db_path: Optional[str] = None,
) -> HistoricalEvidenceResult:
    if db_path is None:
        db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "database", "tradingai.db")

    if not os.path.exists(db_path):
        return HistoricalEvidenceResult(
            symbol=symbol, query_date=query_date[:10],
            conditions=conditions._asdict(), match_count=0, confirmed=0, failed=0, neutral=0,
            confirmation_rate=0, median_subsequent_move=None, average_subsequent_move=None,
            best_window=None, underlying_outcomes=[], options_outcomes=[],
            option_data_available=False, coverage={}, insufficient_data=True,
            message="DB not found",
        )

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    candles = _load_daily_candles(symbol, conn)
    if not candles:
        conn.close()
        return HistoricalEvidenceResult(
            symbol=symbol, query_date=query_date[:10],
            conditions=conditions._asdict(), match_count=0, confirmed=0, failed=0, neutral=0,
            confirmation_rate=0, median_subsequent_move=None, average_subsequent_move=None,
            best_window=None, underlying_outcomes=[], options_outcomes=[],
            option_data_available=False, coverage={}, insufficient_data=True,
            message="INSUFFICIENT_HISTORICAL_DATA: no daily price data for symbol",
        )

    earliest = candles[0]["timestamp"][:10]
    latest = candles[-1]["timestamp"][:10]
    coverage = {
        "symbol": symbol,
        "earliest": earliest,
        "latest": latest,
        "total_days": len(candles),
    }

    qdate = query_date[:10]
    q_idx = None
    for i, c in enumerate(candles):
        if c["timestamp"][:10] == qdate:
            q_idx = i
            break

    if q_idx is None:
        conn.close()
        return HistoricalEvidenceResult(
            symbol=symbol, query_date=qdate,
            conditions=conditions._asdict(), match_count=0, confirmed=0, failed=0, neutral=0,
            confirmation_rate=0, median_subsequent_move=None, average_subsequent_move=None,
            best_window=None, underlying_outcomes=[], options_outcomes=[],
            option_data_available=False, coverage=coverage, insufficient_data=True,
            message=f"INSUFFICIENT_HISTORICAL_DATA: no data for {qdate}",
        )

    query_cond = _generate_daily_conditions(candles[q_idx], candles[:q_idx], q_idx)

    match_indices = []
    for i, candle in enumerate(candles):
        day = candle["timestamp"][:10]
        if day == qdate:
            continue
        cond = _generate_daily_conditions(candle, candles[:i], i)
        if _matches(cond, conditions):
            match_indices.append(i)

    if not match_indices:
        conn.close()
        return HistoricalEvidenceResult(
            symbol=symbol, query_date=qdate,
            conditions={**conditions._asdict(), **query_cond},
            match_count=0, confirmed=0, failed=0, neutral=0,
            confirmation_rate=0, median_subsequent_move=None, average_subsequent_move=None,
            best_window=None, underlying_outcomes=[], options_outcomes=[],
            option_data_available=False, coverage=coverage, insufficient_data=False,
            message=f"No historical matches found for {symbol} on {qdate}",
        )

    outcomes = []
    for idx in match_indices:
        candle = candles[idx]
        entry_close = candle["close"]
        high = candle["high"]
        low = candle["low"]
        day_pct = ((candle["close"] - candle["open"]) / candle["open"] * 100) if candle["open"] else 0
        hl_pct = ((high - low) / (low or 1)) * 100

        future_candles = [c for c in candles[idx + 1:] if c["timestamp"][:10] > candle["timestamp"][:10]]
        subsequent_moves = []
        target_reached = False
        invalidation_reached = False
        for fc in future_candles[:5]:
            subsequent_pct = ((fc["close"] - entry_close) / entry_close * 100) if entry_close else 0
            subsequent_moves.append(subsequent_pct)
            if fc["high"] > entry_close * 1.01:
                target_reached = True
            if fc["low"] < entry_close * 0.99:
                invalidation_reached = True

        final_pct = subsequent_moves[-1] if subsequent_moves else 0
        direction = "UP" if final_pct > 0 else ("DOWN" if final_pct < 0 else "FLAT")

        outcomes.append(UnderlyingOutcome(
            date=candle["timestamp"][:10],
            open_to_close_pct=round(day_pct, 2),
            high_to_low_pct=round(hl_pct, 2),
            subsequent_high_pct=round(max(subsequent_moves) if subsequent_moves else 0, 2),
            subsequent_low_pct=round(min(subsequent_moves) if subsequent_moves else 0, 2),
            subsequent_close_pct=round(final_pct, 2),
            target_reached=target_reached,
            invalidation_reached=invalidation_reached,
            subsequent_move_direction=direction,
        ))

    confirmed = sum(1 for o in outcomes if o.subsequent_close_pct > 0)
    failed = sum(1 for o in outcomes if o.subsequent_close_pct <= 0)
    neutral = sum(1 for o in outcomes if o.subsequent_close_pct == 0)
    match_count = len(outcomes)
    confirmation_rate = round(confirmed / match_count * 100, 1) if match_count > 0 else 0

    pct_moves = [o.subsequent_close_pct for o in outcomes]
    sorted_pcts = sorted(pct_moves)
    n = len(sorted_pcts)
    median_move = sorted_pcts[n // 2] if n % 2 == 1 else (sorted_pcts[n // 2 - 1] + sorted_pcts[n // 2]) / 2
    avg_move = sum(pct_moves) / n if n > 0 else 0

    option_data_available = False
    options_outcomes = []
    try:
        opt_count = conn.execute("SELECT COUNT(*) FROM option_chain WHERE symbol=?", (symbol,)).fetchone()[0]
        if opt_count > 0:
            option_data_available = True
    except Exception:
        pass

    best_window = None
    if outcomes:
        best = max(outcomes, key=lambda o: o.subsequent_close_pct)
        best_window = f"{best.date} 09:30 - 15:30"

    conn.close()

    return HistoricalEvidenceResult(
        symbol=symbol,
        query_date=qdate,
        conditions={**conditions._asdict(), **query_cond},
        match_count=match_count,
        confirmed=confirmed,
        failed=failed,
        neutral=neutral,
        confirmation_rate=confirmation_rate,
        median_subsequent_move=round(median_move, 2),
        average_subsequent_move=round(avg_move, 2),
        best_window=best_window,
        underlying_outcomes=outcomes,
        options_outcomes=options_outcomes,
        option_data_available=option_data_available,
        coverage=coverage,
        insufficient_data=False,
        message=f"Found {match_count} matching sessions for {symbol}",
    )
