from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger("tradingai.options")


class OptionsEngine:
    def __init__(self) -> None:
        self._cache: dict[str, Any] = {}
        self._cache_time: dict[str, float] = {}
        self._cache_ttl = 300

    def _cached(self, key: str) -> Optional[Any]:
        if key in self._cache and key in self._cache_time:
            if (datetime.now(timezone.utc).timestamp() - self._cache_time[key]) < self._cache_ttl:
                return self._cache[key]
        return None

    def _set_cache(self, key: str, value: Any) -> None:
        self._cache[key] = value
        self._cache_time[key] = datetime.now(timezone.utc).timestamp()

    def calculate_pcr(self, call_oi: float, put_oi: float) -> float:
        if call_oi == 0:
            return 0.0
        return round(put_oi / call_oi, 3)

    def calculate_max_pain(self, contracts: list[dict]) -> dict[str, Any]:
        pain_map = defaultdict(float)
        for c in contracts:
            strike = c.get("strike", 0)
            oi = c.get("open_interest", 0)
            if strike > 0 and oi > 0:
                pain_map[strike] += oi
        if not pain_map:
            return {"max_pain": 0, "call_max_oi_strike": 0, "put_max_oi_strike": 0}
        max_pain_strike = max(pain_map, key=pain_map.get)
        call_oi_by_strike = defaultdict(float)
        put_oi_by_strike = defaultdict(float)
        for c in contracts:
            strike = c.get("strike", 0)
            oi = c.get("open_interest", 0)
            if c.get("option_type") == "CE":
                call_oi_by_strike[strike] += oi
            else:
                put_oi_by_strike[strike] += oi
        return {
            "max_pain": max_pain_strike,
            "call_max_oi_strike": max(call_oi_by_strike, key=call_oi_by_strike.get) if call_oi_by_strike else 0,
            "put_max_oi_strike": max(put_oi_by_strike, key=put_oi_by_strike.get) if put_oi_by_strike else 0,
        }

    def calculate_iv_stats(self, contracts: list[dict]) -> dict[str, Any]:
        ivs = [c.get("implied_volatility", 0) for c in contracts if c.get("implied_volatility")]
        if not ivs:
            return {"avg_iv": 0, "min_iv": 0, "max_iv": 0, "iv_rank": 0}
        avg_iv = sum(ivs) / len(ivs)
        return {"avg_iv": round(avg_iv, 2), "min_iv": round(min(ivs), 2), "max_iv": round(max(ivs), 2), "iv_rank": round(((avg_iv - min(ivs)) / (max(ivs) - min(ivs)) * 100) if max(ivs) > min(ivs) else 50, 1)}

    def analyze_options(self, chain: Optional[dict], underlying_price: float) -> dict[str, Any]:
        if not chain:
            return {"data_unavailable": True, "message": "Options data unavailable"}
        calls = chain.get("calls", [])
        puts = chain.get("puts", [])
        contracts = calls + puts
        call_oi = sum(c.get("open_interest", 0) for c in calls)
        put_oi = sum(c.get("open_interest", 0) for c in puts)
        pcr = self.calculate_pcr(call_oi, put_oi)
        max_pain = self.calculate_max_pain(contracts)
        iv_stats = self.calculate_iv_stats(contracts)
        if iv_stats.get("iv_rank", 0) > 70:
            environment = "HIGH_VOLATILITY"
        elif pcr > 1.5:
            environment = "BEARISH"
        elif pcr < 0.7:
            environment = "BULLISH"
        elif underlying_price > 0 and max_pain.get("max_pain", 0) > 0:
            diff = abs(underlying_price - max_pain["max_pain"]) / underlying_price * 100
            environment = "RANGE" if diff < 1 else "NEUTRAL"
        else:
            environment = "NEUTRAL"
        strategy_map = {"BULLISH": ["Bull Call Spread", "Bull Put Spread"], "BEARISH": ["Bear Put Spread", "Bear Call Spread"], "RANGE": ["Iron Condor", "Butterfly Spread"], "HIGH_VOLATILITY": ["Defined-risk structures"], "NEUTRAL": ["Iron Condor"]}
        return {
            "pcr": pcr, "call_oi": call_oi, "put_oi": put_oi, "max_pain": max_pain, "iv_stats": iv_stats,
            "environment": environment, "strategy_classes": strategy_map.get(environment, ["Neutral"]),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }