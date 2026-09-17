from __future__ import annotations

import json
import os
import sys
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ai_outlook import AIOutlookEngine

logger = logging.getLogger("tradingai.ai_outlook_5m")

IST = "Asia/Kolkata"

AI_OUTLOOK_PROMPT = """You are an Indian intraday market analyst. Analyze the structured market evidence below and return a structured JSON outlook.

IMPORTANT: This is an AI-generated market outlook for INFORMATIONAL purposes only. It is NOT a trade recommendation.
The confidence value is the AI model's assessment, NOT a validated probability.
NEVER present confidence as "X% probability of profit".

The AI must NOT invent indicators or market facts. Only use the structured evidence provided.
If evidence groups show UNAVAILABLE, acknowledge the gap — do NOT fabricate direction.

Market evidence will be provided below. Return ONLY valid JSON with these fields:

{
  "instrument": "NIFTY",
  "timestamp": "ISO timestamp",
  "bias": "BULLISH|BEARISH|RANGE|MIXED",
  "confidence": 0-100,
  "market_regime": "BULLISH|BEARISH|RANGE|MIXED",
  "summary": "1-2 sentence factual outlook summary",
  "evidence": ["list of supporting factors from evidence"],
  "conflicting_evidence": ["list of conflicting evidence if any"],
  "watch_levels": ["key levels to monitor"],
  "confirmation_conditions": ["what would confirm this view"],
  "invalidation_conditions": ["what would invalidate this view"],
  "risk_conditions": ["risk factors"],
  "trade_state": "TRADE|WAIT|NO_TRADE",
  "strategy_context": null,
  "expected_horizon_minutes": 30,
  "data_availability": {
    "trend": "LIVE|DELAYED|UNAVAILABLE",
    "options": "LIVE|DELAYED|UNAVAILABLE"
  }
}

Allowed bias values ONLY: BULLISH, BEARISH, RANGE, MIXED. No other labels.
Allowed trade_state ONLY: TRADE, WAIT, NO_TRADE. The AI must NOT be forced to produce a trade.
BULLISH market does NOT automatically mean TRADE. RANGE market often means NO_TRADE.
The AI may return NO_TRADE for ANY bias.

If required inputs are unavailable, return:
{
  "instrument": "NIFTY",
  "bias": "MIXED",
  "confidence": 0,
  "trade_state": "NO_TRADE",
  "summary": "DATA UNAVAILABLE — required inputs are not available",
  "evidence": [],
  "conflicting_evidence": [],
  "watch_levels": [],
  "confirmation_conditions": [],
  "invalidation_conditions": [],
  "risk_conditions": ["data unavailable"],
  "trade_state": "NO_TRADE",
  "strategy_context": null,
  "expected_horizon_minutes": 30,
  "data_availability": {"trend": "UNAVAILABLE", "options": "UNAVAILABLE"}
}

Structured market evidence:
"""


