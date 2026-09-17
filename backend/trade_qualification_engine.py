from __future__ import annotations

import json
import os
import sys
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logger = logging.getLogger("tradingai.qualification")

ENGINE_VERSION = "1.0.0-phase41"

DEFAULT_RISK_CONFIG = {
    "capital": 500000,
    "max_risk_per_trade_pct": 0.5,
    "max_daily_loss_pct": 2.0,
    "max_trades_per_day": 3,
    "max_active_trades": 1,
    "min_risk_reward": 1.5,
    "max_consecutive_losses": 3,
    "max_position_size_pct": 10.0,
    "session_start": "09:15",
    "session_end": "15:30",
}

VALID_BIAS = {"BULLISH", "BEARISH", "RANGE", "MIXED"}
VALID_TRADE_STATE = {"TRADE", "WAIT", "NO_TRADE"}
VALID_REGIME = {"BULLISH", "BEARISH", "RANGE", "MIXED"}

STRATEGY_BY_BIAS = {
    "BULLISH": {
        "strategy": "CALL_DEBIT_SPREAD",
        "direction": "BULLISH",
        "entry_condition": "Price sustains above breakout level with VWAP support",
        "default_invalidation_offset_pct": 0.5,
        "default_target_offset_pct": 1.5,
        "long_allowed": False,
    },
    "BEARISH": {
        "strategy": "PUT_DEBIT_SPREAD",
        "direction": "BEARISH",
        "entry_condition": "Price sustains below breakdown level with VWAP resistance",
        "default_invalidation_offset_pct": 0.5,
        "default_target_offset_pct": 1.5,
        "long_allowed": False,
    },
    "RANGE": {
        "strategy": "SHORT_STRANGLE",
        "direction": "NEUTRAL",
        "entry_condition": "Price oscillates between support and resistance",
        "default_invalidation_offset_pct": 1.0,
        "default_target_offset_pct": 0.5,
        "long_allowed": False,
    },
    "MIXED": {
        "strategy": None,
        "direction": "NEUTRAL",
        "entry_condition": "",
        "default_invalidation_offset_pct": 0.5,
        "default_target_offset_pct": 1.0,
        "long_allowed": False,
    },
}


def _safe(v, default=0.0):
    try:
        if v is None:
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


class QualificationResult:
    def __init__(self):
        self.trade_status = "NO_TRADE"
        self.reason = ""
        self.checks = {}
        self.rejection_reasons = []
        self.confirmation = ""
        self.invalidation = ""
        self.entry_price = None
        self.stop_price = None
        self.target_price = None
        self.risk_points = 0.0
        self.reward_points = 0.0
        self.risk_reward = 0.0
        self.strategy = None
        self.direction = "NEUTRAL"
        self.evidence_id = ""
        self.outlook_id = ""
        self.snapshot_id = ""
        self.instrument = ""
        self.candle_timestamp = ""
        self.qualification_timestamp = ""
        self.daily_risk_available = True
        self.daily_risk_reason = ""
        self.active_trade_exists = False
        self.data_availability = {}

    def to_dict(self) -> dict:
        return {
            "trade_status": self.trade_status,
            "reason": self.reason,
            "checks": self.checks,
            "rejection_reasons": self.rejection_reasons,
            "confirmation": self.confirmation,
            "invalidation": self.invalidation,
            "entry_price": self.entry_price,
            "stop_price": self.stop_price,
            "target_price": self.target_price,
            "risk_points": self.risk_points,
            "reward_points": self.reward_points,
            "risk_reward": self.risk_reward,
            "strategy": self.strategy,
            "direction": self.direction,
            "evidence_id": self.evidence_id,
            "outlook_id": self.outlook_id,
            "snapshot_id": self.snapshot_id,
            "instrument": self.instrument,
            "candle_timestamp": self.candle_timestamp,
            "qualification_timestamp": self.qualification_timestamp,
            "daily_risk_available": self.daily_risk_available,
            "daily_risk_reason": self.daily_risk_reason,
            "active_trade_exists": self.active_trade_exists,
            "data_availability": self.data_availability,
            "engine_version": ENGINE_VERSION,
        }


def _check(qual: QualificationResult, name: str, passed: bool, detail: str = ""):
    qual.checks[name] = {"passed": passed, "detail": detail}
    if not passed:
        qual.rejection_reasons.append(name)
    return passed


