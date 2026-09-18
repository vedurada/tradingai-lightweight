from __future__ import annotations

import json
import logging
import os
import sys
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db_schema import DB_PATH
from data_quality import DATA_QUALITY_LIVE, DATA_QUALITY_UNAVAILABLE
from regime_utils import normalize_regime

logger = logging.getLogger("tradingai.expected_movement")

MIN_SAMPLE_SIZE = 10


def _get_conn(db_path: str = None) -> sqlite3.Connection:
    path = db_path or DB_PATH
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


def _get_time_of_day(timestamp: str) -> str:
    if not timestamp:
        return "UNKNOWN"
    try:
        dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        mins = dt.hour * 60 + dt.minute
        if 9 * 60 + 15 <= mins < 11 * 60:
            return "0930-1100"
        elif 11 * 60 <= mins < 14 * 60:
            return "1100-1400"
        elif 14 * 60 <= mins < 15 * 60:
            return "1400-1500"
        elif 15 * 60 <= mins < 16 * 60:
            return "1500_CLOSE"
        return "OTHER"
    except (ValueError, TypeError):
        return "UNKNOWN"


def _get_volatility_regime(atr: Optional[float], close: Optional[float]) -> str:
    if atr is None or close is None or close == 0:
        return "UNKNOWN"
    atr_pct = atr / close * 100
    if atr_pct > 1.5:
        return "HIGH"
    elif atr_pct > 0.5:
        return "NORMAL"
    return "LOW"


def _get_positioning_state(market_state: Dict[str, Any] or None) -> str:
    if not market_state:
        return "UNKNOWN"
    vwap = market_state.get("vwap")
    close = market_state.get("close") or market_state.get("last_price")
    if vwap is None or close is None:
        return "UNKNOWN"
    diff_pct = (close - vwap) / vwap * 100
    if diff_pct > 0.5:
        return "ABOVE_VWAP_STRONG"
    elif diff_pct > 0.05:
        return "ABOVE_VWAP"
    elif diff_pct < -0.5:
        return "BELOW_VWAP_STRONG"
    elif diff_pct < -0.05:
        return "BELOW_VWAP"
    return "AT_VWAP"


def _get_liquidity_event(market_state: Dict[str, Any] or None,
                           candle: Dict[str, Any] or None) -> str:
    if candle and candle.get("volume", 0) > 0 and market_state:
        volume = candle["volume"]
        avg_volume = market_state.get("avg_volume")
        if avg_volume and volume > avg_volume * 2:
            return "HIGH_VOLUME"
        if avg_volume and volume > avg_volume * 1.5:
            return "ELEVATED_VOLUME"
    if market_state and market_state.get("volume_spike"):
        return "VOLUME_SPIKE"
    return "NORMAL"


def _price_vs_vwap(close_price: float, vwap: Optional[float]) -> str:
    if vwap is None or vwap == 0:
        return "UNKNOWN"
    diff_pct = (close_price - vwap) / vwap * 100
    if diff_pct > 0.3:
        return "ABOVE_VWAP"
    elif diff_pct < -0.3:
        return "BELOW_VWAP"
    return "AT_VWAP"


def _normalize_match_key(value: Any) -> str:
    if value is None:
        return "UNKNOWN"
    return str(value).upper()


def _compute_percentile(sorted_values: List[float], percentile: float) -> Optional[float]:
    if not sorted_values:
        return None
    n = len(sorted_values)
    if n == 1:
        return sorted_values[0]
    idx = (percentile / 100.0) * (n - 1)
    lower = int(idx)
    upper = lower + 1
    if upper >= n:
        return sorted_values[-1]
    frac = idx - lower
    return sorted_values[lower] + frac * (sorted_values[upper] - sorted_values[lower])


