from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger("tradingai.regime")


class RegimeEngine:
    def __init__(self) -> None:
        self._cache: dict[str, Any] = {}
        self._cache_time: dict[str, float] = {}
        self._cache_ttl = 300

    def _cached(self, key: str, value: Any = None, ttl: float = 300) -> Optional[Any]:
        if value is not None:
            self._cache[key] = value
            self._cache_time[key] = datetime.now(timezone.utc).timestamp()
            return None
        if key in self._cache and key in self._cache_time:
            if (datetime.now(timezone.utc).timestamp() - self._cache_time[key]) < self._cache_ttl:
                return self._cache[key]
        return None

    def evaluate(self, price: float, vwap: float, prev_close: float, rsi: Optional[float],
                 macd: Optional[dict], adx: Optional[float], vix_price: float,
                 bollinger: Optional[dict], pivot: Optional[dict],
                 support_resistance: Optional[dict], pcr: Optional[float] = None) -> dict:
        cached_key = f"regime:{price}:{vwap}:{rsi}:{adx}"
        cached = self._cached(cached_key)
        if cached:
            return cached
        scores = {"trend_up": 0.0, "trend_down": 0.0, "range": 0.0, "high_vol": 0.0}
        reasons = []
        if price > vwap > prev_close:
            scores["trend_up"] += 30
            reasons.append("Price above VWAP and prev close")
        elif price < vwap < prev_close:
            scores["trend_down"] += 30
            reasons.append("Price below VWAP and prev close")
        else:
            scores["range"] += 20
            reasons.append("Price near VWAP - range bound")
        if rsi is not None:
            if rsi > 60:
                scores["trend_up"] += 20
                reasons.append(f"RSI {rsi} - bullish momentum")
            elif rsi < 40:
                scores["trend_down"] += 20
                reasons.append(f"RSI {rsi} - bearish momentum")
        if macd and macd.get("histogram", 0) > 0:
            scores["trend_up"] += 15
            reasons.append("MACD histogram positive")
        elif macd and macd.get("histogram", 0) < 0:
            scores["trend_down"] += 15
            reasons.append("MACD histogram negative")
        if adx is not None and adx > 25:
            scores["trend_up" if scores["trend_up"] > scores["trend_down"] else "trend_down"] += 15
            reasons.append(f"ADX {adx} - trending")
        if vix_price > 20:
            scores["high_vol"] += 20
            reasons.append(f"VIX {vix_price} - high volatility")
        if pcr is not None and pcr > 1.5:
            scores["trend_down"] += 10
            reasons.append("PCR > 1.5 - put heavy")
        regime = max(scores, key=scores.get)
        regime_map = {"trend_up": "TRENDING_BULLISH", "trend_down": "TRENDING_BEARISH", "range": "RANGE_BOUND", "high_vol": "HIGH_VOLATILITY"}
        result = {"regime": regime_map.get(regime, "UNCONFIRMED"), "confidence": round(max(scores.values()), 1), "reasons": reasons, "scores": scores, "timestamp": datetime.now(timezone.utc).isoformat()}
        self._cached(cached_key, result)
        return result