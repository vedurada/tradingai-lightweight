from __future__ import annotations

from typing import Optional, Dict, Any


def expected_move(price: float, atr: Optional[float], vix: Optional[float]) -> Dict[str, Any]:
    """Expected daily range from ATR and VIX.

    Combines ATR-based range with VIX scaling for expected move.
    Returns: {"low": ..., "high": ..., "move_pct": ..., "basis": ...}
    """
    if price <= 0:
        return {"low": price, "high": price, "move_pct": 0.0, "basis": "no_price", "price": price}

    atr_move = 0.0
    vix_move = 0.0
    sources = []

    if atr is not None and atr > 0:
        atr_move = atr / price * 100
        sources.append("atr")

    if vix is not None and vix > 0:
        vix_move = vix * 0.04
        sources.append("vix")

    if atr_move > 0 and vix_move > 0:
        move_pct = max(atr_move, vix_move)
        basis = f"max({','.join(sources)})"
    elif atr_move > 0:
        move_pct = atr_move
        basis = "atr"
    elif vix_move > 0:
        move_pct = vix_move
        basis = "vix"
    else:
        move_pct = 1.0
        basis = "default"

    half_move = price * move_pct / 200
    return {
        "low": round(price - half_move, 2),
        "high": round(price + half_move, 2),
        "move_pct": round(move_pct, 2),
        "basis": basis,
        "price": round(price, 2),
    }


def bollinger_range(bb: Optional[Dict[str, Any]], price: float) -> Dict[str, Any]:
    """Bollinger Band expected range."""
    if not bb or not isinstance(bb, dict):
        return expected_move(price, None, None)
    upper = bb.get("upper")
    lower = bb.get("lower")
    if upper is None or lower is None or price <= 0:
        return expected_move(price, None, None)
    return {
        "low": round(lower, 2),
        "high": round(upper, 2),
        "move_pct": round((upper - lower) / price * 100, 2),
        "basis": "bollinger",
        "price": round(price, 2),
    }


def support_resistance_range(sr: Optional[Dict[str, Any]], price: float) -> Dict[str, Any]:
    """Range bounded by support/resistance levels."""
    if not sr or not isinstance(sr, dict):
        return expected_move(price, None, None)
    support = sr.get("support", [])
    resistance = sr.get("resistance", [])
    nearest_support = max([s for s in support if s < price], default=None)
    nearest_resistance = min([r for r in resistance if r > price], default=None)
    if nearest_support and nearest_resistance:
        return {
            "low": round(nearest_support, 2),
            "high": round(nearest_resistance, 2),
            "move_pct": round((nearest_resistance - nearest_support) / price * 100, 2),
            "basis": "sr",
            "price": round(price, 2),
        }
    return expected_move(price, None, None)


def compute_expected_range(indicators: Optional[Dict[str, Any]], price: float, vix_price: Optional[float] = None) -> Dict[str, Any]:
    """Compute expected range from multiple sources, returning the most appropriate one.

    Priority: Bollinger > SR > ATR+VIX
    """
    if not indicators or not isinstance(indicators, dict):
        return expected_move(price, None, vix_price)

    bb = indicators.get("bollinger_bands")
    sr = indicators.get("support_resistance")
    atr = indicators.get("atr")

    if bb and isinstance(bb, dict) and bb.get("upper") and bb.get("lower"):
        return bollinger_range(bb, price)

    sr_range = support_resistance_range(sr, price)
    if sr_range and sr_range.get("low", price) < price and sr_range.get("high", price) > price:
        return sr_range

    return expected_move(price, atr, vix_price)
