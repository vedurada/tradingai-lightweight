from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


class StrategyEngine:
    def select(self, regime: str, confidence: float, data_quality: str) -> dict[str, Any]:
        strategies = []
        if regime == "TRENDING_BULLISH":
            strategies = [
                {"strategy": "Bull Call Spread", "market_condition": "Bullish trend", "expiry": "NEXT_WEEKLY", "legs": ["BUY ATM CALL", "SELL 1-2 OTM CALL"], "entry_trigger": "Price above VWAP, RSI < 70", "maximum_profit": "Strike width - premium", "maximum_loss": "Premium + costs", "breakeven": "Lower strike + premium", "stop_loss": "Below lower strike", "adjustment": "Roll up both legs", "exit": "At expiry or target"},
                {"strategy": "Bull Put Spread", "market_condition": "Bullish trend", "expiry": "NEXT_WEEKLY", "legs": ["SELL OTM PUT", "BUY further OTM PUT"], "entry_trigger": "Price above VWAP, RSI < 70", "maximum_profit": "Premium received", "maximum_loss": "Strike width - premium", "breakeven": "Higher strike - premium", "stop_loss": "Below lower strike", "adjustment": "Roll down both legs", "exit": "At expiry or target"},
            ]
        elif regime == "TRENDING_BEARISH":
            strategies = [
                {"strategy": "Bear Put Spread", "market_condition": "Bearish trend", "expiry": "NEXT_WEEKLY", "legs": ["BUY ATM PUT", "SELL 1-2 OTM PUT"], "entry_trigger": "Price below VWAP, RSI > 30", "maximum_profit": "Strike width - premium", "maximum_loss": "Premium + costs", "breakeven": "Higher strike - premium", "stop_loss": "Above higher strike", "adjustment": "Roll down both legs", "exit": "At expiry or target"},
                {"strategy": "Bear Call Spread", "market_condition": "Bearish trend", "expiry": "NEXT_WEEKLY", "legs": ["SELL OTM CALL", "BUY further OTM CALL"], "entry_trigger": "Price below VWAP, RSI > 30", "maximum_profit": "Premium received", "maximum_loss": "Strike width - premium", "breakeven": "Lower strike + premium", "stop_loss": "Above higher strike", "adjustment": "Roll up both legs", "exit": "At expiry or target"},
            ]
        elif regime == "RANGE_BOUND":
            strategies = [
                {"strategy": "Iron Condor", "market_condition": "Range-bound", "expiry": "NEXT_WEEKLY", "legs": ["SELL OTM CALL", "BUY OTM CALL", "SELL OTM PUT", "BUY OTM PUT"], "entry_trigger": "Price between support and resistance", "maximum_profit": "Premium received", "maximum_loss": "Strike width - premium", "breakeven": "Wings ± premium", "stop_loss": "Breakout/breakdown", "adjustment": "Roll both sides", "exit": "At expiry"},
            ]
        elif regime == "HIGH_VOLATILITY":
            strategies = [
                {"strategy": "Defined-risk premium selling", "market_condition": "High IV", "expiry": "NEXT_WEEKLY", "legs": ["SELL OTM PUT Spread", "SELL OTM CALL Spread"], "entry_trigger": "High IV, range-bound", "maximum_profit": "Premium received", "maximum_loss": "Strike width - premium", "breakeven": "Wings ± premium", "stop_loss": "Breakout/breakdown", "adjustment": "Roll both sides", "exit": "At expiry"},
            ]
        else:
            strategies = [{"strategy": "NO TRADE", "market_condition": "Unclear", "expiry": "N/A", "legs": [], "entry_trigger": "Wait for clear signal", "maximum_profit": "N/A", "maximum_loss": "N/A", "breakeven": "N/A", "stop_loss": "N/A", "adjustment": "N/A", "exit": "N/A"}]
        return {"regime": regime, "confidence": confidence, "data_quality": data_quality, "strategies": strategies, "timestamp": datetime.now(timezone.utc).isoformat()}