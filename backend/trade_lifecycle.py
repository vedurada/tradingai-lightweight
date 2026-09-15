from __future__ import annotations

"""Trade Lifecycle Engine - Intraday Trade Setup Engine.

Combines Market State + Gap Analysis + Options State → Trade Setup.

Key principle: The AI can say WAIT. Not every market condition deserves a trade.
The trade lifecycle has deterministic stages, each with immutable timestamp.

Stages:
  DETECTED → TRIGGER → CONFIRMATION → ENTRY_WINDOW → ACTIVE → TARGET/INVALIDATED/EXIT

Every transition has:
  - timestamp (when it happened, or None if not reached)
  - status (ACTIVE, WAIT, NO_SETUP, COMPLETE)
  - evidence (what data shows, NOT guarantees)
  - uncertainty (what's unknown)
"""
import json
from typing import Any, Dict, List, Optional


class TradeStage:
    """A single stage in the trade lifecycle. Immutable."""

    def __init__(self, name: str, status: str, *,
                 timestamp: Optional[str] = None,
                 evidence: List[str] = None,
                 uncertainty: List[str] = None,
                 levels: Optional[Dict[str, Any]] = None,
                 reason: str = ""):
        self.name = name
        self.status = status  # ACTIVE, WAIT, NO_SETUP, COMPLETE, PENDING
        self.timestamp = timestamp
        self.evidence = sorted(evidence or [])
        self.uncertainty = sorted(uncertainty or [])
        self.levels = levels or {}
        self.reason = reason

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "timestamp": self.timestamp,
            "evidence": self.evidence,
            "uncertainty": self.uncertainty,
            "levels": self.levels,
            "reason": self.reason,
        }


class TradeSetup:
    """Immutable trade setup for a symbol.

    Contains the full trade lifecycle with timestamps at each stage.
    Once created, never modified.
    """

    STAGES = ["DETECTED", "TRIGGER", "CONFIRMATION", "ENTRY_WINDOW", "ACTIVE", "COMPLETE"]
    EXIT_REASONS = ["TARGET", "INVALIDATED", "EXIT", "NO_TRADE"]

    def __init__(self, symbol: str, timestamp: str, *,
                 current_stage: str,
                 trade_readiness: str,
                 stages: Dict[str, TradeStage],
                 evidence: List[str],
                 uncertainty: List[str],
                 data_quality: str,
                 setup_type: Optional[str] = None,
                 trigger_level: Optional[float] = None,
                 entry_window: Optional[Dict[str, float]] = None,
                 invalidation: Optional[float] = None,
                 target: Optional[float] = None,
                 confidence: Optional[int] = None,
                 gap_info: Optional[Dict[str, Any]] = None,
                 options_summary: Optional[Dict[str, Any]] = None):
        self.symbol = symbol
        self.timestamp = timestamp
        self.current_stage = current_stage
        self.trade_readiness = trade_readiness  # GO, WAIT, NO_SETUP
        self.stages = stages
        self.evidence = sorted(evidence or [])
        self.uncertainty = sorted(uncertainty or [])
        self.data_quality = data_quality
        self.setup_type = setup_type
        self.trigger_level = trigger_level
        self.entry_window = entry_window
        self.invalidation = invalidation
        self.target = target
        self.confidence = confidence
        self.gap_info = gap_info
        self.options_summary = options_summary

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp,
            "current_stage": self.current_stage,
            "trade_readiness": self.trade_readiness,
            "stages": {name: stage.to_dict() for name, stage in self.stages.items()},
            "evidence": self.evidence,
            "uncertainty": self.uncertainty,
            "data_quality": self.data_quality,
            "setup_type": self.setup_type,
            "trigger_level": self.trigger_level,
            "entry_window": self.entry_window,
            "invalidation": self.invalidation,
            "target": self.target,
            "confidence": self.confidence,
            "gap_info": self.gap_info,
            "options_summary": self.options_summary,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), default=str)

    def mobile_summary(self) -> dict[str, Any]:
        """Mobile-first: bias + readiness + key levels + lifecycle."""
        return {
            "symbol": self.symbol,
            "trade_readiness": self.trade_readiness,
            "current_stage": self.current_stage,
            "setup_type": self.setup_type,
            "confidence": self.confidence,
            "key_levels": {
                "trigger": self.trigger_level,
                "entry": self.entry_window,
                "invalidation": self.invalidation,
                "target": self.target,
            },
            "evidence": self.evidence[:5],
            "uncertainty": self.uncertainty[:3],
            "stages": {name: {"status": s.status, "reason": s.reason} for name, s in self.stages.items()},
        }


