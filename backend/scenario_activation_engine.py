from __future__ import annotations

import json
import logging
import os
import sys
import sqlite3
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db_schema import DB_PATH
from data_quality import DATA_QUALITY_LIVE, DATA_QUALITY_STALE, DATA_QUALITY_UNAVAILABLE
from regime_utils import normalize_regime

logger = logging.getLogger("tradingai.scenario_activation")


class ScenarioState(str, Enum):
    ARMED = "ARMED"
    PRE_TRIGGER = "PRE_TRIGGER"
    ACTIVATED = "ACTIVATED"
    CONFIRMED = "CONFIRMED"
    INVALIDATED = "INVALIDATED"
    EXPIRED = "EXPIRED"
    COMPLETED = "COMPLETED"


VALID_TRANSITIONS: Dict[ScenarioState, List[ScenarioState]] = {
    ScenarioState.ARMED: [ScenarioState.PRE_TRIGGER, ScenarioState.INVALIDATED, ScenarioState.EXPIRED],
    ScenarioState.PRE_TRIGGER: [ScenarioState.ACTIVATED, ScenarioState.INVALIDATED, ScenarioState.EXPIRED],
    ScenarioState.ACTIVATED: [ScenarioState.CONFIRMED, ScenarioState.INVALIDATED, ScenarioState.EXPIRED],
    ScenarioState.CONFIRMED: [ScenarioState.COMPLETED],
    ScenarioState.INVALIDATED: [ScenarioState.COMPLETED],
    ScenarioState.EXPIRED: [ScenarioState.COMPLETED],
    ScenarioState.COMPLETED: [],
}

SCENARIO_TYPES = {
    "BULLISH_BREAKOUT",
    "BEARISH_BREAKOUT",
    "RANGE_BREAKOUT",
    "REVERSAL",
    "TREND_CONTINUATION",
}


class ScenarioEvent:
    __slots__ = [
        "event_id", "scenario_id", "timestamp", "event_type",
        "price", "conditions", "evidence",
    ]

    def __init__(self, *, event_id: str, scenario_id: str, timestamp: str,
                 event_type: str, price: Optional[float],
                 conditions: Dict[str, Any], evidence: List[str]):
        self.event_id = event_id
        self.scenario_id = scenario_id
        self.timestamp = timestamp
        self.event_type = event_type
        self.price = price
        self.conditions = conditions
        self.evidence = sorted(evidence)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "scenario_id": self.scenario_id,
            "timestamp": self.timestamp,
            "event_type": self.event_type,
            "price": self.price,
            "conditions": self.conditions,
            "evidence": self.evidence,
        }


