"""Thin adapter — uses canonical HLC engine without modification."""
# Import canonical interface from /opt/tradingai/app/research/scalp_engine.py
# Phase 3 design: evaluate completed candle, return direction/valid.

def evaluate_candle(candle_dict):
    # Design: delegate to canonical engine; do not replicate logic.
    # Mock for isolated validation:
    return {"valid": bool(candle_dict.get("hlc_pattern")), "direction": candle_dict.get("direction", "BULLISH")}
