from __future__ import annotations

from typing import Any, Optional


class RegimeEngine:
    def evaluate(self, market: dict[str, Any], options: dict[str, Any]) -> dict[str, Any]:
        trend = self._classify_trend(market)
        momentum = self._classify_momentum(market)
        vix = self._classify_vix(market)
        breadth = self._classify_breadth(market)
        options_class = self._classify_options(options)

        components = {
            "trend": trend,
            "momentum": momentum,
            "vix": vix,
            "breadth": breadth,
            "options": options_class,
        }

        reasons = []
        if trend != "UNAVAILABLE":
            reasons.append(self._trend_reason(market, trend))
        if momentum != "UNAVAILABLE":
            reasons.append(self._momentum_reason(market, momentum))
        if vix != "UNAVAILABLE":
            reasons.append(self._vix_reason(market, vix))
        if breadth != "UNAVAILABLE":
            reasons.append(self._breadth_reason(market, breadth))
        if options_class != "UNAVAILABLE":
            reasons.append(self._options_reason(options, options_class))

        data_quality = self._data_quality(components)

        if vix == "EXTREME":
            regime = "HIGH_VOLATILITY"
        elif vix == "HIGH":
            regime = "HIGH_VOLATILITY"
        else:
            regime = self._directional_regime(components)

        confidence = self._confidence(components, regime, market)

        if regime == "HIGH_VOLATILITY":
            confidence = min(confidence, 60)

        return {
            "regime": regime,
            "confidence": confidence,
            "components": components,
            "reasons": reasons,
            "data_quality": data_quality,
            "timestamp": self._timestamp(),
        }

    def _classify_trend(self, market: dict[str, Any]) -> str:
        sma20 = market.get("sma20")
        if sma20 is None:
            return "UNAVAILABLE"
        price = market.get("price")
        sma50 = market.get("sma50")
        if price is None:
            return "UNAVAILABLE"
        if price > sma20:
            if sma50 is None or sma20 > sma50:
                return "BULLISH"
            return "NEUTRAL"
        elif price < sma20:
            if sma50 is None or sma20 < sma50:
                return "BEARISH"
            return "NEUTRAL"
        return "NEUTRAL"

    def _trend_reason(self, market: dict[str, Any], trend: str) -> str:
        price = market.get("price")
        sma20 = market.get("sma20")
        sma50 = market.get("sma50")
        if trend == "BULLISH":
            base = f"Price {price:.2f} above SMA20 {sma20:.2f}"
            if sma50 is not None and sma20 > sma50:
                return f"{base} — SMA20 above SMA50 confirms uptrend"
            return base
        if trend == "BEARISH":
            base = f"Price {price:.2f} below SMA20 {sma20:.2f}"
            if sma50 is not None and sma20 < sma50:
                return f"{base} — SMA20 below SMA50 confirms downtrend"
            return base
        if sma50 is not None and sma20 <= sma50 and price > sma20:
            return f"Price {price:.2f} above SMA20 {sma20:.2f} but SMA20 at/below SMA50"
        if sma50 is not None and sma20 >= sma50 and price < sma20:
            return f"Price {price:.2f} below SMA20 {sma20:.2f} but SMA20 at/above SMA50"
        return f"Price {price:.2f} near SMA20 {sma20:.2f}"

    def _classify_momentum(self, market: dict[str, Any]) -> str:
        rsi = market.get("rsi")
        macd_hist = None
        macd = market.get("macd")
        if isinstance(macd, dict):
            macd_hist = macd.get("histogram")
        if rsi is None and macd_hist is None:
            return "UNAVAILABLE"
        if rsi is None and macd_hist is not None:
            if macd_hist >= 0:
                return "BULLISH"
            return "BEARISH"
        if macd_hist is None:
            if rsi >= 50:
                return "BULLISH"
            return "BEARISH"
        if rsi >= 50 and macd_hist >= 0:
            return "BULLISH"
        if rsi < 50 and macd_hist < 0:
            return "BEARISH"
        return "NEUTRAL"

    def _momentum_reason(self, market: dict[str, Any], momentum: str) -> str:
        rsi = market.get("rsi")
        macd = market.get("macd")
        macd_hist = None
        if isinstance(macd, dict):
            macd_hist = macd.get("histogram")
        if momentum == "BULLISH":
            parts = []
            if rsi is not None:
                parts.append(f"RSI {rsi:.1f} supports bullish momentum")
            if macd_hist is not None:
                parts.append(f"MACD histogram {macd_hist:+.2f} confirms direction")
            return "; ".join(parts) if parts else "Momentum bullish"
        if momentum == "BEARISH":
            parts = []
            if rsi is not None:
                parts.append(f"RSI {rsi:.1f} supports bearish momentum")
            if macd_hist is not None:
                parts.append(f"MACD histogram {macd_hist:+.2f} confirms direction")
            return "; ".join(parts) if parts else "Momentum bearish"
        if rsi is not None and macd_hist is not None:
            return f"RSI {rsi:.1f} and MACD histogram {macd_hist:+.2f} conflict — momentum neutral"
        if rsi is not None:
            return f"RSI {rsi:.1f} alone — momentum neutral"
        return "Momentum neutral"

    def _classify_vix(self, market: dict[str, Any]) -> str:
        vix = market.get("vix_close")
        if vix is None:
            return "UNAVAILABLE"
        if vix >= 25:
            return "EXTREME"
        if vix >= 20:
            return "HIGH"
        if vix >= 16:
            return "ELEVATED"
        if vix >= 13:
            return "NORMAL"
        if vix >= 11:
            return "LOW"
        return "VERY_LOW"

    def _vix_reason(self, market: dict[str, Any], vix: str) -> str:
        vix_close = market.get("vix_close", 0)
        labels = {
            "EXTREME": f"VIX {vix_close:.2f} — extreme volatility",
            "HIGH": f"VIX {vix_close:.2f} — high volatility",
            "ELEVATED": f"VIX {vix_close:.2f} — elevated volatility",
            "NORMAL": f"VIX {vix_close:.2f} — normal range",
            "LOW": f"VIX {vix_close:.2f} — low volatility",
            "VERY_LOW": f"VIX {vix_close:.2f} — very low volatility",
        }
        return labels.get(vix, f"VIX {vix_close:.2f}")

    def _classify_breadth(self, market: dict[str, Any]) -> str:
        ratio = market.get("advance_decline_ratio")
        if ratio is not None:
            if ratio > 1.0:
                return "POSITIVE"
            if ratio < 0.8:
                return "NEGATIVE"
            return "NEUTRAL"
        advances = market.get("advances")
        declines = market.get("declines")
        if advances is not None and declines is not None:
            if advances > declines:
                return "POSITIVE"
            if advances < declines:
                return "NEGATIVE"
            return "NEUTRAL"
        return "UNAVAILABLE"

    def _breadth_reason(self, market: dict[str, Any], breadth: str) -> str:
        advances = market.get("advances")
        declines = market.get("declines")
        ratio = market.get("advance_decline_ratio")
        if breadth == "POSITIVE":
            if advances is not None and declines is not None:
                return f"Breadth positive: advances {advances} vs declines {declines}"
            return f"Breadth positive: ratio {ratio:.2f}"
        if breadth == "NEGATIVE":
            if advances is not None and declines is not None:
                return f"Breadth negative: advances {advances} vs declines {declines}"
            return f"Breadth negative: ratio {ratio:.2f}"
        return "Breadth balanced"

    def _classify_options(self, options: dict[str, Any]) -> str:
        pcr = options.get("pcr")
        if pcr is None:
            return "UNAVAILABLE"
        if pcr < 0.7:
            return "BULLISH"
        if pcr > 1.5:
            return "BEARISH"
        return "NEUTRAL"

    def _options_reason(self, options: dict[str, Any], options_class: str) -> str:
        pcr = options.get("pcr", 0)
        labels = {
            "BULLISH": f"Options confirm bullish: PCR {pcr:.3f}",
            "BEARISH": f"Options confirm bearish: PCR {pcr:.3f}",
            "NEUTRAL": f"Options neutral: PCR {pcr:.3f}",
        }
        return labels.get(options_class, "Options data unavailable")

    def _directional_regime(self, components: dict[str, str]) -> str:
        bullish = 0.0
        bearish = 0.0
        for key in ("trend", "momentum"):
            if components.get(key) == "BULLISH":
                bullish += 1.0
            elif components.get(key) == "BEARISH":
                bearish += 1.0
        if components.get("options") == "BULLISH":
            bullish += 0.5
        elif components.get("options") == "BEARISH":
            bearish += 0.5
        if bullish > bearish + 0.5:
            return "BULLISH"
        if bearish > bullish + 0.5:
            return "BEARISH"
        return "SIDEWAYS"

    def _confidence(self, components: dict[str, str], regime: str, market: dict[str, Any]) -> int:
        confidence = 50
        for key in ("trend", "momentum", "options"):
            if components.get(key) == regime:
                confidence += 15
        if components.get("breadth") == regime:
            confidence += 10
        vix = components.get("vix")
        if vix in ("ELEVATED", "HIGH", "EXTREME"):
            confidence -= 10
        for key in ("trend", "momentum", "vix", "breadth", "options"):
            if components.get(key) == "UNAVAILABLE":
                confidence -= 10
        adx = market.get("adx")
        if adx is not None and adx >= 25 and regime != "HIGH_VOLATILITY":
            confidence += 5
        return max(15, min(100, confidence))

    def _data_quality(self, components: dict[str, str]) -> str:
        available = sum(1 for v in components.values() if v != "UNAVAILABLE")
        if available == 5:
            return "LIVE"
        if available >= 1:
            return "PARTIAL"
        return "UNAVAILABLE"

    def _timestamp(self) -> str:
        from datetime import datetime, timezone
        return datetime.now(timezone.utc).isoformat()