class TradeQualificationEngine:
    def __init__(self, risk_config: dict = None):
        self.risk_config = {**DEFAULT_RISK_CONFIG, **(risk_config or {})}

    def qualify(
        self,
        instrument: str,
        snapshot: dict,
        evidence: dict,
        market_state: dict,
        outlook: dict,
        options_data: dict = None,
        active_trade: dict = None,
    ) -> QualificationResult:
        result = QualificationResult()
        result.instrument = instrument
        result.candle_timestamp = snapshot.get("candle_timestamp", snapshot.get("timestamp", ""))
        result.evidence_id = evidence.get("evidence_id", "") if evidence else ""
        result.outlook_id = outlook.get("outlook_id", "") if outlook else ""
        result.snapshot_id = snapshot.get("id", snapshot.get("snapshot_id", "")) if snapshot else ""
        result.qualification_timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        if not snapshot:
            result.trade_status = "NO_TRADE"
            result.reason = "No market snapshot available"
            result.checks["market_data_available"] = {"passed": False, "detail": "No snapshot"}
            return result

        self._check_ai_outlook(result, outlook)
        self._check_market_evidence(result, evidence)
        self._check_confirmation(result, snapshot, outlook)
        self._check_invalidation(result, snapshot, outlook)
        self._check_risk(result, snapshot, outlook, options_data)
        self._check_options_data(result, options_data, outlook, evidence)
        self._check_daily_risk(result, instrument)
        self._check_active_trade(result, active_trade)
        self._check_data_availability(result, snapshot, evidence, options_data)

        passing = [name for name, check in result.checks.items() if check.get("passed")]
        total = len(result.checks)
        rejection = result.rejection_reasons

        if result.trade_status == "NO_TRADE" and not rejection and total > 0:
            result.trade_status = "TRADE"
        elif result.trade_status == "NO_TRADE" and not rejection:
            result.trade_status = "TRADE"

        self._determine_strategy(result, outlook, options_data)

        if result.trade_status == "NO_TRADE":
            if not result.rejection_reasons:
                result.rejection_reasons.append("trade_qualification_not_satisfied")
            result.reason = "NO_TRADE: " + ", ".join(result.rejection_reasons)
        elif result.trade_status == "WAIT":
            result.reason = "WAIT: " + result.confirmation if result.confirmation else "WAIT: conditions not yet confirmed"
        elif result.trade_status == "TRADE":
            result.reason = "TRADE: all qualification checks passed"

        logger.info(
            f"[{instrument}] Qualification: {result.trade_status} "
            f"reason={result.reason} checks={json.dumps({k: v['passed'] for k, v in result.checks.items()})}"
        )
        return result

    def _check_ai_outlook(self, result: QualificationResult, outlook: dict):
        if not outlook:
            _check(result, "ai_outlook_present", False, "No AI outlook provided")
            return

        bias = outlook.get("bias", "MIXED")
        trade_state = outlook.get("trade_state", "NO_TRADE")
        confidence = outlook.get("confidence", 0)

        bias_ok = bias in VALID_BIAS
        _check(result, "ai_bias_valid", bias_ok, f"bias={bias}")

        ts_ok = trade_state in VALID_TRADE_STATE
        _check(result, "ai_trade_state_valid", ts_ok, f"trade_state={trade_state}")

        ai_allows_trade = trade_state == "TRADE"
        _check(result, "ai_trade_state_requires_trade", ai_allows_trade,
               f"AI trade_state={trade_state}, needs TRADE for qualification")

        if bias not in VALID_BIAS:
            result.direction = "NEUTRAL"
        else:
            result.direction = bias

        _check(result, "ai_confidence_reviewed", True, f"confidence={confidence} (not used for qualification)")

    def _check_market_evidence(self, result: QualificationResult, evidence: dict):
        if not evidence or not evidence.get("groups"):
            _check(result, "evidence_available", False, "No evidence data")
            return

        overall = evidence.get("overall", {})
        groups = evidence.get("groups", {})
        conflict = evidence.get("conflict", {})

        overall_signal = overall.get("overall_signal", "INSUFFICIENT_DATA")
        has_directional = overall_signal in ("BULLISH", "BEARISH")
        _check(result, "evidence_directional", has_directional, f"overall_signal={overall_signal}")

        conflict_detected = conflict.get("detected", False)
        conflict_severity = conflict.get("severity", "NONE")
        _check(result, "evidence_no_severe_conflict",
               not (conflict_detected and conflict_severity == "HIGH"),
               f"conflict={conflict_severity}")

        unavailable_groups = [n for n, g in groups.items() if g.get("availability") == "UNAVAILABLE"]
        directional_groups = [n for n, g in groups.items()
                              if g.get("signal") in ("BULLISH", "BEARISH")]
        _check(result, "evidence_sufficient_groups",
               len(directional_groups) >= 3 or (len(directional_groups) >= 2 and not unavailable_groups),
               f"directional={len(directional_groups)}, unavailable={unavailable_groups}")

        for name, g in groups.items():
            if g.get("availability") == "UNAVAILABLE":
                result.data_availability[name] = "UNAVAILABLE"
            else:
                result.data_availability[name] = g.get("availability", "UNKNOWN")

    def _check_confirmation(self, result: QualificationResult, snapshot: dict, outlook: dict):
        bias = outlook.get("bias", "MIXED") if outlook else "MIXED"
        confirmation = outlook.get("confirmation_conditions", []) if outlook else []
        vwap = snapshot.get("price_vs_vwap", "UNKNOWN")
        close = snapshot.get("close")

        if bias == "BULLISH":
            has_confirmation = vwap == "ABOVE" or (close is not None and close > _safe(snapshot.get("vwap", 0)))
            _check(result, "bullish_confirmation", has_confirmation,
                   f"vwap={vwap}, close={close}")
            result.confirmation = "Price sustains above VWAP for bullish confirmation" if has_confirmation else "Bullish confirmation not met: price must sustain above VWAP"
        elif bias == "BEARISH":
            has_confirmation = vwap == "BELOW" or (close is not None and close < _safe(snapshot.get("vwap", 0)))
            _check(result, "bearish_confirmation", has_confirmation,
                   f"vwap={vwap}, close={close}")
            result.confirmation = "Price sustains below VWAP for bearish confirmation" if has_confirmation else "Bearish confirmation not met: price must sustain below VWAP"
        elif bias == "RANGE":
            support = snapshot.get("support")
            resistance = snapshot.get("resistance")
            has_confirmation = (_safe(close) >= _safe(support) and _safe(close) <= _safe(resistance)) if (support and resistance) else False
            _check(result, "range_confirmation", has_confirmation,
                   f"close in range: {has_confirmation}")
            result.confirmation = "Price within support/resistance range" if has_confirmation else "Range confirmation not met"
        else:
            _check(result, "confirmation_not_required", True, "MIXED bias does not require confirmation")
            result.confirmation = ""

    def _check_invalidation(self, result: QualificationResult, snapshot: dict, outlook: dict):
        bias = outlook.get("bias", "MIXED") if outlook else "MIXED"
        vwap = snapshot.get("vwap")
        close = snapshot.get("close")
        support = snapshot.get("support")
        resistance = snapshot.get("resistance")

        if bias == "BULLISH":
            if vwap and close:
                invalidation = min(_safe(vwap), _safe(support) if support else float('inf'))
                result.invalidation = f"NIFTY falls below VWAP ({_safe(vwap):.2f})"
            else:
                result.invalidation = "NIFTY falls below VWAP"
            result.stop_price = _safe(vwap) if vwap else None
        elif bias == "BEARISH":
            if vwap and close:
                invalidation = max(_safe(vwap), _safe(resistance) if resistance else 0)
                result.invalidation = f"NIFTY regains VWAP ({_safe(vwap):.2f})"
            else:
                result.invalidation = "NIFTY regains VWAP"
            result.stop_price = _safe(vwap) if vwap else None
        elif bias == "RANGE":
            result.invalidation = "Price breaks outside support/resistance range"
            result.stop_price = None
        else:
            _check(result, "invalidation_defined", False, "MIXED bias needs defined invalidation")
            return

        _check(result, "invalidation_defined", bool(result.invalidation),
               f"invalidation={result.invalidation}")

    def _check_risk(self, result: QualificationResult, snapshot: dict, outlook: dict, options_data: dict):
        entry = snapshot.get("close")
        stop = result.stop_price
        target_offset_pct = STRATEGY_BY_BIAS.get(outlook.get("bias", "MIXED"), {}).get("default_target_offset_pct", 1.5) if outlook else 1.5
        invalidation_offset_pct = STRATEGY_BY_BIAS.get(outlook.get("bias", "MIXED"), {}).get("default_invalidation_offset_pct", 0.5) if outlook else 0.5

        if not entry or not stop:
            _check(result, "risk_calculable", False, "Missing entry or stop")
            return

        entry_val = _safe(entry)
        stop_val = _safe(stop)
        risk_points = abs(entry_val - stop_val)

        if risk_points <= 0:
            _check(result, "risk_calculable", False, "Risk points = 0")
            return

        target_val = entry_val * (1 + target_offset_pct / 100) if outlook and outlook.get("bias") == "BULLISH" else \
                     entry_val * (1 - target_offset_pct / 100) if outlook and outlook.get("bias") == "BEARISH" else \
                     entry_val * (1 + target_offset_pct / 100)

        reward_points = abs(target_val - entry_val)
        rr = reward_points / risk_points if risk_points > 0 else 0

        result.entry_price = entry_val
        result.stop_price = stop_val
        result.target_price = target_val
        result.risk_points = risk_points
        result.reward_points = reward_points
        result.risk_reward = rr

        _check(result, "risk_calculable", True, f"entry={entry_val}, stop={stop_val}, R:R={rr:.2f}")

        min_rr = self.risk_config.get("min_risk_reward", 1.5)
        _check(result, "risk_reward_acceptable", rr >= min_rr,
               f"R:R={rr:.2f}, min={min_rr}")

        max_loss = self.risk_config.get("capital", 500000) * self.risk_config.get("max_risk_per_trade_pct", 0.5) / 100
        _check(result, "risk_within_limits", risk_points <= max_loss,
               f"risk={risk_points}, max={max_loss}")

    def _check_options_data(self, result: QualificationResult, options_data: dict, outlook: dict, evidence: dict = None):
        bias = outlook.get("bias", "MIXED") if outlook else "MIXED"
        if bias not in ("BULLISH", "BEARISH"):
            _check(result, "options_not_required", True, f"bias={bias}, no options needed")
            return

        evidence_options_available = False
        if evidence and evidence.get("groups", {}).get("options", {}).get("availability") == "LIVE":
            evidence_options_available = True

        if evidence_options_available:
            _check(result, "options_data_available", True, "Options available in evidence")
            result.data_availability["options"] = "LIVE"
            return

        if not options_data:
            _check(result, "options_data_available", False, "No options data provided")
            return

        has_chains = bool(options_data.get("option_chain") or options_data.get("strikes") or options_data.get("expiry"))
        has_pcr = options_data.get("pcr") is not None
        has_oi = options_data.get("call_oi") is not None or options_data.get("put_oi") is not None

        has_options = has_chains or has_pcr or has_oi
        _check(result, "options_data_available", has_options,
               f"chain={has_chains}, pcr={has_pcr}, oi={has_oi}")

        if not has_options:
            result.data_availability["options"] = "UNAVAILABLE"

    def _check_daily_risk(self, result: QualificationResult, instrument: str):
        result.daily_risk_available = True
        result.daily_risk_reason = "Risk configuration available"
        _check(result, "daily_risk_available", True, "Configured")

    def _check_active_trade(self, result: QualificationResult, active_trade: dict):
        if active_trade and active_trade.get("status") in ("OPEN", "WAITING_ENTRY"):
            result.active_trade_exists = True
            _check(result, "no_active_trade_exists", False,
                   f"Active trade {active_trade.get('trade_id', 'unknown')} exists")
        else:
            result.active_trade_exists = False
            _check(result, "no_active_trade_exists", True, "No active trade")

    def _check_data_availability(self, result: QualificationResult, snapshot: dict, evidence: dict, options_data: dict):
        missing = []
        if not snapshot.get("close"):
            missing.append("close")
        if not snapshot.get("vwap"):
            missing.append("vwap")
        if not snapshot.get("rsi"):
            missing.append("rsi")
        if evidence and evidence.get("overall", {}).get("overall_signal") == "INSUFFICIENT_DATA":
            missing.append("evidence")
        if options_data and not (options_data.get("option_chain") or options_data.get("strikes")):
            if result.direction in ("BULLISH", "BEARISH"):
                missing.append("options_chain")

        result.data_availability["missing_fields"] = missing
        _check(result, "core_data_available", len(missing) == 0, f"missing={missing}")

    def _determine_strategy(self, result: QualificationResult, outlook: dict, options_data: dict):
        if result.trade_status != "TRADE":
            result.strategy = None
            return

        bias = outlook.get("bias", "MIXED") if outlook else "MIXED"
        strategy_info = STRATEGY_BY_BIAS.get(bias, {})
        result.strategy = strategy_info.get("strategy")
        result.direction = strategy_info.get("direction", "NEUTRAL")

        if not result.strategy:
            result.trade_status = "NO_TRADE"
            result.rejection_reasons.append("no_strategy_for_bias")
            result.reason = f"NO_TRADE: No deterministic strategy for {bias}"


def qualify_trade(
    instrument: str,
    snapshot: dict,
    evidence: dict,
    market_state: dict,
    outlook: dict,
    options_data: dict = None,
    active_trade: dict = None,
    risk_config: dict = None,
) -> dict:
    engine = TradeQualificationEngine(risk_config=risk_config)
    result = engine.qualify(
        instrument, snapshot, evidence, market_state, outlook,
        options_data=options_data, active_trade=active_trade,
    )
    return result.to_dict()