class AIOutlookGenerator5m:
    def __init__(self, model: str = "groq"):
        self.model = model
        self.engine = AIOutlookEngine()

    def generate(self, symbol: str, market_state: dict, material_changes: list = None, evidence: dict = None) -> dict:
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        outlook_id = f"OUTLOOK-{symbol}-{timestamp.replace(':', '')}"

        prompt = self._build_prompt(symbol, market_state, material_changes or [], evidence)
        ai_response = self._call_llm(prompt)
        validated = self._validate(ai_response, symbol, timestamp)

        data_state = "LIVE"
        if evidence and evidence.get("groups"):
            ds = evidence.get("data_state", "")
            if ds and ds != "LIVE":
                data_state = ds
            elif market_state.get("data_state") and market_state.get("data_state") != "LIVE":
                data_state = market_state.get("data_state")

        result = {
            "outlook_id": outlook_id,
            "instrument": symbol,
            "generated_at": timestamp,
            "candle_timestamp": market_state.get("captured_at", timestamp),
            "model": self.model,
            "model_version": "v1",
            "prompt_version": "5m-v1",
            "bias": validated.get("bias", "MIXED"),
            "confidence": validated.get("confidence", 0),
            "market_regime": validated.get("market_regime", "MIXED"),
            "summary": validated.get("summary", ""),
            "evidence": validated.get("evidence", []),
            "watch_levels": validated.get("watch_levels", []),
            "confirmation_conditions": validated.get("confirmation_conditions", []),
            "invalidation_conditions": validated.get("invalidation_conditions", []),
            "risk_conditions": validated.get("risk_conditions", []),
            "trade_state": validated.get("trade_state", "NO_TRADE"),
            "expected_horizon_minutes": validated.get("expected_horizon_minutes", 30),
            "material_changes": material_changes or [],
            "evidence_received": evidence is not None,
            "evidence_summary": self._evidence_summary(evidence) if evidence else None,
            "data_state": data_state,
        }

        logger.info(
            f"[{symbol}] AI outlook generated: bias={result['bias']} "
            f"confidence={result['confidence']} trade_state={result['trade_state']}"
        )
        return result

    def _build_prompt(self, symbol: str, state: dict, changes: list, evidence: dict) -> str:
        state_json = json.dumps(state, indent=2, default=str)
        changes_json = json.dumps(changes, indent=2, default=str) if changes else "[]"
        evidence_json = json.dumps(evidence, indent=2, default=str) if evidence else "{}"
        return AI_OUTLOOK_PROMPT + f"\n\nCurrent state:\n{state_json}\n\nEvidence:\n{evidence_json}\n\nRecent changes:\n{changes_json}"

    def _evidence_summary(self, evidence: dict) -> dict:
        if not evidence or not evidence.get("groups"):
            return None
        groups = evidence.get("groups", {})
        overall = evidence.get("overall", {})
        summary = {
            "overall_signal": overall.get("overall_signal"),
            "overall_strength": overall.get("overall_strength"),
            "conflict_detected": evidence.get("conflict", {}).get("detected", False),
            "groups": {},
        }
        for name, g in groups.items():
            summary["groups"][name] = {
                "signal": g.get("signal"),
                "strength": g.get("strength"),
                "availability": g.get("availability"),
            }
        return summary

    def _call_llm(self, prompt: str) -> dict:
        try:
            result = self.engine.generate("NIFTY", {}, use_llm=True)
            return result
        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            return self._fallback_outlook()

    def _fallback_outlook(self) -> dict:
        return {
            "bias": "MIXED",
            "confidence": 0,
            "market_regime": "MIXED",
            "summary": "AI outlook temporarily unavailable",
            "evidence": [],
            "watch_levels": [],
            "confirmation_conditions": [],
            "invalidation_conditions": [],
            "risk_conditions": ["temporary"],
            "trade_state": "NO_TRADE",
            "expected_horizon_minutes": 30,
        }

    def _validate(self, data: dict, symbol: str, timestamp: str) -> dict:
        if not isinstance(data, dict):
            return self._fallback_outlook()

        allowed_bias = {"BULLISH", "BEARISH", "RANGE", "MIXED"}
        allowed_trade = {"TRADE", "WAIT", "NO_TRADE"}
        allowed_regime = {"BULLISH", "BEARISH", "RANGE", "MIXED"}

        bias = data.get("bias", "MIXED")
        if bias not in allowed_bias:
            bias = "MIXED"

        confidence = data.get("confidence", 0)
        try:
            confidence = int(confidence)
            confidence = max(0, min(100, confidence))
        except (ValueError, TypeError):
            confidence = 0

        regime = data.get("market_regime", "MIXED")
        if regime not in allowed_regime:
            regime = "MIXED"

        trade_state = data.get("trade_state", "NO_TRADE")
        if trade_state not in allowed_trade:
            trade_state = "NO_TRADE"

        return {
            "bias": bias,
            "confidence": confidence,
            "market_regime": regime,
            "summary": str(data.get("summary", "")),
            "evidence": data.get("evidence", []) or [],
            "watch_levels": data.get("watch_levels", []) or [],
            "confirmation_conditions": data.get("confirmation_conditions", []) or [],
            "invalidation_conditions": data.get("invalidation_conditions", []) or [],
            "risk_conditions": data.get("risk_conditions", []) or [],
            "trade_state": trade_state,
            "expected_horizon_minutes": data.get("expected_horizon_minutes", 30),
        }
