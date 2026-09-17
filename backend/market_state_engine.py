from __future__ import annotations

import json
import os
import sys
import logging
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from indicators import calculate_all_indicators

logger = logging.getLogger("tradingai.market_state")


class MarketStateEngine:
    def __init__(self):
        self.thresholds = {
            "vwap_distance_pct": 0.5,
            "adx_strong": 30,
            "adx_weak": 20,
            "rsi_overbought": 70,
            "rsi_oversold": 30,
            "volatility_high": 20,
            "volatility_normal": 15,
            "trend_ema_ratio": 0.02,
        }

    def evaluate(self, symbol: str, snapshot: dict) -> dict:
        indicators = snapshot.get("indicators", {}) if isinstance(snapshot, dict) else {}
        if not indicators:
            return self._unavailable_state(symbol)

        market_regime = self._determine_regime(indicators, snapshot)
        trend_state = self._determine_trend(indicators, snapshot)
        price_vs_vwap = self._determine_price_vs_vwap(indicators, snapshot)
        volatility_state = self._determine_volatility(indicators, snapshot)
        trade_state = self._determine_trade_state(
            market_regime, trend_state, price_vs_vwap, volatility_state, indicators,
        )

        state = {
            "symbol": symbol,
            "market_regime": market_regime,
            "trend_state": trend_state,
            "price_vs_vwap": price_vs_vwap,
            "volatility_state": volatility_state,
            "trade_state": trade_state,
            "calculated_at": snapshot.get("candle_timestamp", snapshot.get("snapshot_time", "")),
        }

        logger.info(
            f"[{symbol}] State: regime={market_regime} trend={trend_state} "
            f"vwap={price_vs_vwap} vol={volatility_state} trade={trade_state}"
        )
        return state

    def _unavailable_state(self, symbol: str) -> dict:
        return {
            "symbol": symbol,
            "market_regime": "UNAVAILABLE",
            "trend_state": "UNKNOWN",
            "price_vs_vwap": "UNKNOWN",
            "volatility_state": "UNKNOWN",
            "trade_state": "NO_TRADE",
            "calculated_at": "",
        }

    def _determine_regime(self, indicators: dict, snapshot: dict) -> str:
        rsi = indicators.get("rsi")
        adx = indicators.get("adx")
        trend = snapshot.get("trend_state", "NEUTRAL")
        ema9 = indicators.get("ema9")
        ema200 = indicators.get("ema200")

        regime_score = 0.0

        if trend == "STRONG_UP":
            regime_score += 2
        elif trend == "UP":
            regime_score += 1
        elif trend == "STRONG_DOWN":
            regime_score -= 2
        elif trend == "DOWN":
            regime_score -= 1

        if rsi is not None:
            try:
                rsi_val = float(rsi)
                if rsi_val > 65:
                    regime_score += 0.5
                elif rsi_val < 35:
                    regime_score -= 0.5
            except (TypeError, ValueError):
                pass

        if ema9 is not None and ema200 is not None:
            try:
                if float(ema9) > float(ema200):
                    regime_score += 1
                else:
                    regime_score -= 1
            except (TypeError, ValueError):
                pass

        if adx is not None:
            try:
                if float(adx) < 20:
                    return "RANGE"
            except (TypeError, ValueError):
                pass

        if regime_score >= 2.5:
            return "BULLISH"
        if regime_score <= -2.5:
            return "BEARISH"
        if abs(regime_score) < 1.0:
            return "RANGE"
        return "MIXED"

    def _determine_trend(self, indicators: dict, snapshot: dict) -> str:
        ema9 = indicators.get("ema9")
        ema21 = indicators.get("ema21")
        ema20 = indicators.get("ema20")
        ema200 = indicators.get("ema200")
        close = snapshot.get("close")

        if close is None or not all(v is not None for v in (ema9, ema21, ema20, ema200)):
            return "NEUTRAL"

        try:
            close = float(close)
            ema9 = float(ema9)
            ema21 = float(ema21)
            ema20 = float(ema20)
            ema200 = float(ema200)
        except (TypeError, ValueError):
            return "NEUTRAL"

        above_200 = close > ema200
        above_20 = close > ema20
        ema_aligned = ema9 > ema21 > ema20 if (ema9 > ema21 > ema20) else False

        if above_200 and above_20 and ema_aligned:
            return "STRONG_UP"
        if above_200 and above_20:
            return "UP"
        if not above_200 and not above_20 and (ema20 > ema21 > ema9):
            return "STRONG_DOWN"
        if not above_200 and not above_20:
            return "DOWN"
        return "NEUTRAL"

    def _determine_price_vs_vwap(self, indicators: dict, snapshot: dict) -> str:
        vwap = indicators.get("vwap")
        close = snapshot.get("close")

        if vwap is None or close is None or vwap == 0:
            return "UNKNOWN"

        try:
            diff_pct = (float(close) - float(vwap)) / float(vwap) * 100
        except (TypeError, ValueError, ZeroDivisionError):
            return "UNKNOWN"

        if diff_pct > 0.5:
            return "ABOVE"
        if diff_pct < -0.5:
            return "BELOW"
        return "NEAR"

    def _determine_volatility(self, indicators: dict, snapshot: dict) -> str:
        atr = indicators.get("atr")
        bollinger_width = None
        bb = indicators.get("bollinger_bands")
        if isinstance(bb, dict):
            bollinger_width = bb.get("width")
        vix = snapshot.get("vix")
        rsi = indicators.get("rsi")
        close = snapshot.get("close")

        score = 0.0

        if atr is not None and close is not None:
            try:
                ratio = float(atr) / float(close) * 100
                if ratio > 1.5:
                    score += 2
                elif ratio > 0.8:
                    score += 1
            except (TypeError, ValueError, ZeroDivisionError):
                pass

        if bollinger_width is not None:
            try:
                if float(bollinger_width) > 2.0:
                    score += 2
                elif float(bollinger_width) > 1.0:
                    score += 1
            except (TypeError, ValueError):
                pass

        if vix is not None:
            try:
                if float(vix) > 20:
                    score += 2
                elif float(vix) > 15:
                    score += 1
            except (TypeError, ValueError):
                pass

        if score >= 4:
            return "HIGH"
        if score >= 2:
            return "NORMAL"
        return "LOW"

    def _determine_trade_state(
        self, regime: str, trend: str, vwap: str, volatility: str, indicators: dict,
    ) -> str:
        if regime in ("BEARISH",) and volatility == "HIGH":
            return "NO_TRADE"
        if regime == "RANGE" and trend == "NEUTRAL":
            return "NO_TRADE"
        if vwap == "UNKNOWN" or trend == "UNKNOWN":
            return "NO_TRADE"

        rsi = indicators.get("rsi")
        adx = indicators.get("adx")

        if regime == "BULLISH" and trend in ("UP", "STRONG_UP") and vwap == "ABOVE":
            if rsi is not None:
                try:
                    if float(rsi) > 80:
                        return "WAIT"
                except (TypeError, ValueError):
                    pass
            if adx is not None:
                try:
                    if float(adx) > 25:
                        return "TRADE"
                except (TypeError, ValueError):
                    pass
            return "WAIT"

        if regime == "BEARISH" and trend in ("DOWN", "STRONG_DOWN") and vwap == "BELOW":
            return "WAIT"

        if regime == "MIXED" or volatility == "HIGH":
            return "WAIT"

        return "WAIT"


def evaluate_market_state(symbol: str, snapshot: dict) -> dict:
    engine = MarketStateEngine()
    return engine.evaluate(symbol, snapshot)