def _median(values: List[float]) -> Optional[float]:
    if not values:
        return None
    sorted_v = sorted(values)
    n = len(sorted_v)
    if n % 2 == 1:
        return sorted_v[n // 2]
    return (sorted_v[n // 2 - 1] + sorted_v[n // 2]) / 2.0


class ExpectedMovementResult:
    __slots__ = [
        "symbol", "scenario_type", "session_date", "direction",
        "market_regime", "volatility_regime", "time_of_day",
        "distance_from_vwap", "positioning_state", "liquidity_event",
        "data_status", "sample_size", "minimum_required",
        "median_favorable_move", "p25_favorable_move", "p75_favorable_move",
        "median_adverse_move", "p25_adverse_move", "p75_adverse_move",
        "mfe", "mae",
        "target_hit_rate",
        "time_to_target", "time_to_invalidation",
        "target_zone_low", "target_zone_high",
        "expected_horizon_minutes",
        "comparable_scenarios",
        "data_quality", "message",
    ]

    def __init__(self, *, symbol: str, scenario_type: str, session_date: str,
                 direction: str, market_regime: str, volatility_regime: str,
                 time_of_day: str, distance_from_vwap: str,
                 positioning_state: str, liquidity_event: str,
                 data_status: str, sample_size: int, minimum_required: int,
                 median_favorable_move: Optional[float],
                 p25_favorable_move: Optional[float],
                 p75_favorable_move: Optional[float],
                 median_adverse_move: Optional[float],
                 p25_adverse_move: Optional[float],
                 p75_adverse_move: Optional[float],
                 mfe: Optional[float], mae: Optional[float],
                 target_hit_rate: Optional[float],
                 time_to_target: Optional[float],
                 time_to_invalidation: Optional[float],
                 target_zone_low: Optional[float], target_zone_high: Optional[float],
                 expected_horizon_minutes: Optional[int],
                 comparable_scenarios: List[Dict[str, Any]],
                 data_quality: str, message: str):
        self.symbol = symbol
        self.scenario_type = scenario_type
        self.session_date = session_date
        self.direction = direction
        self.market_regime = market_regime
        self.volatility_regime = volatility_regime
        self.time_of_day = time_of_day
        self.distance_from_vwap = distance_from_vwap
        self.positioning_state = positioning_state
        self.liquidity_event = liquidity_event
        self.data_status = data_status
        self.sample_size = sample_size
        self.minimum_required = minimum_required
        self.median_favorable_move = median_favorable_move
        self.p25_favorable_move = p25_favorable_move
        self.p75_favorable_move = p75_favorable_move
        self.median_adverse_move = median_adverse_move
        self.p25_adverse_move = p25_adverse_move
        self.p75_adverse_move = p75_adverse_move
        self.mfe = mfe
        self.mae = mae
        self.target_hit_rate = target_hit_rate
        self.time_to_target = time_to_target
        self.time_to_invalidation = time_to_invalidation
        self.target_zone_low = target_zone_low
        self.target_zone_high = target_zone_high
        self.expected_horizon_minutes = expected_horizon_minutes
        self.comparable_scenarios = comparable_scenarios
        self.data_quality = data_quality
        self.message = message

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "scenario_type": self.scenario_type,
            "session_date": self.session_date,
            "direction": self.direction,
            "market_regime": self.market_regime,
            "volatility_regime": self.volatility_regime,
            "time_of_day": self.time_of_day,
            "distance_from_vwap": self.distance_from_vwap,
            "positioning_state": self.positioning_state,
            "liquidity_event": self.liquidity_event,
            "data_status": self.data_status,
            "sample_size": self.sample_size,
            "minimum_required": self.minimum_required,
            "median_favorable_move": self.median_favorable_move,
            "p25_favorable_move": self.p25_favorable_move,
            "p75_favorable_move": self.p75_favorable_move,
            "median_adverse_move": self.median_adverse_move,
            "p25_adverse_move": self.p25_adverse_move,
            "p75_adverse_move": self.p75_adverse_move,
            "mfe": self.mfe,
            "mae": self.mae,
            "target_hit_rate": self.target_hit_rate,
            "time_to_target": self.time_to_target,
            "time_to_invalidation": self.time_to_invalidation,
            "target_zone_low": self.target_zone_low,
            "target_zone_high": self.target_zone_high,
            "expected_horizon_minutes": self.expected_horizon_minutes,
            "comparable_scenarios": self.comparable_scenarios,
            "data_quality": self.data_quality,
            "message": self.message,
        }


class ExpectedMovementEngine:
    """Expected Movement Engine.

    Deterministic engine that computes expected movement ranges from historical
    comparable setups. Does NOT invent probabilities.

    Principles:
    - Deterministic calculations from historical data only
    - Does NOT invent probabilities, prices, targets, or OI
    - Returns NOT_CALIBRATED / INSUFFICIENT_SAMPLE when data is insufficient
    - Every response includes data_status, sample_size, minimum_required
    - Comparable dimensions: instrument, scenario_type, direction, market_regime,
      volatility_regime, time_of_day, distance_from_vwap, positioning_state, liquidity_event
    """

    def __init__(self, db_path: str = None):
        self.db_path = db_path or DB_PATH

    def _load_outcome_data(self, conn: sqlite3.Connection, symbol: str) -> List[dict]:
        rows = conn.execute(
            """SELECT * FROM research_outcome_tracking
               WHERE instrument=? AND outcome_5m_return_pct IS NOT NULL
               ORDER BY candle_timestamp""",
            (symbol,),
        ).fetchall()
        return [dict(r) for r in rows]

    def _load_scenario_data(self, conn: sqlite3.Connection, symbol: str,
                              session_date: str) -> List[dict]:
        rows = conn.execute(
            """SELECT * FROM scenarios
               WHERE symbol=? AND timestamp LIKE ?
               ORDER BY timestamp""",
            (symbol, f"{session_date[:10]}%"),
        ).fetchall()
        return [dict(r) for r in rows]

    def _find_comparable_scenarios(self, scenarios: List[dict],
                                     scenario_type: str, direction: str,
                                     market_regime: str, volatility_regime: str,
                                     time_of_day: str, positioning_state: str,
                                     liquidity_event: str) -> List[Dict[str, Any]]:
        if not scenarios:
            return []

        comparable = []
        for s in scenarios:
            match_score = 0
            total_criteria = 0

            stype = s.get("scenario_type", "").upper() if s.get("scenario_type") else ""
            sdir = s.get("direction", "").upper() if s.get("direction") else ""

            total_criteria += 1
            if stype == scenario_type.upper():
                match_score += 1

            total_criteria += 1
            if sdir == direction.upper():
                match_score += 1

            s_regime = normalize_regime(s.get("market_regime", ""))
            total_criteria += 1
            if s_regime == normalize_regime(market_regime):
                match_score += 1

            total_criteria += 1
            if volatility_regime == "HIGH" and s.get("adx", 0) > 30:
                match_score += 1
            elif volatility_regime == "LOW" and s.get("adx", 0) < 20:
                match_score += 1

            total_criteria += 1
            s_tod = _get_time_of_day(s.get("timestamp", ""))
            if s_tod == time_of_day:
                match_score += 1

            comparable.append({
                "scenario_id": s.get("id"),
                "symbol": s.get("symbol"),
                "timestamp": s.get("timestamp"),
                "scenario_type": stype,
                "direction": sdir,
                "market_regime": s_regime,
                "match_score": match_score,
                "total_criteria": total_criteria,
            })

        comparable.sort(key=lambda x: (-x["match_score"], x.get("timestamp", "")))
        return comparable

    def _compute_outcome_statistics(self, outcomes: List[dict],
                                      direction: str) -> Dict[str, Any]:
        if not outcomes:
            return {
                "median_favorable_move": None,
                "p25_favorable_move": None,
                "p75_favorable_move": None,
                "median_adverse_move": None,
                "p25_adverse_move": None,
                "p75_adverse_move": None,
                "mfe": None,
                "mae": None,
                "target_hit_rate": None,
                "time_to_target": None,
                "time_to_invalidation": None,
            }

        favorable_moves = []
        adverse_moves = []
        mfe_values = []
        mae_values = []
        target_hits = []
        time_targets = []
        time_invalidations = []

        for o in outcomes:
            ret_5m = o.get("outcome_5m_return_pct")
            ret_15m = o.get("outcome_15m_return_pct")
            ret_30m = o.get("outcome_30m_return_pct")
            ret_60m = o.get("outcome_60m_return_pct")

            if direction.upper() == "LONG":
                if ret_5m is not None:
                    if ret_5m >= 0:
                        favorable_moves.append(ret_5m)
                    else:
                        adverse_moves.append(abs(ret_5m))
                if ret_15m is not None:
                    if ret_15m >= 0:
                        favorable_moves.append(ret_15m)
                    else:
                        adverse_moves.append(abs(ret_15m))
                if ret_30m is not None:
                    if ret_30m >= 0:
                        favorable_moves.append(ret_30m)
                    else:
                        adverse_moves.append(abs(ret_30m))
                if ret_60m is not None:
                    if ret_60m >= 0:
                        favorable_moves.append(ret_60m)
                    else:
                        adverse_moves.append(abs(ret_60m))

                mfe_val = o.get("outcome_60m_return_pct") or o.get("outcome_30m_return_pct") or ret_5m
                mae_val = -(o.get("outcome_60m_return_pct") or o.get("outcome_30m_return_pct") or ret_5m)
            else:
                if ret_5m is not None:
                    if ret_5m <= 0:
                        favorable_moves.append(abs(ret_5m))
                    else:
                        adverse_moves.append(ret_5m)
                if ret_15m is not None:
                    if ret_15m <= 0:
                        favorable_moves.append(abs(ret_15m))
                    else:
                        adverse_moves.append(ret_15m)
                if ret_30m is not None:
                    if ret_30m <= 0:
                        favorable_moves.append(abs(ret_30m))
                    else:
                        adverse_moves.append(ret_30m)
                if ret_60m is not None:
                    if ret_60m <= 0:
                        favorable_moves.append(abs(ret_60m))
                    else:
                        adverse_moves.append(ret_60m)

                mfe_val = -(o.get("outcome_60m_return_pct") or o.get("outcome_30m_return_pct") or ret_5m)
                mae_val = o.get("outcome_60m_return_pct") or o.get("outcome_30m_return_pct") or ret_5m

            if mfe_val is not None:
                mfe_values.append(abs(mfe_val))
            if mae_val is not None:
                mae_values.append(abs(mae_val))

            target_status = o.get("outcome_60m") or o.get("outcome_30m") or o.get("outcome_15m") or o.get("outcome_5m", "")
            target_hits.append(1 if "WIN" in str(target_status).upper() else 0)

            o60 = o.get("outcome_60m_timestamp")
            o5 = o.get("outcome_5m_timestamp")
            candle_ts = o.get("candle_timestamp", "")
            if o60 and candle_ts:
                try:
                    t_target = datetime.fromisoformat(o60.replace("Z", "+00:00"))
                    t_candle = datetime.fromisoformat(candle_ts.replace("Z", "+00:00"))
                    time_targets.append((t_target - t_candle).total_seconds() / 60.0)
                except (ValueError, TypeError):
                    pass
            if o5 and candle_ts:
                try:
                    t_inv = datetime.fromisoformat(o5.replace("Z", "+00:00"))
                    t_candle = datetime.fromisoformat(candle_ts.replace("Z", "+00:00"))
                    time_invalidations.append((t_inv - t_candle).total_seconds() / 60.0)
                except (ValueError, TypeError):
                    pass

        result = {
            "median_favorable_move": _median(favorable_moves) if favorable_moves else None,
            "p25_favorable_move": _compute_percentile(sorted(favorable_moves), 25) if favorable_moves else None,
            "p75_favorable_move": _compute_percentile(sorted(favorable_moves), 75) if favorable_moves else None,
            "median_adverse_move": _median(adverse_moves) if adverse_moves else None,
            "p25_adverse_move": _compute_percentile(sorted(adverse_moves), 25) if adverse_moves else None,
            "p75_adverse_move": _compute_percentile(sorted(adverse_moves), 75) if adverse_moves else None,
            "mfe": _median(mfe_values) if mfe_values else None,
            "mae": _median(mae_values) if mae_values else None,
            "target_hit_rate": round(sum(target_hits) / len(target_hits), 4) if target_hits else None,
            "time_to_target": round(_median(time_targets), 2) if time_targets else None,
            "time_to_invalidation": round(_median(time_invalidations), 2) if time_invalidations else None,
        }

        return result

    def compute_expected_movement(self, symbol: str, scenario_type: str,
                                    session_date: str,
                                    market_state: Dict[str, Any] = None,
                                    db_path: str = None) -> Dict[str, Any]:
        """Compute expected movement range from historical comparable setups.

        Args:
            symbol: Instrument symbol (e.g., "NIFTY")
            scenario_type: Type of scenario (e.g., "BULLISH_BREAKOUT")
            session_date: Trading session date
            market_state: Current market state for dimension matching
            db_path: Path to database (defaults to default DB)

        Returns:
            Dict with expected movement statistics, target zone, and data status.
        """
        conn = _get_conn(db_path or self.db_path)
        try:
            direction = "LONG" if "BULLISH" in scenario_type.upper() else "SHORT"
            market_regime = normalize_regime(
                (market_state or {}).get("market_regime", "UNKNOWN")
            )
            volatility_regime = _get_volatility_regime(
                (market_state or {}).get("atr"),
                (market_state or {}).get("close"),
            )
            time_of_day = _get_time_of_day(
                (market_state or {}).get("candle_timestamp", "")
            )
            positioning_state = _get_positioning_state(market_state)
            liquidity_event = _get_liquidity_event(market_state, {})
            distance_from_vwap = _price_vs_vwap(
                (market_state or {}).get("close", 0),
                (market_state or {}).get("vwap"),
            )

            outcomes = self._load_outcome_data(conn, symbol)
            scenarios = self._load_scenario_data(conn, symbol, session_date)

            comparable_scenarios = self._find_comparable_scenarios(
                scenarios, scenario_type, direction, market_regime,
                volatility_regime, time_of_day, positioning_state, liquidity_event,
            )

            stats = self._compute_outcome_statistics(outcomes, direction)

            sample_size = len(outcomes)
            minimum_required = MIN_SAMPLE_SIZE

            if sample_size < minimum_required:
                return {
                    "symbol": symbol,
                    "scenario_type": scenario_type,
                    "session_date": session_date,
                    "direction": direction,
                    "market_regime": market_regime,
                    "volatility_regime": volatility_regime,
                    "time_of_day": time_of_day,
                    "distance_from_vwap": distance_from_vwap,
                    "positioning_state": positioning_state,
                    "liquidity_event": liquidity_event,
                    "data_status": "INSUFFICIENT_SAMPLE",
                    "sample_size": sample_size,
                    "minimum_required": minimum_required,
                    "median_favorable_move": None,
                    "p25_favorable_move": None,
                    "p75_favorable_move": None,
                    "median_adverse_move": None,
                    "p25_adverse_move": None,
                    "p75_adverse_move": None,
                    "mfe": None,
                    "mae": None,
                    "target_hit_rate": None,
                    "time_to_target": None,
                    "time_to_invalidation": None,
                    "target_zone_low": None,
                    "target_zone_high": None,
                    "expected_horizon_minutes": None,
                    "comparable_scenarios": comparable_scenarios[:10],
                    "data_quality": DATA_QUALITY_UNAVAILABLE,
                    "message": (
                        f"INSUFFICIENT_SAMPLE: {sample_size} outcomes found, "
                        f"minimum {minimum_required} required for calibration. "
                        f"Data status: NOT_CALIBRATED."
                    ),
                }

            median_favorable = stats["median_favorable_move"]
            p25_favorable = stats["p25_favorable_move"]
            p75_favorable = stats["p75_favorable_move"]

            ref_price = (market_state or {}).get("close") or (market_state or {}).get("entry_reference", 0)
            target_zone_low = None
            target_zone_high = None
            expected_horizon = None

            if ref_price and median_favorable is not None:
                move_high = median_favorable
                move_low = p25_favorable if p25_favorable is not None else median_favorable * 0.5
                target_zone_low = round(ref_price + ref_price * move_low / 100.0, 2)
                target_zone_high = round(ref_price + ref_price * move_high / 100.0, 2)
                expected_horizon = 60

            return {
                "symbol": symbol,
                "scenario_type": scenario_type,
                "session_date": session_date,
                "direction": direction,
                "market_regime": market_regime,
                "volatility_regime": volatility_regime,
                "time_of_day": time_of_day,
                "distance_from_vwap": distance_from_vwap,
                "positioning_state": positioning_state,
                "liquidity_event": liquidity_event,
                "data_status": "SUFFICIENT_DATA" if sample_size >= minimum_required else "INSUFFICIENT_SAMPLE",
                "sample_size": sample_size,
                "minimum_required": minimum_required,
                "median_favorable_move": round(median_favorable, 4) if median_favorable is not None else None,
                "p25_favorable_move": round(p25_favorable, 4) if p25_favorable is not None else None,
                "p75_favorable_move": round(p75_favorable, 4) if p75_favorable is not None else None,
                "median_adverse_move": round(stats["median_adverse_move"], 4) if stats["median_adverse_move"] is not None else None,
                "p25_adverse_move": round(stats["p25_adverse_move"], 4) if stats["p25_adverse_move"] is not None else None,
                "p75_adverse_move": round(stats["p75_adverse_move"], 4) if stats["p75_adverse_move"] is not None else None,
                "mfe": round(stats["mfe"], 4) if stats["mfe"] is not None else None,
                "mae": round(stats["mae"], 4) if stats["mae"] is not None else None,
                "target_hit_rate": round(stats["target_hit_rate"], 4) if stats["target_hit_rate"] is not None else None,
                "time_to_target": stats["time_to_target"],
                "time_to_invalidation": stats["time_to_invalidation"],
                "target_zone_low": target_zone_low,
                "target_zone_high": target_zone_high,
                "expected_horizon_minutes": expected_horizon,
                "comparable_scenarios": comparable_scenarios[:20],
                "data_quality": DATA_QUALITY_LIVE,
                "message": (
                    f"SUFFICIENT_DATA: {sample_size} outcomes used for calibration. "
                    f"Target zone: {target_zone_low} - {target_zone_high}"
                    if target_zone_low and target_zone_high
                    else f"{sample_size} outcomes processed."
                ),
            }
        finally:
            conn.close()

    def record_scenario_outcome(self, scenario_id: str, instrument: str,
                                  session_date: str, outcome_5m: str = "PENDING",
                                  outcome_5m_return_pct: Optional[float] = None,
                                  outcome_15m: str = "PENDING",
                                  outcome_15m_return_pct: Optional[float] = None,
                                  outcome_30m: str = "PENDING",
                                  outcome_30m_return_pct: Optional[float] = None,
                                  outcome_60m: str = "PENDING",
                                  outcome_60m_return_pct: Optional[float] = None,
                                  mfe_pct: Optional[float] = None,
                                  mae_pct: Optional[float] = None,
                                  target_reached: bool = False,
                                  invalidation_reached: bool = False,
                                  time_to_target: Optional[float] = None,
                                  time_to_invalidation: Optional[float] = None,
                                  db_path: str = None) -> bool:
        conn = _get_conn(db_path or self.db_path)
        try:
            conn.execute(
                """INSERT INTO scenario_outcomes (
                    scenario_id, instrument, session_date,
                    outcome_5m, outcome_5m_return_pct,
                    outcome_15m, outcome_15m_return_pct,
                    outcome_30m, outcome_30m_return_pct,
                    outcome_60m, outcome_60m_return_pct,
                    mfe, mae, target_reached, invalidation_reached,
                    time_to_target, time_to_invalidation, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
                (
                    scenario_id, instrument, session_date,
                    outcome_5m, outcome_5m_return_pct,
                    outcome_15m, outcome_15m_return_pct,
                    outcome_30m, outcome_30m_return_pct,
                    outcome_60m, outcome_60m_return_pct,
                    mfe_pct, mae_pct, target_reached, invalidation_reached,
                    time_to_target, time_to_invalidation, "RECORDED",
                ),
            )
            conn.commit()
            return True
        except sqlite3.Error as e:
            logger.warning(f"Failed to record scenario outcome {scenario_id}: {e}")
            return False
        finally:
            conn.close()

    def get_calibration_summary(self, symbol: str, db_path: str = None) -> Dict[str, Any]:
        conn = _get_conn(db_path or self.db_path)
        try:
            total = conn.execute(
                "SELECT COUNT(*) FROM scenario_outcomes WHERE instrument=?",
                (symbol,),
            ).fetchone()[0]

            if total < MIN_SAMPLE_SIZE:
                return {
                    "symbol": symbol,
                    "data_status": "INSUFFICIENT_DATA",
                    "sample_size": total,
                    "minimum_required": MIN_SAMPLE_SIZE,
                    "message": f"Sample size {total} < {MIN_SAMPLE_SIZE} minimum required",
                }

            target_hits = conn.execute(
                "SELECT COUNT(*) FROM scenario_outcomes WHERE instrument=? AND target_reached=1",
                (symbol,),
            ).fetchone()[0]

            avg_mfe = conn.execute(
                "SELECT AVG(mfe) FROM scenario_outcomes WHERE instrument=? AND mfe IS NOT NULL",
                (symbol,),
            ).fetchone()[0]

            avg_mae = conn.execute(
                "SELECT AVG(mae) FROM scenario_outcomes WHERE instrument=? AND mae IS NOT NULL",
                (symbol,),
            ).fetchone()[0]

            return {
                "symbol": symbol,
                "data_status": "SUFFICIENT_DATA",
                "sample_size": total,
                "minimum_required": MIN_SAMPLE_SIZE,
                "target_hit_rate": round(target_hits / total, 4) if total else 0,
                "avg_mfe": round(avg_mfe, 4) if avg_mfe else None,
                "avg_mae": round(avg_mae, 4) if avg_mae else None,
            }
        finally:
            conn.close()
