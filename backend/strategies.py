from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


class StrategyEngine:
    # Option strategies (spreads/condors) are only for tradable index derivatives.
    INDEX_SYMBOLS = {"NIFTY", "BANKNIFTY", "SENSEX", "FINNIFTY"}

    def is_index(self, symbol: str = "") -> bool:
        return (symbol or "").upper() in self.INDEX_SYMBOLS

    def select(self, regime: str, confidence: float, data_quality: str, vix_price: float = 0, vix_change_pct: float = 0, symbol: str = "", price: float = 0, vwap: float = 0, rsi: float | None = None, adx: float | None = None) -> dict[str, Any]:
        # Stocks / ETFs get a simple BUY / HOLD / EXIT outlook, never option spreads.
        if symbol and not self.is_index(symbol):
            return self.select_stock_outlook(regime, confidence, data_quality, symbol, price, vwap, rsi, adx)
        strategies = []
        position_size = self._position_size(confidence, data_quality)
        nd = self._non_directional_intraday(regime, confidence, vix_price, vix_change_pct, symbol)
        if nd:
            strategies.append(nd)
        if regime == "TRENDING_BULLISH":
            strategies += [
                {"strategy": "Bull Call Spread", "market_condition": "Bullish trend", "expiry": "NEXT_WEEKLY", "legs": ["BUY ATM CALL", "SELL 1-2 OTM CALL"], "entry_trigger": "Price above VWAP, RSI < 70", "maximum_profit": "Strike width - premium", "maximum_loss": "Premium + costs", "breakeven": "Lower strike + premium", "stop_loss": "Below lower strike", "adjustment": "Roll up both legs", "exit": "At expiry or target", "strategy_environment": "TRENDING_BULLISH", "invalidation": "Price below VWAP or RSI > 75", "position_size": position_size},
                {"strategy": "Bull Put Spread", "market_condition": "Bullish trend", "expiry": "NEXT_WEEKLY", "legs": ["SELL OTM PUT", "BUY further OTM PUT"], "entry_trigger": "Price above VWAP, RSI < 70", "maximum_profit": "Premium received", "maximum_loss": "Strike width - premium", "breakeven": "Higher strike - premium", "stop_loss": "Below lower strike", "adjustment": "Roll down both legs", "exit": "At expiry or target", "strategy_environment": "TRENDING_BULLISH", "invalidation": "Price below lower put strike", "position_size": position_size},
            ]
        elif regime == "TRENDING_BEARISH":
            strategies += [
                {"strategy": "Bear Put Spread", "market_condition": "Bearish trend", "expiry": "NEXT_WEEKLY", "legs": ["BUY ATM PUT", "SELL 1-2 OTM PUT"], "entry_trigger": "Price below VWAP, RSI > 30", "maximum_profit": "Strike width - premium", "maximum_loss": "Premium + costs", "breakeven": "Higher strike - premium", "stop_loss": "Above higher strike", "adjustment": "Roll down both legs", "exit": "At expiry or target", "strategy_environment": "TRENDING_BEARISH", "invalidation": "Price above VWAP or RSI < 25", "position_size": position_size},
                {"strategy": "Bear Call Spread", "market_condition": "Bearish trend", "expiry": "NEXT_WEEKLY", "legs": ["SELL OTM CALL", "BUY further OTM CALL"], "entry_trigger": "Price below VWAP, RSI > 30", "maximum_profit": "Premium received", "maximum_loss": "Strike width - premium", "breakeven": "Lower strike + premium", "stop_loss": "Above higher strike", "adjustment": "Roll up both legs", "exit": "At expiry or target", "strategy_environment": "TRENDING_BEARISH", "invalidation": "Price above higher call strike", "position_size": position_size},
            ]
        elif regime == "RANGE_BOUND":
            strategies += [
                {"strategy": "Iron Condor", "market_condition": "Range-bound", "expiry": "NEXT_WEEKLY", "legs": ["SELL OTM CALL", "BUY OTM CALL", "SELL OTM PUT", "BUY OTM PUT"], "entry_trigger": "Price between support and resistance", "maximum_profit": "Premium received", "maximum_loss": "Strike width - premium", "breakeven": "Wings ± premium", "stop_loss": "Breakout/breakdown", "adjustment": "Roll both sides", "exit": "At expiry", "strategy_environment": "RANGE_BOUND", "invalidation": "Breakout above resistance or breakdown below support", "position_size": position_size},
            ]
        elif regime == "HIGH_VOLATILITY":
            strategies += [
                {"strategy": "Defined-risk premium selling", "market_condition": "High IV", "expiry": "NEXT_WEEKLY", "legs": ["SELL OTM PUT Spread", "SELL OTM CALL Spread"], "entry_trigger": "High IV, range-bound", "maximum_profit": "Premium received", "maximum_loss": "Strike width - premium", "breakeven": "Wings ± premium", "stop_loss": "Breakout/breakdown", "adjustment": "Roll both sides", "exit": "At expiry", "strategy_environment": "HIGH_VOLATILITY", "invalidation": "Volatility crush or breakout", "position_size": "50%"},
            ]
        if not strategies:
            strategies = [{"strategy": "NO TRADE", "market_condition": "Unclear", "expiry": "N/A", "legs": [], "entry_trigger": "Wait for clear signal", "maximum_profit": "N/A", "maximum_loss": "N/A", "breakeven": "N/A", "stop_loss": "N/A", "adjustment": "N/A", "exit": "N/A", "strategy_environment": "UNKNOWN", "invalidation": "Wait for confirmation", "position_size": "0%"}]
        return {"regime": regime, "confidence": confidence, "data_quality": data_quality, "strategies": strategies, "position_size": position_size, "timestamp": datetime.now(timezone.utc).isoformat()}

    def select_stock_outlook(self, regime: str, confidence: float, data_quality: str, symbol: str = "", price: float = 0, vwap: float = 0, rsi: float | None = None, adx: float | None = None) -> dict[str, Any]:
        """Simple BUY / HOLD / EXIT outlook for cash-market stocks (no options)."""
        position_size = self._position_size(confidence, data_quality)
        if data_quality == "STALE":
            outlook = "HOLD"
            reason = "Stale data — wait for fresh prices"
            env = "UNKNOWN"
        elif regime == "TRENDING_BULLISH" and confidence >= 50:
            outlook = "BUY"
            reason = "Uptrend with strength"
            env = "TRENDING_BULLISH"
        elif regime == "TRENDING_BEARISH":
            outlook = "EXIT"
            reason = "Downtrend — exit longs / avoid fresh buying"
            env = "TRENDING_BEARISH"
        elif regime == "HIGH_VOLATILITY":
            outlook = "HOLD"
            reason = "High volatility — reduce risk, wait for clarity"
            env = "HIGH_VOLATILITY"
        elif regime == "RANGE_BOUND":
            outlook = "HOLD"
            reason = "Range-bound — buy near support, book near resistance"
            env = "RANGE_BOUND"
        else:
            # Fallback on price vs VWAP + RSI when regime is unclear.
            above_vwap = price > vwap > 0
            if above_vwap and rsi is not None and 50 <= rsi <= 70 and confidence >= 45:
                outlook = "BUY"
                reason = "Price above VWAP with healthy momentum"
                env = "MOMENTUM"
            elif rsi is not None and rsi < 30 and confidence >= 40:
                outlook = "BUY"
                reason = "Oversold bounce setup (watch for reversal confirmation)"
                env = "REVERSAL"
            elif rsi is not None and rsi > 75:
                outlook = "EXIT"
                reason = "Overbought — book partial profits"
                env = "OVERBOUGHT"
            else:
                outlook = "HOLD"
                reason = "No clear edge — wait for confirmation"
                env = "UNKNOWN"
        if outlook == "BUY":
            entry = "Buy in tranches near VWAP / support; confirm with green 15m close"
            stop = "Below recent swing low / -5% positional stop"
            target = "Nearest resistance / +8-12% swing target"
            max_loss = "Defined by stop-loss"
            max_profit = "Open-ended to resistance"
        elif outlook == "EXIT":
            entry = "Exit longs on bounce; no fresh buying"
            stop = "N/A (risk-off)"
            target = "Re-enter only above VWAP with momentum"
            max_loss = "Avoid further downside"
            max_profit = "Capital protection"
        else:
            entry = "Hold existing; fresh entry only on breakout/breakdown with volume"
            stop = "Below support"
            target = "Range top"
            max_loss = "Limited to range"
            max_profit = "Range move"
        strategy = {
            "strategy": outlook,
            "market_condition": f"Stock outlook | {reason}",
            "expiry": "N/A",
            "legs": [],
            "entry_trigger": entry,
            "maximum_profit": max_profit,
            "maximum_loss": max_loss,
            "breakeven": "N/A",
            "stop_loss": stop,
            "target": target,
            "adjustment": "Re-evaluate on regime change",
            "exit": "On EXIT signal or stop-loss",
            "strategy_environment": env,
            "invalidation": "Regime flip or stop-loss hit",
            "position_size": position_size,
            "is_stock_outlook": True,
        }
        return {"regime": regime, "confidence": confidence, "data_quality": data_quality, "strategies": [strategy], "position_size": position_size, "timestamp": datetime.now(timezone.utc).isoformat()}

    def _non_directional_intraday(self, regime: str, confidence: float, vix_price: float, vix_change_pct: float, symbol: str = "") -> dict[str, Any] | None:
        if symbol.upper() not in ("NIFTY", "BANKNIFTY"):
            return None
        from datetime import datetime as dt
        now = dt.now(timezone.utc)
        ist_hour = (now.hour + 5) % 24
        ist_minute = now.minute
        ist_time = ist_hour * 60 + ist_minute
        entry_time = 9 * 60 + 30
        exit_time = 15 * 60 + 20
        is_entry_time = ist_time >= entry_time and ist_time < entry_time + 1
        is_market_open = ist_time >= entry_time and ist_time < exit_time
        if vix_price < 12:
            strike_type = "ATM Straddle"
            legs = ["BUY ATM CALL", "BUY ATM PUT"]
        elif vix_price < 18:
            strike_type = "ATM Strangle"
            legs = ["BUY 1-strike OTM CALL", "BUY 1-strike OTM PUT"]
        elif vix_price < 25:
            strike_type = "Wide OTM Strangle"
            legs = ["BUY 2-strikes OTM CALL", "BUY 2-strikes OTM PUT"]
        else:
            return None
        if is_entry_time:
            entry_trigger = "9:30 AM IST | VIX < 5% intraday up | VIX-based strikes"
            exit_cond = "VIX crosses 5% intraday up | 2% loss | 3:20 PM IST"
        elif is_market_open:
            entry_trigger = "ENTRY PASSED 9:30 AM — monitor exit"
            exit_cond = "VIX crosses 5% intraday up | 2% loss | 3:20 PM IST"
        else:
            entry_trigger = "Market closed — no new entry"
            exit_cond = "N/A"
        return {"strategy": f"ND Intraday {strike_type}", "market_condition": "Non-directional intraday | NIFTY options", "expiry": "DAY", "legs": legs, "entry_trigger": entry_trigger, "maximum_profit": "Unlimited (both legs)", "maximum_loss": "Premium paid", "breakeven": "ATM ± premium", "stop_loss": "2% of premium paid", "adjustment": "Roll strikes wider", "exit": exit_cond, "strategy_environment": regime, "invalidation": "VIX > 5% intraday up | Stop loss hit", "position_size": "25%", "is_intraday": True}

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