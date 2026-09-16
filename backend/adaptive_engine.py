from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("tradingai.adaptive")


def _safe(v, default=0.0):
    try:
        if v is None:
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def _classify_vix(vix_val):
    if vix_val is None or vix_val <= 0:
        return "UNKNOWN", "N/A"
    if vix_val < 11:
        return "VERY LOW", "Low volatility environment"
    if vix_val < 13:
        return "LOW", "Comfortable for risk-taking"
    if vix_val < 16:
        return "NORMAL", "Balanced volatility"
    if vix_val < 20:
        return "ELEVATED", "Above-average caution"
    if vix_val < 25:
        return "HIGH", "High fear, define risk"
    return "EXTREME", "Extreme fear, minimum risk"


def _classify_adx(adx_val):
    if adx_val is None or adx_val <= 0:
        return "UNKNOWN", 0.0
    if adx_val > 45:
        return "STRONG", 1.0
    if adx_val > 30:
        return "MODERATE", 0.7
    if adx_val > 25:
        return "WEAK", 0.4
    return "ABSENT", 0.1


def _classify_rsi(rsi_val):
    if rsi_val is None:
        return "UNKNOWN", 0.0
    if rsi_val >= 70:
        return "OVERBOUGHT", -0.3
    if rsi_val > 60:
        return "BULLISH", 0.3
    if rsi_val >= 40:
        return "NEUTRAL", 0.0
    if rsi_val > 30:
        return "BEARISH", -0.3
    return "OVERSOLD", 0.3


def _trend_score(price, ema20, ema50, ema200):
    scores = []
    if price and ema20 and price > ema20:
        scores.append(1)
    elif price and ema20 and price < ema20:
        scores.append(-1)
    if price and ema50 and price > ema50:
        scores.append(1)
    elif price and ema50 and price < ema50:
        scores.append(-1)
    if price and ema200 and price > ema200:
        scores.append(1)
    elif price and ema200 and price < ema200:
        scores.append(-1)
    if not scores:
        return "UNKNOWN", 0.0
    total = sum(scores)
    if total >= 2:
        return "UPTREND", min(1.0, 0.5 + len(scores) * 0.1)
    if total <= -2:
        return "DOWNTREND", min(1.0, 0.5 + len(scores) * 0.1)
    return "MIXED", 0.3


def _vwap_signal(price, vwap):
    if not price or not vwap:
        return "UNKNOWN", 0.0
    diff = (price - vwap) / vwap * 100 if vwap else 0
    if diff > 0.3:
        return "ABOVE", 0.6
    if diff < -0.3:
        return "BELOW", 0.6
    return "AT", 0.2


def _momentum_signal(macd, signal):
    if macd is None or signal is None:
        return "UNKNOWN", 0.0
    diff = macd - signal
    if diff > 0:
        return "BULLISH", 0.5
    if diff < 0:
        return "BEARISH", 0.5
    return "NEUTRAL", 0.1


def _cpr_signal(cpr_type, spot, cpr_value):
    if not cpr_value or not spot:
        return "UNKNOWN", 0.0
    if cpr_type == "BULLISH":
        return "ABOVE_BULLISH", 0.5
    if cpr_type == "BEARISH":
        return "BELOW_BEARISH", 0.5
    return "NEUTRAL", 0.2


def _gap_signal(gap_pct, gap_fill):
    if gap_pct is None or gap_fill is None:
        return "UNKNOWN", 0.0
    if gap_pct >= 0.5 and gap_fill < 50:
        return "UNFILLED_BULLISH", 0.4
    if gap_pct <= -0.5 and gap_fill < 50:
        return "UNFILLED_BEARISH", 0.4
    if gap_pct >= 0.5 and gap_fill >= 90:
        return "FILLED_BULLISH", 0.2
    if gap_pct <= -0.5 and gap_fill >= 90:
        return "FILLED_BEARISH", 0.2
    return "NEUTRAL", 0.1


