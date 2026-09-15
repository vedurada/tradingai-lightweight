"""TradingAI.in — Indicators Test Suite (~25 tests).

Covers SMA/EMA, MACD, RSI, ADX, ATR, VWAP, Pivot/CPR/Bollinger,
Support/Resistance, and calculate_all_indicators integration.
Per TEST_PLAN_SCOPE.md Section 4.1.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from backend.indicators import (
    calculate_ema, calculate_vwap, calculate_pivot, calculate_cpr,
    calculate_bollinger_bands, calculate_rsi, calculate_macd,
    calculate_adx, calculate_atr, calculate_support_resistance,
    calculate_all_indicators,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ═══════════════════════════════════════════════════════
# Price Builders
# ═══════════════════════════════════════════════════════

def make_closes(start, count, step=1.0):
    return [start + step * i for i in range(count)]


def make_ohlcv(start, count, step=1.0):
    return [
        {"open": start + step * i, "high": start + step * i + 2,
         "low": start + step * i - 1, "close": start + step * i + 0.5,
         "volume": 1000}
        for i in range(count)
    ]


# ═══════════════════════════════════════════════════════
# EMA / SMA (via calculate_ema)
# ═══════════════════════════════════════════════════════

class TestEMA:
    def test_ema_insufficient_data(self):
        assert calculate_ema([1, 2, 3], 10) is None

    def test_ema_returns_number(self):
        r = calculate_ema(make_closes(100, 30), 10)
        assert r is not None
        assert isinstance(r, float)

    def test_ema_between_first_last(self):
        r = calculate_ema(make_closes(100, 30), 10)
        assert r >= 100, f"EMA {r} below first value"
        assert r <= 130, f"EMA {r} above last value"

    def test_ema_closer_to_recent(self):
        r = calculate_ema(make_closes(100, 30), 10)
        dist_to_last = abs(r - 129)
        dist_to_first = abs(r - 100)
        assert dist_to_last < dist_to_first, f"EMA {r} not closer to recent values"

    def test_ema_period_20(self):
        r = calculate_ema(make_closes(50, 30), 20)
        assert r is not None

    def test_ema_period_50(self):
        r = calculate_ema(make_closes(50, 60), 50)
        assert r is not None


# ═══════════════════════════════════════════════════════
# VWAP
# ═══════════════════════════════════════════════════════

class TestVWAP:
    def test_vwap_empty(self):
        assert calculate_vwap([]) == 0.0

    def test_vwap_basic(self):
        ohlcv = make_ohlcv(100, 10)
        r = calculate_vwap(ohlcv)
        assert isinstance(r, float)
        assert 95 < r < 110

    def test_vwap_zero_volume(self):
        data = [{"high": 100, "low": 95, "close": 98, "volume": 0} for _ in range(5)]
        assert calculate_vwap(data) == 0.0


# ═══════════════════════════════════════════════════════
# Pivot / CPR
# ═══════════════════════════════════════════════════════

class TestPivot:
    def test_pivot_basic(self):
        quote = {"high": 110, "low": 90, "close": 100}
        r = calculate_pivot(quote)
        assert "pivot" in r
        assert "r1" in r and "s1" in r
        assert "r3" in r and "s3" in r

    def test_pivot_relations(self):
        quote = {"high": 110, "low": 90, "close": 100}
        r = calculate_pivot(quote)
        assert r["r1"] > r["pivot"] > r["s1"]
        assert r["r2"] > r["r1"]
        assert r["s2"] < r["s1"]

    def test_pivot_from_prev_close(self):
        quote = {"high": 110, "low": 90, "close": None, "previous_close": 95}
        r = calculate_pivot(quote)
        assert r["pivot"] == round((110 + 90 + 95) / 3, 2), f"Got {r['pivot']}"


class TestCPR:
    def test_cpr_basic(self):
        pivot = {"pivot": 100, "r1": 110, "s1": 90}
        r = calculate_cpr(pivot)
        assert "bc" in r and "tc" in r
        assert "classification" in r
        assert r["pivot"] == 100

    def test_cpr_narrow(self):
        pivot = {"pivot": 100, "r1": 100.1, "s1": 99.9}
        r = calculate_cpr(pivot)
        assert r["classification"] == "NARROW"

    def test_cpr_wide(self):
        pivot = {"pivot": 100, "r1": 120, "s1": 80}
        r = calculate_cpr(pivot)
        assert r["classification"] == "WIDE"


# ═══════════════════════════════════════════════════════
# Bollinger Bands
# ═══════════════════════════════════════════════════════

class TestBollingerBands:
    def test_bb_insufficient(self):
        assert calculate_bollinger_bands([1, 2, 3], 20) is None

    def test_bb_basic(self):
        closes = make_closes(100, 30)
        r = calculate_bollinger_bands(closes, 20)
        assert "upper" in r and "middle" in r and "lower" in r
        assert r["upper"] > r["middle"] > r["lower"]

    def test_bb_contains_price(self):
        closes = make_closes(100, 30)
        r = calculate_bollinger_bands(closes, 20)
        last = closes[-1]
        assert r["lower"] <= last <= r["upper"]


# ═══════════════════════════════════════════════════════
# RSI
# ═══════════════════════════════════════════════════════

class TestRSI:
    def test_rsi_insufficient(self):
        assert calculate_rsi([1] * 10) is None

    def test_rsi_overbought(self):
        closes = [100 + i for i in range(20)]  # Strong uptrend
        r = calculate_rsi(closes, 14)
        assert r > 70, f"Expected >70, got {r}"

    def test_rsi_oversold(self):
        closes = [100 - i for i in range(20)]  # Strong downtrend
        r = calculate_rsi(closes, 14)
        assert r < 30, f"Expected <30, got {r}"

    def test_rsi_neutral(self):
        closes = [100 + (i % 3 - 1) for i in range(30)]  # Sideways
        r = calculate_rsi(closes, 14)
        assert 30 <= r <= 70, f"Expected 30-70, got {r}"

    def test_rsi_range(self):
        closes = make_closes(100, 25)
        r = calculate_rsi(closes, 14)
        assert 0 <= r <= 100


# ═══════════════════════════════════════════════════════
# MACD
# ═══════════════════════════════════════════════════════

class TestMACD:
    def test_macd_insufficient(self):
        assert calculate_macd([1] * 20) is None

    def test_macd_returns_dict(self):
        closes = make_closes(100, 40)
        r = calculate_macd(closes)
        assert "macd" in r and "signal" in r and "histogram" in r

    def test_macd_values_numeric(self):
        closes = make_closes(100, 40)
        r = calculate_macd(closes)
        assert isinstance(r["macd"], (int, float))
        assert isinstance(r["signal"], (int, float))
        assert isinstance(r["histogram"], (int, float))


# ═══════════════════════════════════════════════════════
# ADX
# ═══════════════════════════════════════════════════════

class TestADX:
    def test_adx_insufficient(self):
        assert calculate_adx([1]*5, [1]*5, [1]*10) is None

    def test_adx_basic(self):
        closes = make_closes(100, 30)
        highs = [c + 2 for c in closes]
        lows = [c - 1 for c in closes]
        r = calculate_adx(highs, lows, closes, 14)
        assert isinstance(r, float)
        assert 0 <= r <= 100

    def test_adx_trending(self):
        closes = [100 + i * 0.5 for i in range(30)]
        highs = [c + 1 for c in closes]
        lows = [c - 1 for c in closes]
        r = calculate_adx(highs, lows, closes, 14)
        assert r > 20, f"Trending should have ADX > 20, got {r}"


# ═══════════════════════════════════════════════════════
# ATR
# ═══════════════════════════════════════════════════════

class TestATR:
    def test_atr_insufficient(self):
        assert calculate_atr([1]*5, [1]*5, [1]*10) is None

    def test_atr_basic(self):
        closes = make_closes(100, 30)
        highs = [c + 2 for c in closes]
        lows = [c - 1 for c in closes]
        r = calculate_atr(highs, lows, closes, 14)
        assert isinstance(r, float)
        assert r > 0


# ═══════════════════════════════════════════════════════
# Support/Resistance
# ═══════════════════════════════════════════════════════

class TestSupportResistance:
    def test_sr_insufficient(self):
        r = calculate_support_resistance(make_ohlcv(100, 5), window=10)
        assert r == {"support": [], "resistance": []}

    def test_sr_basic(self):
        ohlcv = make_ohlcv(100, 30)
        r = calculate_support_resistance(ohlcv)
        assert "support" in r and "resistance" in r
        assert "prev_high" in r and "prev_low" in r

    def test_sr_resistance_above_support(self):
        ohlcv = make_ohlcv(100, 30)
        r = calculate_support_resistance(ohlcv)
        if r["resistance"] and r["support"]:
            assert r["resistance"][0] > r["support"][0], "Resistance should be above support"


# ═══════════════════════════════════════════════════════
# Integration
# ═══════════════════════════════════════════════════════

class TestAllIndicators:
    def test_all_basic(self):
        ohlcv = make_ohlcv(100, 30)
        quote = {"high": 105, "low": 95, "close": 100}
        r = calculate_all_indicators(ohlcv, quote)
        assert "vwap" in r
        assert "pivot" in r
        assert "rsi" in r
        assert "macd" in r
        assert "adx" in r
        assert "atr" in r
        assert "support_resistance" in r
        assert "bollinger_bands" in r
        assert "ema20" in r
        assert "ema50" in r

    def test_all_has_timestamp(self):
        ohlcv = make_ohlcv(100, 30)
        quote = {"high": 105, "low": 95, "close": 100}
        r = calculate_all_indicators(ohlcv, quote)
        assert "timestamp" in r

    def test_all_rsi_in_range(self):
        ohlcv = make_ohlcv(100, 30)
        quote = {"high": 105, "low": 95, "close": 100}
        r = calculate_all_indicators(ohlcv, quote)
        if r["rsi"] is not None:
            assert 0 <= r["rsi"] <= 100