class ScenarioActivation:
    __slots__ = [
        "scenario_id", "symbol", "session_date", "scenario_type", "direction",
        "trigger", "confirmation_conditions", "invalidation",
        "expected_movement_pct", "expected_horizon_minutes",
        "target_zone_low", "target_zone_high",
        "state", "state_transitions",
        "activation_timestamp", "activation_price",
        "activation_conditions", "evidence_snapshot",
        "market_state_at_activation", "positioning_state_at_activation",
        "liquidity_state_at_activation", "market_intent_snapshot",
        "late_activation_flag", "late_activation_details",
        "data_quality", "created_at",
    ]

    def __init__(self, *, scenario_id: str, symbol: str, session_date: str,
                 scenario_type: str, direction: str, trigger: Optional[float],
                 confirmation_conditions: Dict[str, Any], invalidation: Dict[str, Any],
                 expected_movement_pct: Optional[float], expected_horizon_minutes: Optional[int],
                 target_zone_low: Optional[float], target_zone_high: Optional[float],
                 state: str, state_transitions: List[Dict[str, Any]],
                 activation_timestamp: Optional[str], activation_price: Optional[float],
                 activation_conditions: Dict[str, Any], evidence_snapshot: Dict[str, Any],
                 market_state_at_activation: Optional[Dict[str, Any]],
                 positioning_state_at_activation: Optional[Dict[str, Any]],
                 liquidity_state_at_activation: Optional[Dict[str, Any]],
                 market_intent_snapshot: Optional[Dict[str, Any]],
                 late_activation_flag: bool, late_activation_details: Optional[Dict[str, Any]],
                 data_quality: str, created_at: str):
        self.scenario_id = scenario_id
        self.symbol = symbol
        self.session_date = session_date
        self.scenario_type = scenario_type
        self.direction = direction
        self.trigger = trigger
        self.confirmation_conditions = confirmation_conditions
        self.invalidation = invalidation
        self.expected_movement_pct = expected_movement_pct
        self.expected_horizon_minutes = expected_horizon_minutes
        self.target_zone_low = target_zone_low
        self.target_zone_high = target_zone_high
        self.state = state
        self.state_transitions = state_transitions
        self.activation_timestamp = activation_timestamp
        self.activation_price = activation_price
        self.activation_conditions = activation_conditions
        self.evidence_snapshot = evidence_snapshot
        self.market_state_at_activation = market_state_at_activation
        self.positioning_state_at_activation = positioning_state_at_activation
        self.liquidity_state_at_activation = liquidity_state_at_activation
        self.market_intent_snapshot = market_intent_snapshot
        self.late_activation_flag = late_activation_flag
        self.late_activation_details = late_activation_details
        self.data_quality = data_quality
        self.created_at = created_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "symbol": self.symbol,
            "session_date": self.session_date,
            "scenario_type": self.scenario_type,
            "direction": self.direction,
            "trigger": self.trigger,
            "confirmation_conditions": self.confirmation_conditions,
            "invalidation": self.invalidation,
            "expected_movement_pct": self.expected_movement_pct,
            "expected_horizon_minutes": self.expected_horizon_minutes,
            "target_zone_low": self.target_zone_low,
            "target_zone_high": self.target_zone_high,
            "state": self.state,
            "state_transitions": self.state_transitions,
            "activation_timestamp": self.activation_timestamp,
            "activation_price": self.activation_price,
            "activation_conditions": self.activation_conditions,
            "evidence_snapshot": self.evidence_snapshot,
            "market_state_at_activation": self.market_state_at_activation,
            "positioning_state_at_activation": self.positioning_state_at_activation,
            "liquidity_state_at_activation": self.liquidity_state_at_activation,
            "market_intent_snapshot": self.market_intent_snapshot,
            "late_activation_flag": self.late_activation_flag,
            "late_activation_details": self.late_activation_details,
            "data_quality": self.data_quality,
            "created_at": self.created_at,
        }


def _get_conn(db_path: str = None) -> sqlite3.Connection:
    path = db_path or DB_PATH
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


def _generate_event_id() -> str:
    now = datetime.now(timezone.utc)
    return f"EVT-{now.strftime('%Y%m%dT%H%M%S')}-{now.microsecond:06d}"


def _close_price(candle: Dict[str, Any]) -> Optional[float]:
    if not candle:
        return None
    return candle.get("close")


def _vwap_from_market_state(market_state: Dict[str, Any]) -> Optional[float]:
    if not market_state:
        return None
    return market_state.get("vwap")


def _is_supportive_structure(market_state: Dict[str, Any], direction: str) -> bool:
    if not market_state:
        return False
    trend = market_state.get("trend_state", "UNKNOWN")
    regime = market_state.get("market_regime", "UNKNOWN")
    if direction == "LONG":
        return trend in ("BULLISH", "UPTREND") or regime == "BULLISH"
    elif direction == "SHORT":
        return trend in ("BEARISH", "DOWNTREND") or regime == "BEARISH"
    return False


def _price_vs_vwap(close_price: float, vwap: Optional[float]) -> str:
    if vwap is None or vwap == 0:
        return "UNKNOWN"
    diff_pct = (close_price - vwap) / vwap * 100
    if diff_pct > 0.1:
        return "ABOVE_VWAP"
    elif diff_pct < -0.1:
        return "BELOW_VWAP"
    return "AT_VWAP"