def classify_market_structure(data: dict) -> dict:
    """Classify market structure from validated data.

    Returns structured classification with all adaptive fields.
    Data must come from validated sources — no fabricated values.
    """
    price = _safe(data.get("price"))
    ema20 = _safe(data.get("ema20"))
    ema50 = _safe(data.get("ema50"))
    ema200 = _safe(data.get("ema200"))
    vwap = _safe(data.get("vwap"))
    adx = _safe(data.get("adx"))
    rsi = _safe(data.get("rsi"))
    macd = _safe(data.get("macd"))
    macd_signal = _safe(data.get("macd_signal"))
    cpr_type = data.get("cpr_type", "UNKNOWN")
    cpr_value = _safe(data.get("cpr_value"))
    vix = data.get("vix")
    vix_val = _safe(vix) if vix is not None else None
    gap_pct = data.get("gap_pct") if data.get("gap_available") else None
    gap_fill = data.get("gap_fill_pct") if data.get("gap_available") else None
    breadth = data.get("breadth_ratio")
    support = data.get("support", [])
    resistance = data.get("resistance", [])
    data_state = data.get("data_state", "LIVE")
    options_available = data.get("options_available", False)

    _trend_label, trend_score = _trend_score(price, ema20, ema50, ema200)
    _vwap_label, vwap_score = _vwap_signal(price, vwap)
    _adx_label, adx_score = _classify_adx(adx)
    _rsi_label, rsi_score = _classify_rsi(rsi)
    _macd_label, macd_score = _momentum_signal(macd, macd_signal)
    _gap_label, gap_score = _gap_signal(gap_pct, gap_fill)

    vix_regime, vix_note = _classify_vix(vix_val)

    supporting = []
    conflicting = []

    if _trend_label == "UPTREND":
        supporting.append(f"Price above EMA20/50 (trend: {_trend_label})")
    elif _trend_label == "DOWNTREND":
        supporting.append(f"Price below EMA20/50 (trend: {_trend_label})")

    if _vwap_label == "ABOVE":
        supporting.append(f"Price above VWAP")
    elif _vwap_label == "BELOW":
        supporting.append(f"Price below VWAP")

    if _adx_label == "STRONG":
        supporting.append(f"ADX {adx:.0f} confirms strong trend")
    elif _adx_label == "ABSENT":
        conflicting.append(f"ADX {adx:.0f} — no trend strength")

    if _rsi_label == "BULLISH":
        supporting.append(f"RSI {rsi:.0f} — upward momentum")
    elif _rsi_label == "BEARISH":
        supporting.append(f"RSI {rsi:.0f} — downward momentum")
    elif _rsi_label == "OVERBOUGHT":
        conflicting.append(f"RSI {rsi:.0f} — overbought, momentum weakening")
    elif _rsi_label == "OVERSOLD":
        supporting.append(f"RSI {rsi:.0f} — oversold, bounce possible")

    if _macd_label == "BULLISH":
        supporting.append("MACD above signal — momentum positive")
    elif _macd_label == "BEARISH":
        supporting.append("MACD below signal — momentum negative")

    if vix_regime in ("HIGH", "EXTREME"):
        conflicting.append(f"VIX {vix_val:.1f} ({vix_regime}) — elevated risk")
    elif vix_regime in ("VERY LOW", "LOW"):
        supporting.append(f"VIX {vix_val:.1f} ({vix_regime}) — low risk environment")

    if _gap_label != "NEUTRAL" and gap_pct is not None:
        supporting.append(f"Gap {_gap_label} — {gap_pct:+.2f}%")

    if breadth is not None:
        if breadth > 1.2:
            supporting.append(f"Breadth ratio {breadth:.2f} — healthy advance")
        elif breadth < 0.8:
            conflicting.append(f"Breadth ratio {breadth:.2f} — broad selling")

    if cpr_type == "BULLISH" and price and cpr_value and price > cpr_value:
        supporting.append(f"CPR bullish, price above {cpr_value:,.2f}")
    elif cpr_type == "BEARISH" and price and cpr_value and price < cpr_value:
        supporting.append(f"CPR bearish, price below {cpr_value:,.2f}")

    # ─── MARKET STRUCTURE CLASSIFICATION ───
    # Decision tree — condition-driven, not forced directional

    trend_up = _trend_label == "UPTREND"
    trend_down = _trend_label == "DOWNTREND"
    trend_mixed = _trend_label == "MIXED" or _trend_label == "UNKNOWN"
    adx_strong = _adx_label in ("STRONG", "MODERATE")
    rsi_bull = _rsi_label in ("BULLISH", "OVERSOLD")
    rsi_bear = _rsi_label in ("BEARISH", "OVERBOUGHT")
    vwap_above = _vwap_label == "ABOVE"
    vwap_below = _vwap_label == "BELOW"
    macd_pos = _macd_label == "BULLISH"
    gap_bull = gap_score >= 0.3
    gap_bear = gap_score <= -0.3

    structure = "SIDEWAYS"
    structure_confidence = 0.3

    if trend_up and adx_strong and vwap_above and (rsi_bull or macd_pos):
        structure = "TRENDING_BULLISH"
        structure_confidence = min(1.0, 0.5 + trend_score * 0.3 + vwap_score * 0.1)
    elif trend_down and adx_strong and vwap_below and (rsi_bear or macd_pos is False):
        structure = "TRENDING_BEARISH"
        structure_confidence = min(1.0, 0.5 + trend_score * 0.3 + vwap_score * 0.1)
    elif trend_up and not adx_strong and rsi_bull:
        structure = "SIDEWAYS_TO_BULLISH"
        structure_confidence = 0.4
    elif trend_down and not adx_strong and rsi_bear:
        structure = "SIDEWAYS_TO_BEARISH"
        structure_confidence = 0.4
    elif trend_mixed and adx_strong and vwap_above and rsi_bull:
        structure = "SIDEWAYS_TO_BULLISH"
        structure_confidence = 0.45
    elif trend_mixed and adx_strong and vwap_below and rsi_bear:
        structure = "SIDEWAYS_TO_BEARISH"
        structure_confidence = 0.45
    elif trend_mixed and vwap_above and macd_pos and not rsi_bear:
        structure = "SIDEWAYS_TO_BULLISH"
        structure_confidence = 0.35
    elif trend_mixed and vwap_below and not macd_pos and not rsi_bull:
        structure = "SIDEWAYS_TO_BEARISH"
        structure_confidence = 0.35
    elif trend_mixed and not adx_strong:
        structure = "SIDEWAYS"
        structure_confidence = 0.5
    elif adx_strong and trend_mixed and not vwap_above and not vwap_below:
        structure = "VOLATILE_EXPANSION"
        structure_confidence = 0.4
    elif vix_regime in ("EXTREME", "HIGH") and trend_mixed:
        structure = "VOLATILE_EXPANSION"
        structure_confidence = 0.5

    # ─── DIRECTIONAL BIAS ───
    # Independent from market structure — represents directional tendency

    bias = "NEUTRAL"
    bias_score = 0.0

    if structure in ("TRENDING_BULLISH",):
        bias = "BULLISH"
        bias_score = min(0.9, 0.5 + trend_score * 0.3)
    elif structure in ("TRENDING_BEARISH",):
        bias = "BEARISH"
        bias_score = min(0.9, 0.5 + trend_score * 0.3)
    elif structure == "SIDEWAYS_TO_BULLISH":
        bias = "MILD_BULLISH"
        bias_score = 0.4
    elif structure == "SIDEWAYS_TO_BEARISH":
        bias = "MILD_BEARISH"
        bias_score = 0.4
    elif structure == "VOLATILE_EXPANSION":
        if gap_bull and not gap_bear:
            bias = "MILD_BULLISH"
            bias_score = 0.35
        elif gap_bear and not gap_bull:
            bias = "MILD_BEARISH"
            bias_score = 0.35
        else:
            bias = "MIXED"
            bias_score = 0.2
    elif structure == "SIDEWAYS":
        if rsi_bull and vwap_above:
            bias = "MILD_BULLISH"
            bias_score = 0.3
        elif rsi_bear and vwap_below:
            bias = "MILD_BEARISH"
            bias_score = 0.3
        else:
            bias = "NEUTRAL"
            bias_score = 0.15

    # Override: if conflicting factors dominate, bias = MIXED
    if len(conflicting) >= 2 and len(supporting) <= 1:
        bias = "MIXED"
        bias_score = 0.15

    # ─── TRADE CLASSIFICATION ───

    trade_class = "NO_TRADE"

    if structure in ("TRENDING_BULLISH", "SIDEWAYS_TO_BULLISH") and bias in ("BULLISH", "MILD_BULLISH") and adx_strong:
        trade_class = "DIRECTIONAL"
    elif structure in ("TRENDING_BEARISH", "SIDEWAYS_TO_BEARISH") and bias in ("BEARISH", "MILD_BEARISH") and adx_strong:
        trade_class = "DIRECTIONAL"
    elif structure in ("SIDEWAYS_TO_BULLISH", "SIDEWAYS_TO_BEARISH") and bias in ("MILD_BULLISH", "MILD_BEARISH") and not adx_strong:
        trade_class = "MILD_DIRECTIONAL"
    elif structure == "SIDEWAYS" and bias == "NEUTRAL" and adx_strong and options_available:
        trade_class = "NON_DIRECTIONAL"
    elif structure == "SIDEWAYS" and bias in ("MILD_BULLISH", "MILD_BEARISH") and not adx_strong:
        trade_class = "MILD_DIRECTIONAL"

    # ─── TRADE STATUS ───

    trade_status = "NO_TRADE"

    if trade_class == "DIRECTIONAL":
        if adx_strong and rsi_bull and vwap_above and structure == "TRENDING_BULLISH":
            trade_status = "ACTIVE"
        elif structure == "TRENDING_BULLISH" and (not rsi_bull or not vwap_above):
            trade_status = "WAIT_FOR_PULLBACK"
        elif structure == "SIDEWAYS_TO_BULLISH":
            trade_status = "WAIT_FOR_CONFIRMATION"
        elif structure == "SIDEWAYS_TO_BEARISH" and bias == "MILD_BEARISH":
            trade_status = "WAIT_FOR_CONFIRMATION"
        else:
            trade_status = "CONDITIONAL"
    elif trade_class == "MILD_DIRECTIONAL":
        trade_status = "CONDITIONAL"
    elif trade_class == "NON_DIRECTIONAL":
        trade_status = "CONDITIONAL"
    elif trade_class == "NO_TRADE":
        if vix_regime in ("EXTREME", "HIGH"):
            trade_status = "NO_TRADE"
        elif data_state in ("UNAVAILABLE", "ERROR", "STALE"):
            trade_status = "NO_TRADE"
        elif len(supporting) == 0 and len(conflicting) >= 1:
            trade_status = "NO_TRADE"
        else:
            trade_status = "NO_TRADE"

    # ─── ENTRY TRIGGER ───

    entry_trigger = "No valid entry trigger"

    if trade_status == "ACTIVE":
        entry_trigger = f"Entry active — {price:,.2f} holding above VWAP with positive momentum"
    elif trade_status == "WAIT_FOR_CONFIRMATION":
        if structure == "SIDEWAYS_TO_BULLISH":
            entry_trigger = f"Wait for 15-min close above nearest resistance ({resistance[0] if resistance else '—'}) with volume confirmation"
        elif structure == "SIDEWAYS_TO_BEARISH":
            entry_trigger = f"Wait for 15-min close below nearest support ({support[0] if support else '—'}) with volume confirmation"
        elif structure == "TRENDING_BULLISH":
            entry_trigger = f"Wait for pullback to support ({support[0] if support else '—'}) before adding"
        else:
            entry_trigger = "Wait for trend confirmation"
    elif trade_status == "WAIT_FOR_PULLBACK":
        entry_trigger = f"Wait for pullback to VWAP ({vwap:,.2f}) or nearest support"
    elif trade_status == "CONDITIONAL":
        if trade_class == "MILD_DIRECTIONAL":
            entry_trigger = f"Conditional — requires breakout above {resistance[0] if resistance else '—'} or breakdown below {support[0] if support else '—'}"
        elif trade_class == "NON_DIRECTIONAL":
            entry_trigger = f"Conditional — range trade between {support[0] if support else '—'} and {resistance[0] if resistance else '—'}"
    else:
        entry_trigger = "No valid setup — conditions not satisfied"

    # ─── CONFIRMATION CONDITIONS ───

    confirmation = []
    if trade_status == "WAIT_FOR_CONFIRMATION" or trade_status == "CONDITIONAL":
        if vwap_above:
            confirmation.append("Price above VWAP")
        if macd_pos:
            confirmation.append("MACD momentum positive")
        if adx_strong:
            confirmation.append(f"ADX {adx:.0f} confirms trend")
        if rsi_bull:
            confirmation.append(f"RSI {rsi:.0f} supports direction")
        if gap_bull:
            confirmation.append("Gap unfilled — continuation likely")
    elif trade_status == "ACTIVE":
        confirmation = ["Entry confirmed by trend, momentum, and VWAP"]

    # ─── INVALIDATION ───

    invalidation = "Key level breach"
    if structure == "TRENDING_BULLISH" or structure == "SIDEWAYS_TO_BULLISH":
        invalidation = f"Close below {support[1] if len(support) > 1 else (support[0] if support else '—')} invalidates bullish view"
    elif structure == "TRENDING_BEARISH" or structure == "SIDEWAYS_TO_BEARISH":
        invalidation = f"Close above {resistance[1] if len(resistance) > 1 else (resistance[0] if resistance else '—')} invalidates bearish view"
    elif structure == "SIDEWAYS":
        invalidation = f"Breakout below {support[0] if support else '—'} or above {resistance[0] if resistance else '—'}"
    elif structure == "VOLATILE_EXPANSION":
        invalidation = f"Close below {support[0] if support else '—'} or above {resistance[0] if resistance else '—'} with VIX spike"

    # ─── TARGET ───

    target = "Next resistance zone"
    if structure in ("TRENDING_BULLISH", "SIDEWAYS_TO_BULLISH"):
        target = f"R1 {resistance[0] if resistance else '—'} – R2 {resistance[1] if len(resistance) > 1 else '—'}"
    elif structure in ("TRENDING_BEARISH", "SIDEWAYS_TO_BEARISH"):
        target = f"S1 {support[0] if support else '—'} – S2 {support[1] if len(support) > 1 else '—'}"
    elif structure == "SIDEWAYS":
        target = f"Range: {support[0] if support else '—'} – {resistance[0] if resistance else '—'}"
    elif structure == "VOLATILE_EXPANSION":
        _spread = (max(resistance) - min(support)) if (support and resistance and isinstance(support[0], (int, float)) and isinstance(resistance[0], (int, float))) else 0
        target = f"ATR-based range: ±{_spread / 2:,.2f}"

    # ─── PREFERRED STRATEGY ───

    preferred_strategy = "No trade"
    if trade_class == "DIRECTIONAL":
        if bias == "BULLISH":
            preferred_strategy = "BULL CALL SPREAD"
        elif bias == "BEARISH":
            preferred_strategy = "BEAR PUT SPREAD"
    elif trade_class == "MILD_DIRECTIONAL":
        if bias == "MILD_BULLISH":
            preferred_strategy = "BULL PUT SPREAD"
        elif bias == "MILD_BEARISH":
            preferred_strategy = "BEAR CALL SPREAD"
    elif trade_class == "NON_DIRECTIONAL":
        preferred_strategy = "IRON_CONDOR"

    # ─── CONFIDENCE ───

    confidence = structure_confidence * 100
    if data_state in ("UNAVAILABLE", "ERROR", "STALE"):
        confidence *= 0.5
    if vix_regime in ("EXTREME", "HIGH"):
        confidence *= 0.8
    confidence = max(0, min(100, round(confidence)))

    return {
        "market_structure": structure,
        "structure_confidence": round(structure_confidence, 2),
        "directional_bias": bias,
        "bias_score": round(bias_score, 2),
        "trade_class": trade_class,
        "trade_status": trade_status,
        "entry_trigger": entry_trigger,
        "confirmation_conditions": confirmation,
        "invalidation": invalidation,
        "target_zone": target,
        "preferred_strategy": preferred_strategy,
        "confidence": confidence,
        "confidence_label": "MODEL_CONFIDENCE",
        "supporting_factors": supporting,
        "conflicting_factors": conflicting,
        "data_state": data_state,
        "vix_regime": vix_regime,
        "vix_note": vix_note,
        "trend": _trend_label,
        "adx_classification": _adx_label,
        "rsi_classification": _rsi_label,
        "vwap_signal": _vwap_label,
        "macd_signal": _macd_label,
    }


