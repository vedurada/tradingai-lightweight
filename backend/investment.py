from __future__ import annotations

"""Investment views for stocks (NOT intraday index signals).

Two horizons, computed from daily candles + stored fundamentals:
- SHORT (positional, weeks): daily trend (SMA20/50) + RSI momentum.
- LONG (months): SMA200 trend + 52-week position + valuation (P/E),
  analyst upside, dividend. Rating: ACCUMULATE / HOLD / AVOID.

Thresholds are documented heuristics for Indian large/mid-caps, not
universal truths — tune them in one place below.
"""

from typing import Any, Optional


def _sma(values: list[float], period: int) -> Optional[float]:
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def _rsi(closes: list[float], period: int = 14) -> Optional[float]:
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100.0
    avg_gain = sum(gains[-period:]) / period
    return round(100 - 100 / (1 + avg_gain / avg_loss), 2)


def short_term_view(closes: list[float], quote_price: float = 0) -> dict[str, Any]:
    """Positional view for the coming weeks. Returns BUY / HOLD / EXIT."""
    price = quote_price or (closes[-1] if closes else 0)
    sma20 = _sma(closes, 20)
    sma50 = _sma(closes, 50)
    rsi = _rsi(closes)
    score = 0
    reasons: list[str] = []
    if sma20 and price > sma20:
        score += 1
        reasons.append("above 20-day average")
    elif sma20:
        score -= 1
        reasons.append("below 20-day average")
    if sma50 and price > sma50:
        score += 1
        reasons.append("above 50-day average")
    elif sma50:
        score -= 1
        reasons.append("below 50-day average")
    if sma20 and sma50:
        if sma20 > sma50:
            score += 1
            reasons.append("short trend above medium trend")
        else:
            score -= 1
            reasons.append("short trend below medium trend")
    if rsi is not None:
        if 50 <= rsi <= 70:
            score += 1
            reasons.append(f"healthy momentum (RSI {rsi})")
        elif rsi is not None and rsi < 30:
            score += 1
            reasons.append(f"oversold bounce setup (RSI {rsi})")
        elif rsi is not None and rsi > 75:
            score -= 2
            reasons.append(f"overbought (RSI {rsi})")
    if len(closes) >= 20 and closes[-20]:
        ret20 = (price - closes[-20]) / closes[-20] * 100
        if ret20 > 8:
            score += 1
            reasons.append(f"+{ret20:.1f}% in 20 sessions")
        elif ret20 < -8:
            score -= 1
            reasons.append(f"{ret20:.1f}% in 20 sessions")
    if score >= 3:
        rating = "BUY"
    elif score <= -2:
        rating = "EXIT"
    else:
        rating = "HOLD"
    confidence = min(80, 45 + abs(score) * 8)
    return {"rating": rating, "score": score, "confidence": confidence,
            "rsi": rsi, "sma20": sma20, "sma50": sma50,
            "reason": "; ".join(reasons) or "mixed signals"}


def long_term_view(closes: list[float], fundamentals: dict, quote_price: float = 0) -> dict[str, Any]:
    """Investment view for the coming months. Returns ACCUMULATE / HOLD / AVOID."""
    price = quote_price or (closes[-1] if closes else 0)
    f = fundamentals or {}
    sma200 = _sma(closes, 200)
    hi52 = f.get("fiftyTwoWeekHigh") or 0
    lo52 = f.get("fiftyTwoWeekLow") or 0
    pe = f.get("trailingPE")
    analyst_target = f.get("targetMeanPrice") or 0
    div_yield = f.get("dividendYield") or 0
    margins = f.get("profitMargins") or 0
    score = 0
    reasons: list[str] = []
    if sma200 and price > sma200:
        score += 2
        reasons.append("above 200-day average (primary uptrend)")
    elif sma200:
        score -= 2
        reasons.append("below 200-day average")
    elif len(closes) >= 50:
        score += 0
        reasons.append("200-day history incomplete")
    if hi52 and lo52 and hi52 > lo52:
        pos = (price - lo52) / (hi52 - lo52) * 100
        if pos >= 50:
            score += 1
            reasons.append(f"upper half of 52w range ({pos:.0f}%)")
        elif pos < 25:
            score -= 1
            reasons.append(f"lower quartile of 52w range ({pos:.0f}%)")
    if isinstance(pe, (int, float)) and pe > 0:
        if pe < 20:
            score += 1
            reasons.append(f"reasonable valuation (P/E {pe:.1f})")
        elif pe > 35:
            score -= 1
            reasons.append(f"expensive valuation (P/E {pe:.1f})")
    if analyst_target and price:
        upside = (analyst_target - price) / price * 100
        if upside > 15:
            score += 1
            reasons.append(f"analyst upside {upside:.0f}%")
        elif upside < 0:
            score -= 1
            reasons.append("analyst target below current price")
    if isinstance(div_yield, (int, float)) and div_yield > 1:
        score += 0.5
        reasons.append(f"dividend yield {div_yield:.2f}%")
    if isinstance(margins, (int, float)) and margins > 0.10:
        score += 0.5
        reasons.append("double-digit profit margins")
    if score >= 3:
        rating = "ACCUMULATE"
    elif score <= 0:
        rating = "AVOID"
    else:
        rating = "HOLD"
    confidence = min(80, 45 + abs(score) * 8)
    fair_value = analyst_target or (hi52 or None)
    return {"rating": rating, "score": score, "confidence": int(confidence),
            "sma200": sma200, "pe": pe, "analyst_target": analyst_target or None,
            "fair_value": fair_value,
            "reason": "; ".join(reasons) or "insufficient data"}


def swing_levels(closes: list[float], price: float, lookback: int = 20) -> dict[str, float]:
    """Positional target/stop from recent swing high/low."""
    window = closes[-lookback:] if len(closes) >= 5 else closes
    hi = max(window) if window else price
    lo = min(window) if window else price
    target = hi if hi > price else round(price * 1.08, 2)
    stop = lo if lo < price and (price - lo) / price <= 0.10 else round(price * 0.94, 2)
    return {"target": round(target, 2), "stop": round(stop, 2)}
