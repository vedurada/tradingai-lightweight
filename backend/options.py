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

    def _max_pain_aggregate_payout(self, contracts: list[dict]) -> dict[str, Any]:
        """
        Calculate Max Pain strike: the strike that minimizes the aggregate
        intrinsic payout of all options at expiration.

        For each candidate settlement strike K:
        - Calls: max(K - strike, 0) × Call OI
        - Puts: max(strike - K, 0) × Put OI
        Max Pain = K producing the minimum aggregate payout.
        """
        if not contracts:
            return {"max_pain": None, "pain_details": {}, "min_payout": None}

        # Group open interest by strike and option type
        calls_by_strike = {}
        puts_by_strike = {}
        for c in contracts:
            strike = c.get("strike", 0)
            oi = c.get("open_interest", 0)
            opt_type = c.get("option_type", "")
            if strike <= 0 or oi <= 0:
                continue
            if opt_type == "CE":
                calls_by_strike[strike] = calls_by_strike.get(strike, 0) + oi
            elif opt_type == "PE":
                puts_by_strike[strike] = puts_by_strike.get(strike, 0) + oi

        # Get all unique strikes
        all_strikes = sorted(list(set(list(calls_by_strike.keys()) + list(puts_by_strike.keys()))))

        # Calculate aggregate payout for each candidate settlement strike
        pain_details = {}
        for settlement in all_strikes:
            total_payout = 0.0
            # Call payouts: max(settlement - strike, 0) × Call OI
            for strike, call_oi in calls_by_strike.items():
                total_payout += max(settlement - strike, 0) * call_oi
            # Put payouts: max(strike - settlement, 0) × Put OI
            for strike, put_oi in puts_by_strike.items():
                total_payout += max(strike - settlement, 0) * put_oi
            pain_details[settlement] = total_payout

        if not pain_details:
            return {"max_pain": None, "pain_details": {}, "min_payout": None}

        # Max Pain = strike with minimum aggregate payout
        max_pain_strike = min(pain_details, key=pain_details.get)
        return {
            "max_pain": max_pain_strike,
            "pain_details": pain_details,
            "min_payout": pain_details[max_pain_strike],
        }

    def calculate_max_pain(self, contracts: list[dict]) -> dict[str, Any]:
        """
        Public API: calculate Max Pain strike from options contracts.
        Returns the strike producing the minimum aggregate option-holder payout.
        """
        result = self._max_pain_aggregate_payout(contracts)
        # Return a simple dict for backward compatibility with existing callers
        return {"max_pain": result["max_pain"]}

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