def adaptive_outlook(data: dict) -> dict:
    """Generate adaptive AI outlook from validated data.

    This is the deterministic fallback when LLM is unavailable.
    Produces the structured schema from the implementation prompt.
    """
    classified = classify_market_structure(data)

    interpretation = _build_interpretation(classified)

    return {
        "symbol": data.get("symbol", ""),
        "timestamp": data.get("timestamp", ""),
        "market_cycle": data.get("data_state", "LIVE"),
        "market_structure": classified["market_structure"],
        "directional_bias": classified["directional_bias"],
        "trade_class": classified["trade_class"],
        "trade_status": classified["trade_status"],
        "confidence": classified["confidence"],
        "confidence_label": classified["confidence_label"],
        "entry_trigger": classified["entry_trigger"],
        "confirmation_conditions": classified["confirmation_conditions"],
        "preferred_strategy": classified["preferred_strategy"],
        "invalidation": classified["invalidation"],
        "target_zone": classified["target_zone"],
        "supporting_factors": classified["supporting_factors"],
        "conflicting_factors": classified["conflicting_factors"],
        "risk_conditions": classified["conflicting_factors"] if classified["conflicting_factors"] else [],
        "options_data_state": "UNAVAILABLE" if not data.get("options_available", False) else "LIVE",
        "interpretation": interpretation,
        "data_quality": data.get("data_state", "VALID"),
        "structure_confidence": classified["structure_confidence"],
        "bias_score": classified["bias_score"],
        "trend": classified["trend"],
        "adx_classification": classified["adx_classification"],
        "rsi_classification": classified["rsi_classification"],
        "vwap_signal": classified["vwap_signal"],
        "macd_signal": classified["macd_signal"],
        "vix_regime": classified["vix_regime"],
        "vix_note": classified["vix_note"],
        "data_state": classified["data_state"],
        "data_quality": data.get("data_quality", "VALID"),
    }


