from __future__ import annotations

from typing import Any, Optional


class ScenarioEngine:
    def generate(self, regime: str, support_levels: list, resistance_levels: list, current_price: float) -> dict[str, Any]:
        bullish = {"trigger": "Price breaks above resistance", "confirmation": "5-min close above resistance + volume", "target": resistance_levels[0] if resistance_levels else "N/A", "invalidation": "Below pivot"}
        bearish = {"trigger": "Price breaks below support", "confirmation": "5-min close below support + volume", "target": support_levels[-1] if support_levels else "N/A", "invalidation": "Above pivot"}
        range_condition = f"Price between {support_levels[-1] if support_levels else 'N/A'} and {resistance_levels[0] if resistance_levels else 'N/A'}"
        range_scenario = {"condition": range_condition, "strategy_environment": "Iron Condor / Butterfly", "invalidation": "Breakout above resistance or breakdown below support"}
        if regime == "TRENDING_BULLISH":
            bullish["trigger"] = "Price above VWAP with RSI < 70"
            bullish["confirmation"] = "Break above resistance with volume"
        elif regime == "TRENDING_BEARISH":
            bearish["trigger"] = "Price below VWAP with RSI > 30"
            bearish["confirmation"] = "Break below support with volume"
        elif regime == "HIGH_VOLATILITY":
            range_scenario["strategy_environment"] = "Reduce risk / wait"
        return {"bullish": bullish, "bearish": bearish, "range": range_scenario}