from __future__ import annotations

import json
import logging
import os
import re
import requests
from datetime import datetime, timezone
from typing import Any, Optional

from regime_utils import normalize_regime

logger = logging.getLogger("tradingai.ai")


def _safe(v, default=0.0):
    try:
        if v is None:
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def _load_adaptive():
    try:
        from adaptive_engine import adaptive_outlook, classify_market_structure
        return adaptive_outlook, classify_market_structure
    except Exception:
        return None, None


FREE_PROVIDERS = ["gemini", "groq", "deepseek", "openrouter", "ollama"]


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
- market_regime: BULLISH/BEARISH/SIDEWAYS/HIGH_VOLATILITY/UNCONFIRMED
- directional_bias: BULLISH/MILD_BULLISH/NEUTRAL/MILD_BEARISH/BEARISH/MIXED
- confidence: 0-100 (MODEL_CONFIDENCE — confidence in current classification, not probability)
- evidence_strength: 0.0-1.0
- volatility_classification: HIGH/MEDIUM/LOW
- market_structure: TRENDING_BULLISH/TRENDING_BEARISH/SIDEWAYS/SIDEWAYS_TO_BULLISH/SIDEWAYS_TO_BEARISH/VOLATILE_EXPANSION/TRANSITIONAL/NO_TRADE
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
- generated_at: ISO timestamp
- trade_class: DIRECTIONAL/MILD_DIRECTIONAL/NON_DIRECTIONAL/NO_TRADE
- trade_status: ACTIVE/WAIT/WAIT_FOR_CONFIRMATION/CONDITIONAL/NO_TRADE/WAIT_FOR_PULLBACK
- entry_trigger: explicit entry condition
- confirmation_conditions: list of required confirmations
- target_zone: defined target zone
- supporting_factors: list of supporting evidence
- conflicting_factors: list of conflicting evidence
- interpretation: concise trader-readable narrative consistent with structured output"""

    def _cached(self, key: str) -> Optional[Any]:
        if key in self._cache and key in self._cache_time:
            if (datetime.now(timezone.utc).timestamp() - self._cache_time[key]) < self._cache_ttl:
                return self._cache[key]
        return None

    def generate(self, symbol: str, data: dict, use_llm: bool = True) -> dict:
        cached = self._cached(f"ai:{symbol}")
        if cached:
            return cached
        prompt = self._build_prompt(symbol, data)
        adaptive_fn, classify_fn = _load_adaptive()
        if use_llm:
            llm_outlook = self._call_llm_chain(prompt, data)
            if llm_outlook:
                outlook = self._normalize_llm_outlook(symbol, llm_outlook, data)
            else:
                outlook = self._adaptive_fallback(data, adaptive_fn)
        else:
            outlook = self._adaptive_fallback(data, adaptive_fn)
        if classify_fn:
            try:
                classified = classify_fn(data)
                outlook["market_structure"] = classified["market_structure"]
                outlook["directional_bias"] = classified["directional_bias"]
                outlook["trade_class"] = classified["trade_class"]
                outlook["trade_status"] = classified["trade_status"]
                outlook["entry_trigger"] = classified["entry_trigger"]
                outlook["confirmation_conditions"] = classified["confirmation_conditions"]
                outlook["preferred_strategy"] = classified["preferred_strategy"]
                outlook["invalidation"] = classified["invalidation"]
                outlook["target_zone"] = classified["target_zone"]
                outlook["supporting_factors"] = classified["supporting_factors"]
                outlook["conflicting_factors"] = classified["conflicting_factors"]
                outlook["adaptive_confidence"] = classified["confidence"]
            except Exception:
                pass
        logger.info(f"AI outlook for {symbol}: structure={outlook.get('market_structure', '?')} bias={outlook.get('directional_bias', '?')} status={outlook.get('trade_status', '?')} conf={outlook.get('confidence', '?')}")
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
        providers = self._load_providers()
        for name in providers:
            try:
                result = self._call_provider(name, prompt)
                if result:
                    logger.info(f"LLM {name} ok for {data.get('symbol', '?')}")
                    return result
            except Exception as e:
                logger.warning(f"LLM {name} failed: {e}")
        return self._rule_based_outlook(data)

    def _load_providers(self) -> list[str]:
        try:
            with open("config/settings.json") as f:
                cfg = json.load(f)
            p = cfg.get("llm_provider", "")
            if p:
                return [p]
            return cfg.get("llm_providers", FREE_PROVIDERS)
        except Exception:
            return FREE_PROVIDERS

    def _call_provider(self, name: str, prompt: str) -> Optional[dict]:
        handlers = {
            "gemini": self._call_gemini,
            "groq": self._call_groq,
            "deepseek": self._call_deepseek,
            "openrouter": self._call_openrouter,
            "ollama": self._call_ollama,
        }
        fn = handlers.get(name)
        if not fn:
            return None
        return fn(prompt)

    def _normalize_llm_outlook(self, symbol: str, outlook: dict, data: dict) -> dict:
        """Coerce LLM output into the schema the site renders (rule-based shape).

        The LLM may return confidence as a 0-1 fraction (site shows %), bias/regime in
        mixed case, and drop required keys. Normalize + backfill so pages like dashboard.js
        and nifty.js never break."""
        out = dict(outlook)
        # confidence -> 0..100 (handle fraction, absolute %, and word forms)
        c = out.get("confidence")
        if isinstance(c, (int, float)):
            if 0 < c <= 1:
                out["confidence"] = round(c * 100)
            else:
                out["confidence"] = max(0, min(100, int(c)))
        elif isinstance(c, str):
            u = c.upper().strip()
            out["confidence"] = 70 if "HIGH" in u else 35 if "LOW" in u else 50
        elif c is None:
            out["confidence"] = 50
        # regime / bias casing
        if out.get("market_regime"):
            out["market_regime"] = str(out["market_regime"]).upper().replace(" ", "_")
        if out.get("directional_bias"):
            out["directional_bias"] = str(out["directional_bias"]).upper()
        # volatility classification -> HIGH/MEDIUM/LOW
        v = str(out.get("volatility_classification") or "").upper()
        out["volatility_classification"] = "HIGH" if "HIGH" in v else "LOW" if "LOW" in v else "MEDIUM"
        # evidence_strength -> 0..1 (handle word forms like "Weak", "Moderate-Strong")
        e = out.get("evidence_strength")
        if isinstance(e, (int, float)):
            out["evidence_strength"] = max(0.0, min(1.0, float(e)))
        elif isinstance(e, str):
            s = e.upper()
            ev = 0.5
            if "VERY STRONG" in s or "EXTREMELY STRONG" in s:
                ev = 0.9
            elif "STRONG" in s:
                ev = 0.75
            elif "WEAK" in s:
                ev = 0.3
            elif "MODERATE" in s:
                ev = 0.55
            out["evidence_strength"] = ev
        # primary_strategy dict may use `name` instead of site's `strategy` key
        ps = out.get("primary_strategy")
        if isinstance(ps, dict) and not ps.get("strategy") and ps.get("name"):
            ps2 = dict(ps)
            ps2["strategy"] = ps["name"]
            out["primary_strategy"] = ps2
        # required keys absent in LLM output -> backfill from rule-based defaults
        rule = self._rule_based_outlook(data)
        for k in ("asset", "date", "market_structure", "market_summary", "trend_analysis",
                  "momentum_analysis", "volatility_analysis", "support_levels", "resistance_levels",
                  "options_analysis", "bullish_scenario", "bearish_scenario", "range_scenario",
                  "primary_strategy", "alternative_strategies", "intraday_plan", "no_trade_conditions",
                  "strategy_environment", "invalidation", "risk_warnings", "data_quality", "generated_at"):
            if not out.get(k):
                out[k] = rule.get(k)
        out["asset"] = symbol
        return out

    def _parse_json(self, text: str) -> Optional[dict]:
        text = re.sub(r"```(?:json)?", "", text)
        text = text.strip()
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        text = text[start:end + 1]
        try:
            obj = json.loads(text)
            return obj if isinstance(obj, dict) else None
        except json.JSONDecodeError:
            return None

    def _post(self, url: str, body: dict, headers: dict[str, str], timeout: int = 15) -> Optional[dict]:
        r = requests.post(url, json=body, headers=headers, timeout=timeout)
        r.raise_for_status()
        return r.json()

    def _call_gemini(self, prompt: str) -> Optional[dict]:
        key = os.environ.get("GEMINI_API_KEY", "")
        if not key:
            return None
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={key}"
        body = {"contents": [{"role": "user", "parts": [prompt]}]}
        resp = self._post(url, body, {}, timeout=15)
        text = resp["candidates"][0]["content"]["parts"][0]["text"]
        return self._parse_json(text)

    def _call_groq(self, prompt: str) -> Optional[dict]:
        key = os.environ.get("GROQ_API_KEY", "")
        if not key:
            return None
        url = "https://api.groq.com/openai/v1/chat/completions"
        body = {"model": "openai/gpt-oss-120b", "messages": [{"role": "user", "content": prompt}], "temperature": 0.1}
        resp = self._post(url, body, {"Authorization": f"Bearer {key}"}, timeout=15)
        text = resp["choices"][0]["message"]["content"]
        return self._parse_json(text)

    def _call_deepseek(self, prompt: str) -> Optional[dict]:
        key = os.environ.get("DEEPSEEK_API_KEY", "")
        if not key:
            return None
        url = "https://api.deepseek.com/v1/chat/completions"
        body = {"model": "deepseek-chat", "messages": [{"role": "user", "content": prompt}], "temperature": 0.1}
        resp = self._post(url, body, {"Authorization": f"Bearer {key}"}, timeout=15)
        text = resp["choices"][0]["message"]["content"]
        return self._parse_json(text)

    def _call_openrouter(self, prompt: str) -> Optional[dict]:
        key = os.environ.get("OPENROUTER_API_KEY", "")
        if not key:
            return None
        url = "https://openrouter.ai/api/v1/chat/completions"
        body = {"model": "google/gemini-flash-1.5", "messages": [{"role": "user", "content": prompt}], "temperature": 0.1}
        resp = self._post(url, body, {"Authorization": f"Bearer {key}", "HTTP-Referer": "tradingai.in", "X-Title": "TradingAI"}, timeout=15)
        text = resp["choices"][0]["message"]["content"]
        return self._parse_json(text)

    def _call_ollama(self, prompt: str) -> Optional[dict]:
        url = "http://localhost:11434/api/generate"
        body = {"model": "qwen2.5:0.5b", "prompt": prompt, "stream": False, "options": {"temperature": 0.1}}
        resp = self._post(url, body, {}, timeout=60)
        text = resp["response"]
        return self._parse_json(text)

    def _adaptive_fallback(self, data: dict, adaptive_fn) -> dict:
        if adaptive_fn:
            try:
                result = adaptive_fn(data)
                result["data_state"] = data.get("data_state", "LIVE")
                result["data_quality"] = data.get("data_quality", "VALID")
                result["adaptive"] = True
                return result
            except Exception as e:
                logger.warning(f"Adaptive engine failed: {e}")
        return self._rule_based_outlook(data)

    def _rule_based_outlook(self, data: dict) -> dict:
        price = _safe(data.get("price", 0))
        rsi = data.get("rsi")
        regime = normalize_regime(data.get("regime", "UNCONFIRMED"))
        confidence = 50
        if regime == "BULLISH":
            directional_bias = "BULLISH"
            confidence = 65
        elif regime == "BEARISH":
            directional_bias = "BEARISH"
            confidence = 65
        else:
            directional_bias = "NEUTRAL"
            confidence = 45
        if rsi and (rsi > 70 or rsi < 30):
            confidence += 10
        atr = data.get("atr", 0)
        vix_val = data.get("vix", 0)
        vol_class = "HIGH" if (atr > 0 and atr > price * 0.02) or vix_val > 20 else ("MEDIUM" if atr > 0 else "LOW")
        structure = "UPTREND" if regime == "BULLISH" else ("DOWNTREND" if regime == "BEARISH" else "RANGE")
        no_trade = []
        if regime == "UNKNOWN":
            no_trade.append("Unclear direction")
        if data.get("volume", 0) == 0:
            no_trade.append("Low liquidity")
        if rsi and 40 < rsi < 60:
            no_trade.append("Conflicting indicators")

        market_structure = {"BULLISH": "TRENDING_BULLISH", "BEARISH": "TRENDING_BEARISH"}.get(regime, "SIDEWAYS")
        trade_class = "DIRECTIONAL" if regime in ("BULLISH", "BEARISH") else "NON_DIRECTIONAL"
        trade_status = "ACTIVE" if regime in ("BULLISH", "BEARISH") else "WAIT_FOR_CONFIRMATION"
        entry_trigger = "Wait for confirmation" if trade_status == "WAIT_FOR_CONFIRMATION" else "Entry active"
        confirmation = ["Price above VWAP"] if regime == "BULLISH" else ["Price below VWAP"] if regime == "BEARISH" else ["Range confirmation"]
        invalidation = "Break of key support/resistance"
        target_zone = "Next resistance zone" if regime == "BULLISH" else "Next support zone" if regime == "BEARISH" else "Range bounds"
        preferred_strategy = {"BULLISH": "BULL CALL SPREAD", "BEARISH": "BEAR PUT SPREAD"}.get(regime, "IRON_CONDOR")

        supporting = []
        if regime == "BULLISH":
            supporting.append(f"Regime: {regime}")
        elif regime == "BEARISH":
            supporting.append(f"Regime: {regime}")
        else:
            supporting.append("Regime: Neutral/range-bound")

        conflicting = []
        if regime == "UNKNOWN":
            conflicting.append("Unclear direction")

        interpretation = f"Market structure: {market_structure}. Directional bias: {directional_bias}. Trade status: {trade_status}. Preferred approach: {preferred_strategy}. {entry_trigger}."

        return {
            "asset": data.get("symbol", ""),
            "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "market_regime": regime,
            "directional_bias": directional_bias,
            "confidence": confidence,
            "evidence_strength": 0.5 if regime != "UNCONFIRMED" else 0.2,
            "volatility_classification": vol_class,
            "market_structure": market_structure,
            "market_summary": f"{data.get('symbol', '')} analysis - {regime}",
            "trend_analysis": f"Price vs EMA: {price} vs {data.get('ema20', 'N/A')}",
            "momentum_analysis": f"RSI: {rsi}, MACD: {data.get('macd', 'N/A')}",
            "volatility_analysis": f"ATR: {atr}, VIX: {vix_val}",
            "support_levels": data.get("support_levels", []),
            "resistance_levels": data.get("resistance_levels", []),
            "options_analysis": "DATA UNAVAILABLE" if data.get("options_unavailable") else "Options data available",
            "bullish_scenario": {"trigger": "Price above VWAP", "confirmation": "Break above resistance", "target": "Next resistance", "invalidation": "Below pivot"},
            "bearish_scenario": {"trigger": "Price below VWAP", "confirmation": "Break below support", "target": "Next support", "invalidation": "Above pivot"},
            "range_scenario": {"condition": "Price between support and resistance", "strategy_environment": "Iron Condor", "invalidation": "Breakout/breakdown"},
            "primary_strategy": {"strategy": preferred_strategy if regime != "UNKNOWN" else "NO TRADE", "market_condition": regime, "expiry": "NEXT_WEEKLY", "legs": [], "entry_trigger": entry_trigger, "maximum_profit": "N/A", "maximum_loss": "N/A", "breakeven": "N/A", "stop_loss": "N/A", "target": target_zone, "adjustment": "N/A", "exit": "N/A"},
            "alternative_strategies": [],
            "intraday_plan": [],
            "no_trade_conditions": no_trade if no_trade else ["Unclear direction", "Low liquidity", "Conflicting indicators"],
            "strategy_environment": "Neutral" if regime == "UNKNOWN" else regime,
            "trade_class": trade_class,
            "trade_status": trade_status,
            "entry_trigger": entry_trigger,
            "confirmation_conditions": confirmation,
            "invalidation": invalidation,
            "target_zone": target_zone,
            "preferred_strategy": preferred_strategy,
            "supporting_factors": supporting,
            "conflicting_factors": conflicting,
            "interpretation": interpretation,
            "risk_warnings": ["This is decision-support, not a guaranteed signal"],
            "data_quality": data.get("data_quality", "PARTIAL"),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "data_state": data.get("data_state", "LIVE"),
            "adaptive": False,
        }