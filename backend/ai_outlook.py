from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger("tradingai.ai")


class AIOutlookEngine:
    def __init__(self, prompt_path: str = "prompts/daily_outlook.txt") -> None:
        self.prompt_path = prompt_path
        self._cache: dict[str, Any] = {}
        self._cache_time: dict[str, float] = {}
        self._cache_ttl = 300
        self._prompt = self._load_prompt()

    def _load_prompt(self) -> str:
        if os.path.exists(self.prompt_path):
            with open(self.prompt_path) as f:
                return f.read()
        return "Analyze the market and return JSON only."

    def _cached(self, key: str) -> Optional[Any]:
        if key in self._cache and key in self._cache_time:
            if (datetime.now(timezone.utc).timestamp() - self._cache_time[key]) < self._cache_ttl:
                return self._cache[key]
        return None

    def generate(self, symbol: str, data: dict) -> dict:
        cached = self._cached(f"ai:{symbol}")
        if cached:
            return cached
        prompt = self._build_prompt(symbol, data)
        outlook = self._call_llm(prompt, data)
        if not self._validate(outlook):
            logger.warning(f"AI outlook for {symbol} invalid, using fallback")
            outlook = self._fallback(symbol, data)
        self._cache[f"ai:{symbol}"] = outlook
        return outlook

    def _build_prompt(self, symbol: str, data: dict) -> str:
        return f"""Analyze {symbol} using this data:
Price: {data.get('price', 'N/A')}
RSI: {data.get('rsi', 'N/A')}
MACD: {data.get('macd', 'N/A')}
ADX: {data.get('adx', 'N/A')}
ATR: {data.get('atr', 'N/A')}
VWAP: {data.get('vwap', 'N/A')}
Pivot: {data.get('pivot', 'N/A')}
CPR: {data.get('cpr', 'N/A')}
VIX: {data.get('vix', 'N/A')}
Regime: {data.get('regime', 'N/A')}

Return valid JSON with: asset, date, market_regime, directional_bias, confidence, market_summary, trend_analysis, momentum_analysis, volatility_analysis, support_levels, resistance_levels, options_analysis, bullish_scenario, bearish_scenario, range_scenario, primary_strategy, alternative_strategies, intraday_plan, no_trade_conditions, risk_warnings, data_quality, generated_at"""

    def _call_llm(self, prompt: str, data: dict) -> dict:
        llm_api_key = os.environ.get("LLM_API_KEY", "")
        llm_url = os.environ.get("LLM_API_URL", "")
        if not llm_api_key or not llm_url:
            logger.info("No LLM configured, generating rule-based outlook")
            return self._rule_based_outlook(data)
        try:
            import urllib.request
            payload = json.dumps({"model": "gpt-4o-mini", "messages": [{"role": "system", "content": "You are a market analyst. Return valid JSON only."}, {"role": "user", "content": prompt}], "temperature": 0.3}).encode()
            req = urllib.request.Request(llm_url, data=payload, headers={"Content-Type": "application/json", "Authorization": f"Bearer {llm_api_key}"}, method="POST")
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read().decode())
                return json.loads(result["choices"][0]["message"]["content"])
        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            return self._rule_based_outlook(data)

    def _rule_based_outlook(self, data: dict) -> dict:
        price = data.get("price", 0)
        rsi = data.get("rsi")
        regime = data.get("regime", "UNCONFIRMED")
        confidence = 50
        if regime == "TRENDING_BULLISH":
            directional_bias = "BULLISH"
            confidence = 65
        elif regime == "TRENDING_BEARISH":
            directional_bias = "BEARISH"
            confidence = 65
        else:
            directional_bias = "NEUTRAL"
            confidence = 45
        if rsi and (rsi > 70 or rsi < 30):
            confidence += 10
        return {
            "asset": data.get("symbol", ""),
            "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "market_regime": regime,
            "directional_bias": directional_bias,
            "confidence": confidence,
            "market_summary": f"{data.get('symbol', '')} analysis - {regime}",
            "trend_analysis": f"Price vs EMA: {price} vs {data.get('ema20', 'N/A')}",
            "momentum_analysis": f"RSI: {rsi}, MACD: {data.get('macd', 'N/A')}",
            "volatility_analysis": f"ATR: {data.get('atr', 'N/A')}, VIX: {data.get('vix', 'N/A')}",
            "support_levels": data.get("support_levels", []),
            "resistance_levels": data.get("resistance_levels", []),
            "options_analysis": "DATA UNAVAILABLE" if data.get("options_unavailable") else "Options data available",
            "bullish_scenario": {"trigger": "Price above VWAP", "confirmation": "Break above resistance", "target": "Next resistance", "invalidation": "Below pivot"},
            "bearish_scenario": {"trigger": "Price below VWAP", "confirmation": "Break below support", "target": "Next support", "invalidation": "Above pivot"},
            "range_scenario": {"condition": "Price between support and resistance", "strategy_environment": "Iron Condor", "invalidation": "Breakout/breakdown"},
            "primary_strategy": {"strategy": "NO TRADE" if regime == "UNCONFIRMED" else "Defined-risk spread", "market_condition": regime, "expiry": "NEXT_WEEKLY", "legs": [], "entry_trigger": "Wait for signal", "maximum_profit": "N/A", "maximum_loss": "N/A", "breakeven": "N/A", "stop_loss": "N/A", "target": "N/A", "adjustment": "N/A", "exit": "N/A"},
            "alternative_strategies": [],
            "intraday_plan": [],
            "no_trade_conditions": ["Unclear direction", "Low liquidity", "Conflicting indicators"],
            "risk_warnings": ["This is decision-support, not a guaranteed signal"],
            "data_quality": data.get("data_quality", "PARTIAL"),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    def _validate(self, outlook: dict) -> bool:
        required = ["asset", "date", "market_regime", "confidence"]
        return all(k in outlook for k in required)

    def _fallback(self, symbol: str, data: dict) -> dict:
        return self._rule_based_outlook(data)