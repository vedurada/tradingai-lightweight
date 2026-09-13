from __future__ import annotations

REGIME_ALIASES: dict[str, str] = {
    "TRENDING_BULLISH": "BULLISH",
    "BULLISH": "BULLISH",
    "TRENDING_BEARISH": "BEARISH",
    "BEARISH": "BEARISH",
    "RANGE_BOUND": "SIDEWAYS",
    "SIDEWAYS": "SIDEWAYS",
    "HIGH_VOLATILITY": "HIGH_VOLATILITY",
}

CANONICAL_REGIMES = {"BULLISH", "BEARISH", "SIDEWAYS", "HIGH_VOLATILITY"}

UNKNOWN_REGIME = "UNKNOWN"


def normalize_regime(regime: str) -> str:
    if regime is None:
        return UNKNOWN_REGIME
    key = str(regime).strip().upper()
    if key in CANONICAL_REGIMES:
        return key
    if key in REGIME_ALIASES:
        return REGIME_ALIASES[key]
    return UNKNOWN_REGIME
