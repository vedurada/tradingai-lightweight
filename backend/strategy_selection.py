from __future__ import annotations

import json
import os
import sys
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logger = logging.getLogger("tradingai.strategy")

ENGINE_VERSION = "1.0.0-phase41"

VALID_BIAS = {"BULLISH", "BEARISH", "RANGE", "MIXED"}
VALID_TRADE_STATE = {"TRADE", "WAIT", "NO_TRADE"}
VALID_REGIME = {"BULLISH", "BEARISH", "RANGE", "MIXED"}

BULLISH_STRATEGIES = ["CALL_DEBIT_SPREAD", "PUT_CREDIT_SPREAD", "LONG_CALL"]
BEARISH_STRATEGIES = ["PUT_DEBIT_SPREAD", "CALL_CREDIT_SPREAD", "LONG_PUT"]
RANGE_STRATEGIES = ["SHORT_STRANGLE", "IRON_CONDOR", "SHORT_STRADDLE"]
VOLATILE_STRATEGIES = ["LONG_STRADDLE", "LONG_STRANGLE"]

STRATEGY_COMPATIBILITY = {
    "CALL_DEBIT_SPREAD": {
        "bias": "BULLISH", "requires_options": True, "defined_risk": True,
        "max_volatility": "HIGH", "legs": [
            {"action": "BUY", "type": "CALL", "description": "Buy lower strike call"},
            {"action": "SELL", "type": "CALL", "description": "Sell higher strike call"},
        ],
    },
    "PUT_CREDIT_SPREAD": {
        "bias": "BULLISH", "requires_options": True, "defined_risk": True,
        "max_volatility": "HIGH", "legs": [
            {"action": "SELL", "type": "PUT", "description": "Sell lower strike put"},
            {"action": "BUY", "type": "PUT", "description": "Buy lower strike put"},
        ],
    },
    "LONG_CALL": {
        "bias": "BULLISH", "requires_options": True, "defined_risk": True,
        "max_volatility": "NORMAL", "legs": [
            {"action": "BUY", "type": "CALL", "description": "Buy call option"},
        ],
    },
    "PUT_DEBIT_SPREAD": {
        "bias": "BEARISH", "requires_options": True, "defined_risk": True,
        "max_volatility": "HIGH", "legs": [
            {"action": "BUY", "type": "PUT", "description": "Buy higher strike put"},
            {"action": "SELL", "type": "PUT", "description": "Sell lower strike put"},
        ],
    },
    "CALL_CREDIT_SPREAD": {
        "bias": "BEARISH", "requires_options": True, "defined_risk": True,
        "max_volatility": "HIGH", "legs": [
            {"action": "SELL", "type": "CALL", "description": "Sell higher strike call"},
            {"action": "BUY", "type": "CALL", "description": "Buy higher strike call"},
        ],
    },
    "LONG_PUT": {
        "bias": "BEARISH", "requires_options": True, "defined_risk": True,
        "max_volatility": "NORMAL", "legs": [
            {"action": "BUY", "type": "PUT", "description": "Buy put option"},
        ],
    },
    "SHORT_STRANGLE": {
        "bias": "RANGE", "requires_options": True, "defined_risk": True,
        "max_volatility": "NORMAL", "legs": [
            {"action": "SELL", "type": "CALL", "description": "Sell OTM call"},
            {"action": "SELL", "type": "PUT", "description": "Sell OTM put"},
        ],
    },
    "IRON_CONDOR": {
        "bias": "RANGE", "requires_options": True, "defined_risk": True,
        "max_volatility": "HIGH", "legs": [
            {"action": "SELL", "type": "CALL", "description": "Sell OTM call"},
            {"action": "BUY", "type": "CALL", "description": "Buy further OTM call"},
            {"action": "SELL", "type": "PUT", "description": "Sell OTM put"},
            {"action": "BUY", "type": "PUT", "description": "Buy further OTM put"},
        ],
    },
    "SHORT_STRADDLE": {
        "bias": "RANGE", "requires_options": True, "defined_risk": False,
        "max_volatility": "LOW", "legs": [
            {"action": "SELL", "type": "CALL", "description": "Sell ATM call"},
            {"action": "SELL", "type": "PUT", "description": "Sell ATM put"},
        ],
    },
    "LONG_STRADDLE": {
        "bias": "MIXED", "requires_options": True, "defined_risk": True,
        "max_volatility": "HIGH", "legs": [
            {"action": "BUY", "type": "CALL", "description": "Buy ATM call"},
            {"action": "BUY", "type": "PUT", "description": "Buy ATM put"},
        ],
    },
    "LONG_STRANGLE": {
        "bias": "MIXED", "requires_options": True, "defined_risk": True,
        "max_volatility": "HIGH", "legs": [
            {"action": "BUY", "type": "CALL", "description": "Buy OTM call"},
            {"action": "BUY", "type": "PUT", "description": "Buy OTM put"},
        ],
    },
}

