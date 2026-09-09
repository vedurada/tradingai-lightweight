from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


class StrategyEngine:
    def select(self, regime: str, confidence: float, data_quality: str) -> dict[str, Any]:
        strategies = []
        position_size = self._position_size(confidence, data_quality)
        if regime == "TRENDING_BULLISH":
            strategies = [
                {"strategy": "Bull Call Spread", "market_condition": "Bullish trend", "expiry": "NEXT_WEEKLY", "legs": ["BUY ATM CALL", "SELL 1-2 OTM CALL"], "entry_trigger": "Price above VWAP, RSI < 70", "maximum_profit": "Strike width - premium", "maximum_loss": "Premium + costs", "breakeven": "Lower strike + premium", "stop_loss": "Below lower strike", "adjustment": "Roll up both legs", "exit": "At expiry or target", "strategy_environment": "TRENDING_BULLISH", "invalidation": "Price below VWAP or RSI > 75", "position_size": position_size},
                {"strategy": "Bull Put Spread", "market_condition": "Bullish trend", "expiry": "NEXT_WEEKLY", "legs": ["SELL OTM PUT", "BUY further OTM PUT"], "entry_trigger": "Price above VWAP, RSI < 70", "maximum_profit": "Premium received", "maximum_loss": "Strike width - premium", "breakeven": "Higher strike - premium", "stop_loss": "Below lower strike", "adjustment": "Roll down both legs", "exit": "At expiry or target", "strategy_environment": "TRENDING_BULLISH", "invalidation": "Price below lower put strike", "position_size": position_size},
            ]
        elif regime == "TRENDING_BEARISH":
            strategies = [
                {"strategy": "Bear Put Spread", "market_condition": "Bearish trend", "expiry": "NEXT_WEEKLY", "legs": ["BUY ATM PUT", "SELL 1-2 OTM PUT"], "entry_trigger": "Price below VWAP, RSI > 30", "maximum_profit": "Strike width - premium", "maximum_loss": "Premium + costs", "breakeven": "Higher strike - premium", "stop_loss": "Above higher strike", "adjustment": "Roll down both legs", "exit": "At expiry or target", "strategy_environment": "TRENDING_BEARISH", "invalidation": "Price above VWAP or RSI < 25", "position_size": position_size},
                {"strategy": "Bear Call Spread", "market_condition": "Bearish trend", "expiry": "NEXT_WEEKLY", "legs": ["SELL OTM CALL", "BUY further OTM CALL"], "entry_trigger": "Price below VWAP, RSI > 30", "maximum_profit": "Premium received", "maximum_loss": "Strike width - premium", "breakeven": "Lower strike + premium", "stop_loss": "Above higher strike", "adjustment": "Roll up both legs", "exit": "At expiry or target", "strategy_environment": "TRENDING_BEARISH", "invalidation": "Price above higher call strike", "position_size": position_size},
            ]
        elif regime == "RANGE_BOUND":
            strategies = [
                {"strategy": "Iron Condor", "market_condition": "Range-bound", "expiry": "NEXT_WEEKLY", "legs": ["SELL OTM CALL", "BUY OTM CALL", "SELL OTM PUT", "BUY OTM PUT"], "entry_trigger": "Price between support and resistance", "maximum_profit": "Premium received", "maximum_loss": "Strike width - premium", "breakeven": "Wings ± premium", "stop_loss": "Breakout/breakdown", "adjustment": "Roll both sides", "exit": "At expiry", "strategy_environment": "RANGE_BOUND", "invalidation": "Breakout above resistance or breakdown below support", "position_size": position_size},
            ]
        elif regime == "HIGH_VOLATILITY":
            strategies = [
                {"strategy": "Defined-risk premium selling", "market_condition": "High IV", "expiry": "NEXT_WEEKLY", "legs": ["SELL OTM PUT Spread", "SELL OTM CALL Spread"], "entry_trigger": "High IV, range-bound", "maximum_profit": "Premium received", "maximum_loss": "Strike width - premium", "breakeven": "Wings ± premium", "stop_loss": "Breakout/breakdown", "adjustment": "Roll both sides", "exit": "At expiry", "strategy_environment": "HIGH_VOLATILITY", "invalidation": "Volatility crush or breakout", "position_size": "50%"},
            ]
        else:
            strategies = [{"strategy": "NO TRADE", "market_condition": "Unclear", "expiry": "N/A", "legs": [], "entry_trigger": "Wait for clear signal", "maximum_profit": "N/A", "maximum_loss": "N/A", "breakeven": "N/A", "stop_loss": "N/A", "adjustment": "N/A", "exit": "N/A", "strategy_environment": "UNKNOWN", "invalidation": "Wait for confirmation", "position_size": "0%"}]
        return {"regime": regime, "confidence": confidence, "data_quality": data_quality, "strategies": strategies, "position_size": position_size, "timestamp": datetime.now(timezone.utc).isoformat()}

    def _position_size(self, confidence: float, data_quality: str) -> str:
        if data_quality == "STALE":
            return "0%"
        base = 10
        if confidence >= 80:
            base = 40
        elif confidence >= 60:
            base = 30
        elif confidence >= 40:
            base = 20
        return f"{base}%"