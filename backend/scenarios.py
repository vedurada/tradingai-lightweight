from __future__ import annotations

from typing import Any, Optional


class ScenarioEngine:
    def generate(self, regime: str, support_levels: list, resistance_levels: list, current_price: float, adx: Optional[float] = None, vix_price: float = 0) -> dict[str, Any]:
        bullish = {"trigger": "Price breaks above resistance", "confirmation": "5-min close above resistance + volume", "target": resistance_levels[0] if resistance_levels else "N/A", "invalidation": "Below pivot", "strategy_environment": "TRENDING_BULLISH", "probability": 0.3}
        bearish = {"trigger": "Price breaks below support", "confirmation": "5-min close below support + volume", "target": support_levels[-1] if support_levels else "N/A", "invalidation": "Above pivot", "strategy_environment": "TRENDING_BEARISH", "probability": 0.3}
        range_condition = f"Price between {support_levels[-1] if support_levels else 'N/A'} and {resistance_levels[0] if resistance_levels else 'N/A'}"
        range_scenario = {"condition": range_condition, "strategy_environment": "Iron Condor / Butterfly", "invalidation": "Breakout above resistance or breakdown below support", "probability": 0.2}
        breakout_scenario = {"trigger": "Volume spike + close beyond support/resistance", "confirmation": "2 consecutive closes beyond level", "target": "Next major level", "invalidation": "Return to range", "strategy_environment": "BREAKOUT", "probability": 0.15}
        reversal_scenario = {"trigger": "RSI divergence + price at support/resistance", "confirmation": "MACD crossover + volume increase", "target": "Opposite side of range", "invalidation": "Continue trend", "strategy_environment": "REVERSAL", "probability": 0.05}
        if regime == "TRENDING_BULLISH":
            bullish["trigger"] = "Price above VWAP with RSI < 70"
            bullish["confirmation"] = "Break above resistance with volume"
            bullish["probability"] = 0.5
            bearish["probability"] = 0.2
            range_scenario["probability"] = 0.2
        elif regime == "TRENDING_BEARISH":
            bearish["trigger"] = "Price below VWAP with RSI > 30"
            bearish["confirmation"] = "Break below support with volume"
            bearish["probability"] = 0.5
            bullish["probability"] = 0.2
            range_scenario["probability"] = 0.2
        elif regime == "HIGH_VOLATILITY":
            range_scenario["strategy_environment"] = "Reduce risk / wait"
            range_scenario["probability"] = 0.1
            breakout_scenario["probability"] = 0.4
            bullish["probability"] = 0.25
            bearish["probability"] = 0.25
        elif regime == "RANGE_BOUND":
            range_scenario["probability"] = 0.4
            breakout_scenario["probability"] = 0.35
            bullish["probability"] = 0.15
            bearish["probability"] = 0.1
        if adx and adx > 40:
            breakout_scenario["probability"] += 0.1
        if vix_price > 25:
            breakout_scenario["probability"] += 0.05
        return {"bullish": bullish, "bearish": bearish, "range": range_scenario, "breakout": breakout_scenario, "reversal": reversal_scenario}