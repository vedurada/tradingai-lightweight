from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any

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
        return self._default_prompt()

    def _default_prompt(self) -> str:
        return """You are an Indian market analyst. Analyze the given market data and return JSON with:
- asset: symbol name
- date: YYYY-MM-DD
- market_regime: TRENDING_BULLISH/TRENDING_BEARISH/RANGE_BOUND/HIGH_VOLATILITY/UNCONFIRMED
- directional_bias: BULLISH/BEARISH/NEUTRAL
- confidence: 0-100
- evidence_strength: 0.0-1.0
- volatility_classification: HIGH/MEDIUM/LOW
- market_structure: UPTREND/DOWNTREND/RANGE
- market_summary: 1-2 sentence summary
- trend_analysis: price vs EMAs
- momentum_analysis: RSI, MACD, volume
- volatility_analysis: ATR, VIX, Bollinger width
- support_levels: list of key support prices
- resistance_levels: list of key resistance prices
- options_analysis: PCR, open interest, IV status
- bullish_scenario: {trigger, confirmation, target, invalidation}
- bearish_scenario: {trigger, confirmation, target, invalidation}
- range_scenario: {condition, strategy_environment, invalidation}
- primary_strategy: {strategy, market_condition, expiry, legs, entry_trigger, maximum_profit, maximum_loss, breakeven, stop_loss, target, adjustment, exit}
- alternative_strategies: list of alternatives
- intraday_plan: list of intraday steps
- no_trade_conditions: list of conditions to avoid trading
- strategy_environment: market environment tag
- invalidation: key invalidation level
- risk_warnings: list of warnings
- data_quality: GOOD/PARTIAL/STALE
- generated_at: ISO timestamp"""

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
        outlook = self._call_llm_chain(prompt, data)
        logger.info(f"AI outlook for {symbol}: {outlook.get('market_regime', '?')} bias={outlook.get('directional_bias', '?')} conf={outlook.get('confidence', '?')}")
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

Return valid JSON with: asset, date, market_regime, directional_bias, confidence, evidence_strength, volatility_classification, market_structure, market_summary, trend_analysis, momentum_analysis, volatility_analysis, support_levels, resistance_levels, options_analysis, bullish_scenario, bearish_scenario, range_scenario, primary_strategy, alternative_strategies, intraday_plan, no_trade_conditions, strategy_environment, invalidation, risk_warnings, data_quality, generated_at"""

    def _call_llm_chain(self, prompt: str, data: dict) -> dict:
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
        atr = data.get("atr", 0)
        vix = data.get("vix", 0)
        vol_class = "HIGH" if (atr > 0 and atr > price * 0.02) or vix > 20 else ("MEDIUM" if atr > 0 else "LOW")
        structure = "UPTREND" if regime == "TRENDING_BULLISH" else ("DOWNTREND" if regime == "TRENDING_BEARISH" else "RANGE")
        no_trade = []
        if regime == "UNCONFIRMED":
            no_trade.append("Unclear direction")
        if data.get("volume", 0) == 0:
            no_trade.append("Low liquidity")
        if rsi and 40 < rsi < 60:
            no_trade.append("Conflicting indicators")
        return {
            "asset": data.get("symbol", ""),
            "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "market_regime": regime,
            "directional_bias": directional_bias,
            "confidence": confidence,
            "evidence_strength": 0.5 if regime != "UNCONFIRMED" else 0.2,
            "volatility_classification": vol_class,
            "market_structure": structure,
            "market_summary": f"{data.get('symbol', '')} analysis - {regime}",
            "trend_analysis": f"Price vs EMA: {price} vs {data.get('ema20', 'N/A')}",
            "momentum_analysis": f"RSI: {rsi}, MACD: {data.get('macd', 'N/A')}",
            "volatility_analysis": f"ATR: {atr}, VIX: {vix}",
            "support_levels": data.get("support_levels", []),
            "resistance_levels": data.get("resistance_levels", []),
            "options_analysis": "DATA UNAVAILABLE" if data.get("options_unavailable") else "Options data available",
            "bullish_scenario": {"trigger": "Price above VWAP", "confirmation": "Break above resistance", "target": "Next resistance", "invalidation": "Below pivot"},
            "bearish_scenario": {"trigger": "Price below VWAP", "confirmation": "Break below support", "target": "Next support", "invalidation": "Above pivot"},
            "range_scenario": {"condition": "Price between support and resistance", "strategy_environment": "Iron Condor", "invalidation": "Breakout/breakdown"},
            "primary_strategy": {"strategy": "NO TRADE" if regime == "UNCONFIRMED" else "Defined-risk spread", "market_condition": regime, "expiry": "NEXT_WEEKLY", "legs": [], "entry_trigger": "Wait for signal", "maximum_profit": "N/A", "maximum_loss": "N/A", "breakeven": "N/A", "stop_loss": "N/A", "target": "N/A", "adjustment": "N/A", "exit": "N/A"},
            "alternative_strategies": [],
            "intraday_plan": [],
            "no_trade_conditions": no_trade if no_trade else ["Unclear direction", "Low liquidity", "Conflicting indicators"],
            "strategy_environment": "Neutral" if regime == "UNCONFIRMED" else regime,
            "invalidation": "Break of key support/resistance",
            "risk_warnings": ["This is decision-support, not a guaranteed signal"],
            "data_quality": data.get("data_quality", "PARTIAL"),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