def _build_interpretation(c: dict) -> str:
    """Convert structured classification to concise trader-readable text."""
    sym = ""
    structure = c["market_structure"].replace("_", " ").title()
    bias = c["directional_bias"].replace("_", " ").title()
    status = c["trade_status"].replace("_", " ").title()
    strategy = c["preferred_strategy"].replace("_", " ")

    parts = [f"{sym}remains {structure.lower()}."]

    if c["directional_bias"] == "MIXED":
        parts.append("Evidence is mixed — no clear directional edge.")
    elif c["directional_bias"] != "NEUTRAL":
        parts.append(f"Directional bias: {bias.lower()}.")

    if c["trade_status"] == "NO_TRADE":
        parts.append(f"No trade advised. {c['entry_trigger']}.")
    elif c["trade_status"] == "WAIT_FOR_CONFIRMATION":
        parts.append(f"Status: {status}. {c['entry_trigger']}.")
    elif c["trade_status"] == "WAIT_FOR_PULLBACK":
        parts.append(f"Status: {status}. {c['entry_trigger']}.")
    elif c["trade_status"] == "CONDITIONAL":
        parts.append(f"Status: {status}. {c['entry_trigger']}.")
    elif c["trade_status"] == "ACTIVE":
        parts.append(f"Status: {status}. Preferred approach: {strategy}.")

    if c["conflicting_factors"]:
        parts.append(f"Caution: {'; '.join(c['conflicting_factors'][:2])}.")

    return " ".join(parts)