def _stage(name: str, status: str, *, reason: str = "", evidence: List[str] = None,
             uncertainty: List[str] = None, levels: Dict[str, Any] = None,
             timestamp: Optional[str] = None) -> TradeStage:
    """Helper to create a trade stage."""
    return TradeStage(
        name=name, status=status, reason=reason,
        evidence=evidence, uncertainty=uncertainty,
        levels=levels, timestamp=timestamp,
    )


def detect_trade_setup(symbol: str, market_state: Optional[dict],
                         options_state: Optional[dict], gap: Optional[dict],
                         timestamp: str = "", data_quality: str = "LIVE",
                         confidence_override: Optional[int] = None) -> TradeSetup:
    """Detect trade setup from market + options + gap data.

    Returns a TradeSetup with lifecycle stages. May return:
    - trade_readiness = "NO_SETUP" when conditions don't warrant a trade
    - trade_readiness = "WAIT" when conditions are forming but not ready
    - trade_readiness = "GO" when a trade setup is detected
    """
    stages: Dict[str, TradeStage] = {}
    evidence: List[str] = []
    uncertainty: List[str] = []
    trade_readiness = "NO_SETUP"
    current_stage = "DETECTED"
    setup_type = None
    trigger_level = None
    entry_window = None
    invalidation = None
    target = None
    confidence = confidence_override

    # ═══════════════════════════════════════════════
    # Stage 1: DETECTED
    # ═══════════════════════════════════════════════
    det_evidence = []
    det_uncertainty = []

    if market_state is None:
        det_uncertainty.append("Market state unavailable: cannot detect setup")
    elif gap is None:
        det_uncertainty.append("Gap data unavailable: cannot assess opening context")
    else:
        spot = market_state.get("spot") if market_state else None
        gap_pct = gap.get("gap_pct") if gap else None
        regime = None
        if market_state.get("regime"):
            regime = market_state["regime"].get("regime") if isinstance(market_state["regime"], dict) else market_state["regime"]
        bias = None
        if market_state.get("bias"):
            bias = market_state["bias"] if isinstance(market_state["bias"], str) else market_state["bias"].get("bias")

        if spot and gap_pct is not None:
            det_evidence.append(f"{symbol} at {spot} with {gap_pct}% gap")
            if regime:
                det_evidence.append(f"Regime: {regime}")
            if bias:
                det_evidence.append(f"Bias: {bias}")
        else:
            det_uncertainty.append("Price data incomplete for setup detection")

        # Decision at DETECTED stage: is there anything worth exploring?
        if gap_pct is not None and abs(gap_pct) >= 0.3:
            trade_readiness = "WAIT"
            current_stage = "DETECTED"
            det_evidence.append(f"Gap {gap_pct}% exceeds threshold - monitoring for trigger")
        elif gap_pct is not None and abs(gap_pct) < 0.3:
            det_evidence.append(f"Gap {gap_pct}% within normal range")
            # Small gap doesn't mean NO_SETUP - could still be trending
            if regime and any(x in str(regime).upper() for x in ["BULLISH", "BEARISH", "TRENDING"]):
                trade_readiness = "WAIT"
                current_stage = "DETECTED"
                det_evidence.append(f"Trend regime {regime} - monitoring for trigger")
            else:
                trade_readiness = "WAIT"
                current_stage = "DETECTED"
                det_evidence.append("No strong signal - monitoring")
        else:
            det_uncertainty.append("Cannot assess gap - setup detection incomplete")

    stages["DETECTED"] = _stage("DETECTED", trade_readiness,
                                  reason=det_evidence[0] if det_evidence else "Monitoring",
                                  evidence=det_evidence, uncertainty=det_uncertainty)

    # ═══════════════════════════════════════════════
    # Stage 2: TRIGGER
    # ═══════════════════════════════════════════════
    trigger_evidence = list(det_evidence)
    trigger_uncertainty = list(det_uncertainty)
    trigger_level = None
    trigger_status = "PENDING"

    if trade_readiness in ("WAIT", "GO") and gap is not None:
        gap_pct = gap.get("gap_pct")
        kind = gap.get("kind", "")
        cover = gap.get("cover_prob")

        if kind == "GAP UP" and gap_pct is not None:
            trigger_level = round(gap.get("high", 0) + gap_pct * 0.001 * gap.get("high", 0), 2) if gap.get("high") else None
            trigger_evidence.append(f"Gap up {gap_pct}% - bullish trigger if sustained above {trigger_level}")
            if cover is not None:
                if cover >= 70:
                    trigger_uncertainty.append(f"Gap cover probability {cover}% - may fill, reducing bullish setup")
                else:
                    trigger_evidence.append(f"Gap cover probability {cover}% - likely to sustain")
            trigger_status = "ACTIVE"

        elif kind == "GAP DOWN" and gap_pct is not None:
            trigger_level = round(gap.get("low", 0), 2) if gap.get("low") else None
            trigger_evidence.append(f"Gap down {gap_pct}% - watch for bounce at {trigger_level}")
            if cover is not None and cover >= 70:
                trigger_uncertainty.append(f"Gap likely to fill (cover {cover}%) - bearish case weakens")
            trigger_status = "ACTIVE"

        elif kind == "FLAT OPEN":
            trigger_evidence.append("Flat open - no gap trigger, watching for intraday break")
            trigger_status = "WAIT"

    elif trade_readiness == "NO_SETUP":
        trigger_status = "SKIPPED"
        trigger_evidence.append("No setup detected - trigger stage not applicable")

    stages["TRIGGER"] = _stage("TRIGGER", trigger_status,
                                 reason=trigger_evidence[0] if trigger_evidence else "Pending",
                                 evidence=trigger_evidence, uncertainty=trigger_uncertainty,
                                 levels={"trigger_level": trigger_level})

    # ═══════════════════════════════════════════════
    # Stage 3: CONFIRMATION
    # ═══════════════════════════════════════════════
    confirm_evidence = list(trigger_evidence)
    confirm_uncertainty = list(trigger_uncertainty)
    confirm_status = "PENDING"
    confirmation_levels = {}

    if trigger_status == "ACTIVE" and market_state is not None:
        # Check multiple confirmation signals
        regime = market_state.get("regime", {})
        if isinstance(regime, dict):
            regime_name = regime.get("regime", "")
        else:
            regime_name = str(regime)

        vwap = None
        indicators = market_state.get("indicators", {}) if market_state.get("indicators") else {}
        if isinstance(indicators, dict):
            vwap = indicators.get("vwap")

        if vwap:
            confirmation_levels["vwap"] = vwap
            confirm_evidence.append(f"VWAP: {vwap} - confirmation reference level")

        if regime_name and any(x in str(regime_name).upper() for x in ["BULLISH", "TRENDING"]):
            confirm_evidence.append(f"Regime {regime_name} confirms directional bias")
            confirm_status = "ACTIVE"
        elif regime_name and "BEARISH" in str(regime_name).upper():
            confirm_evidence.append(f"Regime {regime_name} - bearish confirmation")
            confirm_status = "ACTIVE"
        else:
            confirm_uncertainty.append(f"Regime {regime_name} unclear - confirmation weak")
            confirm_status = "WAIT"
    elif trigger_status == "WAIT":
        confirm_status = "WAIT"
        confirm_evidence.append("Trigger not yet fired - confirmation pending")
    elif trigger_status == "SKIPPED":
        confirm_status = "SKIPPED"

    stages["CONFIRMATION"] = _stage("CONFIRMATION", confirm_status,
                                      reason=confirm_evidence[0] if confirm_evidence else "Pending",
                                      evidence=confirm_evidence, uncertainty=confirm_uncertainty,
                                      levels=confirmation_levels)

    # ═══════════════════════════════════════════════
    # Stage 4: ENTRY WINDOW
    # ═══════════════════════════════════════════════
    entry_evidence = list(confirm_evidence)
    entry_uncertainty = list(confirm_uncertainty)
    entry_status = "PENDING"
    entry_window = None
    invalidation_val = None
    target_val = None

    if confirm_status == "ACTIVE" and market_state is not None and gap is not None:
        spot = market_state.get("spot") if market_state else None
        if not spot and gap.get("open"):
            spot = gap.get("open")

        if spot and trigger_level:
            if "GAP UP" in str(gap.get("kind", "")):
                invalidation_val = round(spot * 0.995, 2)
                target_val = round(trigger_level + (trigger_level - spot) * 2, 2)
                entry_window = {"low": round(spot, 2), "high": round(trigger_level, 2)}
                entry_evidence.append(f"Entry window: {entry_window['low']}-{entry_window['high']}")
                entry_evidence.append(f"Invalidation: {invalidation_val}")
                entry_evidence.append(f"Target: {target_val}")
                entry_status = "ACTIVE"
                setup_type = "BREAKOUT"
            elif "GAP DOWN" in str(gap.get("kind", "")):
                invalidation_val = round(spot * 1.005, 2)
                target_val = round(trigger_level - (spot - trigger_level) * 2, 2)
                entry_window = {"low": round(trigger_level, 2), "high": round(spot, 2)}
                entry_evidence.append(f"Entry window: {entry_window['low']}-{entry_window['high']}")
                entry_evidence.append(f"Invalidation: {invalidation_val}")
                entry_evidence.append(f"Target: {target_val}")
                entry_status = "ACTIVE"
                setup_type = "BOUNCE"
            else:
                entry_evidence.append("Flat open - entry window forming")
                entry_status = "WAIT"
                setup_type = "RANGE"
        else:
            entry_uncertainty.append("Cannot define entry window - price data incomplete")
            entry_status = "WAIT"
    elif trigger_status == "WAIT":
        entry_status = "WAIT"
        entry_evidence.append("Trigger not fired - entry window not defined")
    elif trigger_status == "SKIPPED":
        entry_status = "SKIPPED"

    stages["ENTRY_WINDOW"] = _stage("ENTRY_WINDOW", entry_status,
                                      reason=entry_evidence[0] if entry_evidence else "Pending",
                                      evidence=entry_evidence, uncertainty=entry_uncertainty,
                                      levels={"entry_window": entry_window,
                                              "invalidation": invalidation_val,
                                              "target": target_val})

    # ═══════════════════════════════════════════════
    # Stage 5: ACTIVE (if entry window is active)
    # ═══════════════════════════════════════════════
    active_status = "PENDING"
    if entry_status == "ACTIVE":
        active_status = "ACTIVE"
        active_evidence = list(entry_evidence)
        active_evidence.append("Trade setup active - monitoring for exit")
        active_uncertainty = list(entry_uncertainty)
        active_uncertainty.append("Outcome not determined - could be TARGET, INVALIDATED, or EXIT")
    elif entry_status == "WAIT":
        active_status = "WAIT"
        active_evidence = list(entry_evidence)
        active_evidence.append("Waiting for conditions to mature")
        active_uncertainty = list(entry_uncertainty)
    else:
        active_status = "SKIPPED"
        active_evidence = ["Setup not active"]
        active_uncertainty = ["No active setup"]

    stages["ACTIVE"] = _stage("ACTIVE", active_status,
                                reason=active_evidence[0] if active_evidence else "Pending",
                                evidence=active_evidence, uncertainty=active_uncertainty)

    # ═══════════════════════════════════════════════
    # Stage 6: COMPLETE
    # ═══════════════════════════════════════════════
    if active_status in ("ACTIVE", "WAIT"):
        complete_status = "PENDING"
        complete_reason = "Setup in progress"
    else:
        complete_status = "SKIPPED"
        complete_reason = "No active setup to complete"

    stages["COMPLETE"] = _stage("COMPLETE", complete_status,
                                  reason=complete_reason)

    # ═══════════════════════════════════════════════
    # Final assembly
    # ═══════════════════════════════════════════════
    # Build options summary if available
    options_summary = None
    if options_state:
        options_summary = {
            "pcr": options_state.get("pcr"),
            "atm": options_state.get("atm_strike"),
            "iv": options_state.get("iv_atm"),
            "max_pain": options_state.get("max_pain"),
            "bias": options_state.get("bias"),
            "confidence": options_state.get("confidence"),
        }
        if options_state.get("evidence"):
            for ev in options_state["evidence"][:3]:
                entry_evidence.append(f"Options: {ev}")

    # Gap info
    gap_info = None
    if gap:
        gap_info = {
            "gap_pct": gap.get("gap_pct"),
            "kind": gap.get("kind"),
            "fill_pct": gap.get("fill_pct"),
            "cover_prob": gap.get("cover_prob"),
        }

    # Evidence from all stages (deduplicated, ordered)
    seen = set()
    all_evidence = []
    for stage_name in TradeSetup.STAGES:
        if stage_name in stages and stages[stage_name].evidence:
            for ev in stages[stage_name].evidence:
                if ev not in seen:
                    seen.add(ev)
                    all_evidence.append(ev)
    # Add options evidence
    if options_state and options_state.get("evidence"):
        for ev in options_state["evidence"][:3]:
            labeled = f"Options: {ev}"
            if labeled not in seen:
                seen.add(labeled)
                all_evidence.append(labeled)
    evidence = all_evidence[:15]

    # Uncertainty (deduplicated)
    seen_u = set()
    all_uncertainty = []
    for stage_name in TradeSetup.STAGES:
        if stage_name in stages and stages[stage_name].uncertainty:
            for u in stages[stage_name].uncertainty:
                if u not in seen_u:
                    seen_u.add(u)
                    all_uncertainty.append(u)
    uncertainty = all_uncertainty[:5]

    # Determine final trade_readiness
    if entry_status == "ACTIVE":
        trade_readiness = "GO"
    elif entry_status == "WAIT":
        trade_readiness = "WAIT"
    elif trigger_status == "ACTIVE":
        trade_readiness = "WAIT"
    else:
        trade_readiness = "NO_SETUP"

    # Confidence from stages
    if confidence_override is not None:
        confidence = confidence_override
    elif market_state and market_state.get("confidence"):
        confidence = market_state["confidence"]
    else:
        confidence = None if trade_readiness != "GO" else 50

    return TradeSetup(
        symbol=symbol, timestamp=timestamp,
        current_stage=current_stage,
        trade_readiness=trade_readiness,
        stages=stages,
        evidence=evidence,
        uncertainty=uncertainty,
        data_quality=data_quality,
        setup_type=setup_type,
        trigger_level=trigger_level,
        entry_window=entry_window,
        invalidation=invalidation_val,
        target=target_val,
        confidence=confidence,
        gap_info=gap_info,
        options_summary=options_summary,
    )