def _pre_trigger_check(candle: Dict[str, Any], trigger: Optional[float],
                       close_pct_threshold: float = 1.0) -> Tuple[bool, Optional[float]]:
    close = _close_price(candle)
    if close is None or trigger is None or trigger == 0:
        return False, None
    diff_pct = abs(close - trigger) / trigger * 100
    return diff_pct <= close_pct_threshold, diff_pct


def _activation_check_bullish_breakout(candle: Dict[str, Any], trigger: Optional[float],
                                       market_state: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    close = _close_price(candle)
    vwap = _vwap_from_market_state(market_state)
    if close is None or trigger is None:
        return False, {}

    conditions = {
        "close_above_trigger": close > trigger,
        "price_above_vwap": vwap is not None and close > vwap,
        "structure_supportive": _is_supportive_structure(market_state, "LONG"),
        "close_price": close,
        "trigger": trigger,
        "vwap": vwap,
        "price_vs_vwap": _price_vs_vwap(close, vwap),
    }

    all_met = (
        conditions["close_above_trigger"]
        and conditions["price_above_vwap"]
        and conditions["structure_supportive"]
    )
    return all_met, conditions


def _activation_check_bearish_breakout(candle: Dict[str, Any], trigger: Optional[float],
                                       market_state: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    close = _close_price(candle)
    vwap = _vwap_from_market_state(market_state)
    if close is None or trigger is None:
        return False, {}

    conditions = {
        "close_below_trigger": close < trigger,
        "price_below_vwap": vwap is not None and close < vwap,
        "structure_supportive": _is_supportive_structure(market_state, "SHORT"),
        "close_price": close,
        "trigger": trigger,
        "vwap": vwap,
        "price_vs_vwap": _price_vs_vwap(close, vwap),
    }

    all_met = (
        conditions["close_below_trigger"]
        and conditions["price_below_vwap"]
        and conditions["structure_supportive"]
    )
    return all_met, conditions


def _activation_check(candle: Dict[str, Any], trigger: Optional[float],
                      scenario_type: str, market_state: Dict[str, Any],
                      direction: str) -> Tuple[bool, Dict[str, Any]]:
    if scenario_type == "BULLISH_BREAKOUT":
        return _activation_check_bullish_breakout(candle, trigger, market_state)
    elif scenario_type == "BEARISH_BREAKOUT":
        return _activation_check_bearish_breakout(candle, trigger, market_state)
    else:
        close = _close_price(candle)
        if close is None or trigger is None:
            return False, {}
        conditions = {
            "close_meets_trigger": direction == "LONG" and close > trigger
                       or direction == "SHORT" and close < trigger,
            "close_price": close,
            "trigger": trigger,
        }
        return conditions["close_meets_trigger"], conditions


def _confirmation_check(candle: Dict[str, Any], confirmation_conditions: Dict[str, Any],
                        market_state: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    if not confirmation_conditions:
        return False, {}

    close = _close_price(candle)
    vwap = _vwap_from_market_state(market_state)

    conditions = dict(confirmation_conditions)
    conditions["close_price"] = close
    conditions["vwap"] = vwap

    required = confirmation_conditions.get("required_signals", [])
    met_count = 0
    for signal_name in required:
        if signal_name == "close_above_trigger" and close and confirmation_conditions.get("trigger"):
            if close > confirmation_conditions["trigger"]:
                met_count += 1
        elif signal_name == "volume_confirmed" and candle.get("volume", 0) > 0:
            met_count += 1
        elif signal_name == "momentum_positive" and market_state.get("rsi", 0) > 50:
            met_count += 1
        elif signal_name == "trend_supportive":
            if _is_supportive_structure(market_state, "LONG"):
                met_count += 1
        elif signal_name == "price_above_vwap" and vwap and close and close > vwap:
            met_count += 1

    all_met = met_count == len(required) if required else False
    conditions["signals_met"] = met_count
    conditions["signals_required"] = len(required)
    conditions["confirmed"] = all_met
    return all_met, conditions


def _invalidation_check(candle: Dict[str, Any], invalidation: Dict[str, Any],
                        current_state: str) -> Tuple[bool, Dict[str, Any]]:
    if not invalidation:
        return False, {}

    close = _close_price(candle)
    trigger = invalidation.get("trigger_level")
    conditions = dict(invalidation)
    conditions["close_price"] = close

    if current_state in ("ACTIVATED", "CONFIRMED"):
        if trigger and close is not None:
            direction = invalidation.get("direction", "LONG")
            if direction == "LONG" and close < trigger:
                return True, conditions
            if direction == "SHORT" and close > trigger:
                return True, conditions

    return False, conditions


def _build_evidence_snapshot(candle: Dict[str, Any], market_state: Dict[str, Any],
                             symbol: str, timestamp: str) -> Dict[str, Any]:
    close = _close_price(candle)
    evidence = {
        "symbol": symbol,
        "candle_timestamp": timestamp,
        "candle": {
            "open": candle.get("open"),
            "high": candle.get("high"),
            "low": candle.get("low"),
            "close": close,
            "volume": candle.get("volume"),
        },
        "market_state": {k: v for k, v in (market_state or {}).items()
                         if k not in ("indicators", "raw_data")},
        "data_used_timestamp": timestamp,
        "no_lookahead": True,
    }
    return evidence


def _build_market_intent_snapshot(market_state: Dict[str, Any],
                                  positioning_state: Dict[str, Any],
                                  liquidity_state: Dict[str, Any]) -> Dict[str, Any]:
    intent = {
        "market_regime": market_state.get("market_regime") if market_state else "UNKNOWN",
        "trend_state": market_state.get("trend_state") if market_state else "UNKNOWN",
        "volatility_state": market_state.get("volatility_state") if market_state else "UNKNOWN",
        "positioning": positioning_state or {},
        "liquidity": liquidity_state or {},
    }
    return intent


def _detect_late_activation(activation_price: Optional[float],
                            max_favorable_price: Optional[float],
                            expected_movement_pct: Optional[float],
                            pre_trigger_price: Optional[float],
                            activation_timestamp: Optional[str],
                            current_time: str) -> Tuple[bool, Optional[Dict[str, Any]]]:
    if activation_price is None or expected_movement_pct is None or expected_movement_pct == 0:
        return False, None

    expected_move_abs = activation_price * expected_movement_pct / 100.0

    if max_favorable_price is not None:
        actual_favorable = max_favorable_price - activation_price
        if actual_favorable >= expected_move_abs * 0.5:
            time_to_mfe = None
            if activation_timestamp and current_time:
                try:
                    t_activation = datetime.fromisoformat(activation_timestamp.replace("Z", "+00:00"))
                    t_now = datetime.fromisoformat(current_time.replace("Z", "+00:00"))
                    time_to_mfe = (t_now - t_activation).total_seconds() / 60.0
                except (ValueError, TypeError):
                    pass

            return True, {
                "activation_price": activation_price,
                "max_favorable_price": max_favorable_price,
                "expected_move_abs": expected_move_abs,
                "actual_favorable_move": round(actual_favorable, 4),
                "favorable_pct_of_expected": round(actual_favorable / expected_move_abs * 100, 2),
                "time_to_mfe_minutes": time_to_mfe,
                "movement_before_activation": None if pre_trigger_price is None else round(
                    (activation_price - pre_trigger_price) / pre_trigger_price * 100, 4),
                "movement_remaining_after_activation": round(
                    (expected_move_abs - actual_favorable) / expected_move_abs * 100, 2),
            }

    return False, None


class ScenarioActivationEngine:
    """Scenario Activation Engine.

    Evaluates completed 5-minute candles against active pre-market scenarios.
    Manages the full scenario lifecycle: ARMED → PRE_TRIGGER → ACTIVATED → CONFIRMED → INVALIDATED → EXPIRED → COMPLETED.

    Principles:
    - ONLY uses information available at the activation timestamp (NO FUTURE DATA)
    - Deterministic state transitions
    - Records full evidence snapshot at each transition
    - Late activation detection for risk management
    """

    def __init__(self, db_path: str = None):
        self.db_path = db_path or DB_PATH

    def _load_active_scenarios(self, symbol: str, session_date: str, conn: sqlite3.Connection) -> List[dict]:
        rows = conn.execute(
            """SELECT * FROM pre_market_scenarios
               WHERE symbol=? AND session_date=? AND status IN ('ARMED', 'PRE_TRIGGER', 'ACTIVATED')
               ORDER BY created_at""",
            (symbol, session_date),
        ).fetchall()
        return [dict(r) for r in rows]

    def evaluate_activation(self, symbol: str, candle: Dict[str, Any],
                            market_state: Dict[str, Any] = None,
                            session_date: str = None,
                            db_path: str = None) -> Dict[str, Any]:
        """Evaluate a completed 5m candle against active pre-market scenarios.

        Args:
            symbol: Instrument symbol (e.g., "NIFTY")
            candle: Completed 5m candle with open, high, low, close, volume, timestamp
            market_state: Current market state (vwap, trend, regime, etc.)
            session_date: Trading session date (defaults from candle timestamp)
            db_path: Path to database (defaults to default DB)

        Returns:
            Dict with scenario_id, new_state, activation_details, evidence, late_activation flag
        """
        conn = _get_conn(db_path or self.db_path)
        try:
            candle_ts = candle.get("timestamp")
            if not session_date:
                session_date = candle_ts[:10] if candle_ts else ""

            current_time = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

            scenarios = self._load_active_scenarios(symbol, session_date, conn)

            results = []
            for scenario in scenarios:
                result = self._evaluate_single_scenario(
                    scenario, candle, market_state or {}, session_date, current_time, conn, symbol,
                )
                results.append(result)

            data_quality = DATA_QUALITY_LIVE if scenarios else DATA_QUALITY_UNAVAILABLE

            return {
                "symbol": symbol,
                "candle_timestamp": candle_ts,
                "session_date": session_date,
                "scenarios_evaluated": len(results),
                "results": results,
                "data_quality": data_quality,
                "evaluation_timestamp": current_time,
            }
        finally:
            conn.close()

    def _evaluate_single_scenario(self, scenario: dict, candle: Dict[str, Any],
                                  market_state: Dict[str, Any], session_date: str,
                                  current_time: str, conn: sqlite3.Connection,
                                  symbol: str = "") -> Dict[str, Any]:
        scenario_id = scenario["scenario_id"]
        current_state = scenario.get("state", ScenarioState.ARMED.value)
        trigger = scenario.get("trigger")
        scenario_type = scenario.get("scenario_type", "").upper()
        direction = scenario.get("direction", "LONG")
        confirmation_conditions = scenario.get("confirmation_conditions", {})
        invalidation_cfg = scenario.get("invalidation", {})
        expected_movement_pct = scenario.get("expected_movement_pct")
        expected_horizon = scenario.get("expected_horizon_minutes")
        target_zone_low = scenario.get("target_zone_low")
        target_zone_high = scenario.get("target_zone_high")

        _st_raw = scenario.get("state_transitions", "[]")
        if isinstance(_st_raw, str):
            try: state_transitions = json.loads(_st_raw)
            except (json.JSONDecodeError, TypeError): state_transitions = []
        else: state_transitions = list(_st_raw) if _st_raw else []
        activation_conditions = {}
        evidence_snapshot = {}
        late_activation_flag = False
        late_activation_details = None
        new_state = current_state

        close_price = _close_price(candle)
        if close_price is None:
            return {
                "scenario_id": scenario_id,
                "state": current_state,
                "action": "SKIPPED",
                "reason": "Candle has no close price",
                "state_transitions": state_transitions,
                "data_quality": DATA_QUALITY_UNAVAILABLE,
            }

        try:
            if current_state == ScenarioState.ARMED.value:
                pre_trigger, pre_trigger_pct = _pre_trigger_check(candle, trigger)
                if pre_trigger:
                    new_state = ScenarioState.PRE_TRIGGER.value
                    state_transitions.append({
                        "from": ScenarioState.ARMED.value,
                        "to": ScenarioState.PRE_TRIGGER.value,
                        "timestamp": candle.get("timestamp", current_time),
                        "price": close_price,
                        "reason": f"Price within 1% of trigger ({pre_trigger_pct:.4f}%)",
                        "evidence": {
                            "close_price": close_price,
                            "trigger": trigger,
                            "distance_pct": round(pre_trigger_pct, 4),
                        },
                    })
                else:
                    expiry_ts = scenario.get("expiry_timestamp")
                    if expiry_ts and candle.get("timestamp", "") >= expiry_ts:
                        new_state = ScenarioState.EXPIRED.value
                        state_transitions.append({
                            "from": ScenarioState.ARMED.value,
                            "to": ScenarioState.EXPIRED.value,
                            "timestamp": candle.get("timestamp", current_time),
                            "price": close_price,
                            "reason": "Time window expired before trigger was reached",
                            "evidence": {
                                "close_price": close_price,
                                "expiry_timestamp": expiry_ts,
                            },
                        })

            if current_state == ScenarioState.PRE_TRIGGER.value or (current_state == ScenarioState.ARMED.value and new_state == ScenarioState.PRE_TRIGGER.value):
                if current_state == ScenarioState.PRE_TRIGGER.value or new_state == ScenarioState.PRE_TRIGGER.value:
                    all_met, act_conditions = _activation_check(
                        candle, trigger, scenario_type, market_state, direction,
                    )
                    activation_conditions = act_conditions

                    if all_met:
                        new_state = ScenarioState.ACTIVATED.value
                        evidence_snapshot = _build_evidence_snapshot(
                            candle, market_state, symbol, candle.get("timestamp", current_time),
                        )

                        positioning_state = {
                            "vwap_position": _price_vs_vwap(close_price, _vwap_from_market_state(market_state)),
                            "trend_alignment": _is_supportive_structure(market_state, direction),
                            "regime": market_state.get("market_regime", "UNKNOWN") if market_state else "UNKNOWN",
                        }

                        liquidity_state = {
                            "volume": candle.get("volume"),
                            "volume_vs_average": None,
                            "spread": None,
                        }

                        market_intent = _build_market_intent_snapshot(
                            market_state, positioning_state, liquidity_state,
                        )

                        state_transitions.append({
                            "from": ScenarioState.PRE_TRIGGER.value,
                            "to": ScenarioState.ACTIVATED.value,
                            "timestamp": candle.get("timestamp", current_time),
                            "price": close_price,
                            "activation_price": close_price,
                            "reason": "Activation conditions met for " + scenario_type,
                            "activation_conditions": activation_conditions,
                            "evidence_snapshot": evidence_snapshot,
                            "positioning_state": positioning_state,
                            "liquidity_state": liquidity_state,
                            "market_intent_snapshot": market_intent,
                        })

                        late_activation_flag, late_activation_details = _detect_late_activation(
                            close_price, candle.get("high"), expected_movement_pct,
                            scenario.get("pre_trigger_price"),
                            candle.get("timestamp", current_time),
                            current_time,
                        )

            elif current_state == ScenarioState.ARMED.value and new_state == ScenarioState.ARMED.value:
                expiry_ts = scenario.get("expiry_timestamp")
                if expiry_ts and candle.get("timestamp", "") >= expiry_ts:
                    new_state = ScenarioState.EXPIRED.value
                    state_transitions.append({
                        "from": ScenarioState.ARMED.value,
                        "to": ScenarioState.EXPIRED.value,
                        "timestamp": candle.get("timestamp", current_time),
                        "price": close_price,
                        "reason": "Time window expired while in ARMED state",
                        "evidence": {
                            "close_price": close_price,
                            "expiry_timestamp": expiry_ts,
                        },
                    })

            if current_state == ScenarioState.ACTIVATED.value or (new_state == ScenarioState.ACTIVATED.value):
                if scenario_type in ("BULLISH_BREAKOUT", "BEARISH_BREAKOUT"):
                    confirmed, conf_conditions = _confirmation_check(
                        candle, confirmation_conditions, market_state,
                    )
                    if confirmed:
                        new_state = ScenarioState.CONFIRMED.value
                        state_transitions.append({
                            "from": ScenarioState.ACTIVATED.value,
                            "to": ScenarioState.CONFIRMED.value,
                            "timestamp": candle.get("timestamp", current_time),
                            "price": close_price,
                            "reason": "All confirmation conditions satisfied",
                            "confirmation_conditions": conf_conditions,
                        })
                    elif direction == "LONG" and close_price < (trigger or float("inf")):
                        new_state = ScenarioState.INVALIDATED.value
                        invalid_met, inv_conditions = _invalidation_check(
                            candle, invalidation_cfg, ScenarioState.ACTIVATED.value,
                        )
                        state_transitions.append({
                            "from": ScenarioState.ACTIVATED.value,
                            "to": ScenarioState.INVALIDATED.value,
                            "timestamp": candle.get("timestamp", current_time),
                            "price": close_price,
                            "reason": "Invalidation triggered after activation",
                            "invalidation_conditions": inv_conditions,
                        })

            elif current_state == ScenarioState.ACTIVATED.value:
                invalid_met, inv_conditions = _invalidation_check(
                    candle, invalidation_cfg, ScenarioState.ACTIVATED.value,
                )
                if invalid_met:
                    new_state = ScenarioState.INVALIDATED.value
                    state_transitions.append({
                        "from": ScenarioState.ACTIVATED.value,
                        "to": ScenarioState.INVALIDATED.value,
                        "timestamp": candle.get("timestamp", current_time),
                        "price": close_price,
                        "reason": "Invalidation triggered",
                        "invalidation_conditions": inv_conditions,
                    })

            elif current_state == ScenarioState.CONFIRMED.value:
                invalid_met, inv_conditions = _invalidation_check(
                    candle, invalidation_cfg, ScenarioState.CONFIRMED.value,
                )
                if invalid_met:
                    new_state = ScenarioState.INVALIDATED.value
                    state_transitions.append({
                        "from": ScenarioState.CONFIRMED.value,
                        "to": ScenarioState.INVALIDATED.value,
                        "timestamp": candle.get("timestamp", current_time),
                        "price": close_price,
                        "reason": "Invalidation triggered after confirmation",
                        "invalidation_conditions": inv_conditions,
                    })
                else:
                    new_state = ScenarioState.COMPLETED.value
                    state_transitions.append({
                        "from": ScenarioState.CONFIRMED.value,
                        "to": ScenarioState.COMPLETED.value,
                        "timestamp": candle.get("timestamp", current_time),
                        "price": close_price,
                        "reason": "Scenario resolved after confirmation",
                    })

            elif current_state == ScenarioState.INVALIDATED.value:
                new_state = ScenarioState.COMPLETED.value
                state_transitions.append({
                    "from": ScenarioState.INVALIDATED.value,
                    "to": ScenarioState.COMPLETED.value,
                    "timestamp": candle.get("timestamp", current_time),
                    "price": close_price,
                    "reason": "Invalidated scenario completed",
                })

            elif current_state == ScenarioState.EXPIRED.value:
                new_state = ScenarioState.COMPLETED.value
                state_transitions.append({
                    "from": ScenarioState.EXPIRED.value,
                    "to": ScenarioState.COMPLETED.value,
                    "timestamp": candle.get("timestamp", current_time),
                    "price": close_price,
                    "reason": "Expired scenario completed",
                })

        except (ValueError, TypeError) as e:
            logger.warning(f"Scenario {scenario_id} evaluation error: {e}")

        final_state = ScenarioState(new_state) if new_state in (s.value for s in ScenarioState) else current_state

        is_valid_transition = final_state in VALID_TRANSITIONS.get(
            ScenarioState(current_state) if current_state in (s.value for s in ScenarioState) else ScenarioState.ARMED, []
        ) or final_state == current_state

        if not is_valid_transition and final_state != current_state:
            logger.warning(f"Invalid transition {current_state} → {final_state} for {scenario_id}")
            new_state = current_state
            final_state = ScenarioState(current_state)

        activation_price = None
        if new_state == ScenarioState.ACTIVATED.value:
            for t in reversed(state_transitions):
                if t.get("to") == ScenarioState.ACTIVATED.value:
                    activation_price = t.get("activation_price")
                    break

        result = {
            "scenario_id": scenario_id,
            "symbol": symbol,
            "session_date": session_date,
            "scenario_type": scenario_type,
            "direction": direction,
            "previous_state": current_state,
            "new_state": new_state,
            "state_transitions": state_transitions,
            "activation_timestamp": scenario.get("activation_timestamp"),
            "activation_price": activation_price,
            "activation_conditions": activation_conditions,
            "evidence_snapshot": evidence_snapshot,
            "market_state_at_activation": scenario.get("market_state_at_activation"),
            "positioning_state_at_activation": scenario.get("positioning_state_at_activation"),
            "liquidity_state_at_activation": scenario.get("liquidity_state_at_activation"),
            "market_intent_snapshot": scenario.get("market_intent_snapshot"),
            "late_activation_flag": late_activation_flag,
            "late_activation_details": late_activation_details,
            "expected_movement_pct": expected_movement_pct,
            "expected_horizon_minutes": expected_horizon,
            "target_zone_low": target_zone_low,
            "target_zone_high": target_zone_high,
            "close_price": close_price,
            "trigger": trigger,
            "data_quality": DATA_QUALITY_LIVE,
            "evaluation_timestamp": current_time,
        }

        self._persist_transition(conn, scenario_id, state_transitions[-1] if state_transitions else None, new_state)

        return result

    def _persist_transition(self, conn: sqlite3.Connection, scenario_id: str,
                           transition: Optional[Dict[str, Any]], new_state: str) -> None:
        if not transition:
            return
        try:
            conn.execute(
                """INSERT INTO scenario_events (scenario_id, timestamp, event_type, price, conditions, evidence)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    scenario_id,
                    transition.get("timestamp", ""),
                    transition.get("to", new_state),
                    transition.get("price"),
                    json.dumps(transition.get("activation_conditions", transition.get("reason", ""))),
                    json.dumps(transition.get("evidence_snapshot", transition.get("evidence", {}))),
                ),
            )
            conn.commit()
        except sqlite3.Error as e:
            logger.warning(f"Failed to persist scenario event for {scenario_id}: {e}")

    def get_scenario_state(self, scenario_id: str, db_path: str = None) -> Optional[dict]:
        conn = _get_conn(db_path or self.db_path)
        try:
            row = conn.execute(
                "SELECT * FROM pre_market_scenarios WHERE scenario_id=?",
                (scenario_id,),
            ).fetchone()
            if not row:
                return None
            return dict(row)
        finally:
            conn.close()

    def get_late_activations(self, symbol: str, session_date: str,
                             db_path: str = None) -> List[dict]:
        conn = _get_conn(db_path or self.db_path)
        try:
            rows = conn.execute(
                """SELECT * FROM pre_market_scenarios
                   WHERE symbol=? AND session_date=? AND late_activation_flag=1 AND state IN (?, ?, ?)""",
                (symbol, session_date, ScenarioState.ACTIVATED.value,
                 ScenarioState.CONFIRMED.value, ScenarioState.COMPLETED.value),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def update_scenario_state(self, scenario_id: str, new_state: str,
                              db_path: str = None) -> bool:
        conn = _get_conn(db_path or self.db_path)
        try:
            conn.execute(
                "UPDATE pre_market_scenarios SET status=? WHERE scenario_id=?",
                (new_state, scenario_id),
            )
            conn.commit()
            return True
        finally:
            conn.close()