DEFAULT_EXPECTED_MOVE_OFFSET = 1.0


def _safe(v, default=0.0):
    try:
        if v is None:
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


class StrategySelectionError(Exception):
    pass


class StrategySelector:
    def __init__(self, config: dict = None):
        self.config = config or {}
        self.max_volatility = self.config.get("max_volatility", "HIGH")
        self.min_risk_reward = self.config.get("min_risk_reward", 1.5)
        self.requires_defined_risk = self.config.get("requires_defined_risk", True)

    def select(
        self,
        instrument: str,
        bias: str,
        volatility: str = "NORMAL",
        trend: str = "NEUTRAL",
        regime: str = "NEUTRAL",
        options_data: dict = None,
        expected_move: float = None,
        risk_reward: float = None,
        close: float = None,
        support: float = None,
        resistance: float = None,
    ) -> dict:
        result = {
            "instrument": instrument,
            "bias": bias,
            "volatility": volatility,
            "trend": trend,
            "regime": regime,
            "selected_strategy": None,
            "legs": [],
            "selection_reason": "",
            "candidate_strategies": [],
            "rejected_strategies": [],
            "data_quality": "LIVE",
            "engine_version": ENGINE_VERSION,
        }

        if bias not in VALID_BIAS:
            result["selection_reason"] = f"No strategy: bias={bias} not directional"
            result["data_quality"] = "UNAVAILABLE"
            return result

        candidate_pool = self._get_candidate_pool(bias, volatility)
        result["candidate_strategies"] = candidate_pool

        if not candidate_pool:
            result["selection_reason"] = f"No strategies for bias={bias}, vol={volatility}"
            result["data_quality"] = "UNAVAILABLE"
            return result

        preferred = self._filter_by_conditions(candidate_pool, volatility, regime)
        result["rejected_strategies"] = [s for s in candidate_pool if s not in preferred]

        if not preferred:
            result["selection_reason"] = "No strategies pass filter"
            result["data_quality"] = "UNAVAILABLE"
            return result

        strategy_name = preferred[0]
        strategy_info = STRATEGY_COMPATIBILITY.get(strategy_name, {})

        if not strategy_info:
            result["selection_reason"] = f"Strategy {strategy_name} not found"
            return result

        legs = strategy_info.get("legs", [])
        expected_move = expected_move or self._estimate_expected_move(close, support, resistance, volatility)

        result["selected_strategy"] = strategy_name
        result["legs"] = legs
        result["expected_move"] = expected_move
        result["selection_reason"] = f"Selected {strategy_name} for {bias} bias"

        return result

    def _get_candidate_pool(self, bias: str, volatility: str) -> list:
        if bias == "BULLISH":
            pool = list(BULLISH_STRATEGIES)
        elif bias == "BEARISH":
            pool = list(BEARISH_STRATEGIES)
        elif bias == "RANGE":
            pool = list(RANGE_STRATEGIES)
        else:
            pool = []
        return pool

    def _filter_by_conditions(self, strategies: list, volatility: str, regime: str) -> list:
        filtered = []
        for name in strategies:
            info = STRATEGY_COMPATIBILITY.get(name, {})
            max_vol = info.get("max_volatility", "HIGH")
            defined_risk = info.get("defined_risk", True)

            vol_rank = {"LOW": 1, "NORMAL": 2, "HIGH": 3}
            vol_ok = vol_rank.get(volatility, 2) <= vol_rank.get(max_vol, 3)

            if not vol_ok:
                continue
            if self.requires_defined_risk and not defined_risk:
                continue
            filtered.append(name)
        return filtered

    def _estimate_expected_move(self, close: float, support: float, resistance: float, volatility: str) -> float:
        if close and support and resistance:
            return (float(resistance) - float(support)) / 2
        atr_factor = {"LOW": 0.5, "NORMAL": 1.0, "HIGH": 1.5}
        return _safe(close) * 0.01 * atr_factor.get(volatility, 1.0)


def select_strategy(
    instrument: str,
    bias: str,
    volatility: str = "NORMAL",
    trend: str = "NEUTRAL",
    regime: str = "NEUTRAL",
    options_data: dict = None,
    expected_move: float = None,
    risk_reward: float = None,
    close: float = None,
    support: float = None,
    resistance: float = None,
    config: dict = None,
) -> dict:
    selector = StrategySelector(config=config)
    return selector.select(
        instrument, bias, volatility, trend, regime,
        options_data, expected_move, risk_reward, close, support, resistance,
    )
