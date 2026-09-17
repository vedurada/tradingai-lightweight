from __future__ import annotations

import json
import os
import sys
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logger = logging.getLogger("tradingai.evidence")

ENGINE_VERSION = "1.0.0-phase40"


def _safe(v, default=0.0):
    try:
        if v is None:
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def _price_vs_vwap(vwap: float, price: float) -> str:
    if vwap is None or price is None or vwap == 0:
        return "UNKNOWN"
    diff_pct = (price - vwap) / vwap * 100
    if diff_pct > 0.5:
        return "ABOVE"
    elif diff_pct < -0.5:
        return "BELOW"
    return "NEAR"


def _is_available(value) -> bool:
    if value is None:
        return False
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False


def _availability_from_state(data_state: str, has_value: bool) -> str:
    if not has_value:
        return "UNAVAILABLE"
    if data_state in ("UNAVAILABLE",):
        return "UNAVAILABLE"
    if data_state in ("LIVE",):
        return "LIVE"
    if data_state == "DELAYED":
        return "DELAYED"
    if data_state in ("EOD", "HISTORICAL"):
        return data_state
    return "AVAILABLE"


def _classify_direction(bullish: int, bearish: int, total: int) -> tuple:
    directional = max(1, bullish + bearish)
    if directional == 0:
        return "NEUTRAL", "WEAK", "WEAK"
    if bullish > bearish and bullish > directional * 0.5:
        return "BULLISH", "STRONG" if bullish >= 3 else "MODERATE", "MODERATE"
    if bearish > bullish and bearish > directional * 0.5:
        return "BEARISH", "STRONG" if bearish >= 3 else "MODERATE", "MODERATE"
    if bullish == bearish and bullish > 0:
        return "MIXED", "MODERATE", "WEAK"
    if bullish > bearish:
        return "MIXED", "WEAK", "WEAK"
    if bearish > bullish:
        return "MIXED", "WEAK", "WEAK"
    return "NEUTRAL", "WEAK", "WEAK"


def _strength_from_count(count: int, total: int) -> str:
    if total == 0:
        return "WEAK"
    ratio = count / total
    if ratio >= 0.75:
        return "STRONG"
    if ratio >= 0.5:
        return "MODERATE"
    return "WEAK"


def _detect_conflict_level(bullish: int, bearish: int, neutral: int) -> str:
    total = bullish + bearish + neutral
    if total == 0:
        return "NONE"
    if bullish > 0 and bearish > 0:
        return "HIGH" if abs(bullish - bearish) <= 1 else "MODERATE"
    return "NONE"


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class MarketEvidenceEngine:
    def __init__(self, config: dict = None):
        self.config = config or {}
        self._defaults = {
            "ema": {"fast": 20, "slow": 50},
            "rsi": {"oversold": 30, "overbought": 70},
            "adx": {"trend_threshold": 20, "strong_threshold": 30},
            "vwap": {"distance_pct": 0.5},
            "volatility": {"high_vix": 20, "normal_vix": 15},
            "atr": {"high_ratio": 1.5, "normal_ratio": 0.8},
        }
        for key, val in self._defaults.items():
            if key not in self.config:
                self.config[key] = val

    def evaluate(self, snapshot: dict, data_state: str = "LIVE", symbol: str = "NIFTY") -> dict:
        if not snapshot:
            return self._unavailable(symbol, data_state)

        trend = self._trend_evidence(snapshot, data_state)
        momentum = self._momentum_evidence(snapshot, data_state)
        structure = self._structure_evidence(snapshot, data_state)
        volatility = self._volatility_evidence(snapshot, data_state)
        options = self._options_evidence(snapshot, data_state)
        confirmation = self._confirmation_evidence(snapshot, data_state, symbol)

        groups = {"trend": trend, "momentum": momentum, "structure": structure,
                   "volatility": volatility, "options": options, "confirmation": confirmation}

        overall = self._aggregate(groups)
        conflict = self._detect_conflict(groups)

        result = {
            "instrument": symbol,
            "candle_timestamp": snapshot.get("candle_timestamp", snapshot.get("timestamp", "")),
            "evidence_id": snapshot.get("evidence_id", ""),
            "snapshot_id": snapshot.get("snapshot_id", ""),
            "groups": groups,
            "overall": overall,
            "conflict": conflict,
            "data_state": data_state,
            "engine_version": ENGINE_VERSION,
            "generated_at": _now_utc(),
        }

        logger.info(
            f"[{symbol}] Evidence: overall={overall['overall_signal']} "
            f"conflict={conflict['detected']} strength={overall['overall_strength']}")
        return result

    def _unavailable(self, symbol: str, data_state: str) -> dict:
        return {
            "instrument": symbol,
            "candle_timestamp": "",
            "evidence_id": "",
            "snapshot_id": "",
            "groups": {name: self._empty_group(name) for name in
                       ["trend", "momentum", "structure", "volatility", "options", "confirmation"]},
            "overall": {
                "overall_signal": "INSUFFICIENT_DATA", "overall_strength": "NONE",
                "bullish_groups": 0, "bearish_groups": 0, "neutral_groups": 0,
                "unavailable_groups": 6, "conflict_level": "NONE"},
            "conflict": {"detected": False, "groups": [], "severity": "NONE"},
            "data_state": data_state,
            "engine_version": ENGINE_VERSION,
            "generated_at": _now_utc(),
        }

    def _empty_group(self, name: str) -> dict:
        return {
            "group": name, "availability": "UNAVAILABLE", "signal": "NEUTRAL",
            "strength": "WEAK", "confidence": "WEAK",
            "rules_triggered": [], "rules_not_triggered": [],
            "data_used": {}, "reason": "No data available for this evidence group",
            "timestamp": _now_utc(),
        }

    def _base_group(self, group_name: str, data_state: str) -> dict:
        return {
            "group": group_name,
            "availability": "UNAVAILABLE",
            "signal": "NEUTRAL",
            "strength": "WEAK",
            "confidence": "WEAK",
            "rules_triggered": [],
            "rules_not_triggered": [],
            "data_used": {},
            "reason": "",
            "timestamp": _now_utc(),
        }

    def _finalize(self, group: dict, data_state: str, total_available: int) -> dict:
        group["availability"] = _availability_from_state(data_state, total_available > 0)
        signal = group.get("signal", "NEUTRAL")
        bullish = group.get("_bullish", 0)
        bearish = group.get("_bearish", 0)
        group["strength"] = _strength_from_count(max(bullish, bearish), total_available)
        group["confidence"] = "STRONG" if group["strength"] == "STRONG" else "MODERATE"
        return group

    def _trend_evidence(self, snapshot: dict, data_state: str) -> dict:
        g = self._base_group("trend", data_state)
        close = snapshot.get("close")
        ema9 = snapshot.get("ema9")
        ema20 = snapshot.get("ema20")
        ema50 = snapshot.get("ema50")
        ema200 = snapshot.get("ema200")
        vwap = snapshot.get("vwap")
        adx = snapshot.get("adx")

        checks = [_is_available(close), _is_available(ema9), _is_available(ema20),
                   _is_available(ema50), _is_available(vwap), _is_available(adx)]
        total = sum(checks)

        if total == 0:
            g["reason"] = "No trend data available"
            return g

        bullish = 0
        bearish = 0

        if _is_available(vwap) and _is_available(close):
            vp = _price_vs_vwap(vwap, close)
            g["data_used"]["price_vs_vwap"] = vp
            if vp == "ABOVE":
                bullish += 1; g["rules_triggered"].append("price_above_vwap")
            elif vp == "BELOW":
                bearish += 1; g["rules_triggered"].append("price_below_vwap")
            else:
                g["rules_not_triggered"].append("price_near_vwap")

        if _is_available(ema9) and _is_available(ema20):
            above = float(ema9) > float(ema20)
            g["data_used"]["ema9_ema20"] = {"ema9": ema9, "ema20": ema20, "fast_above": above}
            if above: bullish += 1; g["rules_triggered"].append("ema9_above_ema20")
            else: bearish += 1; g["rules_triggered"].append("ema9_below_ema20")

        if _is_available(ema20) and _is_available(ema50):
            above = float(ema20) > float(ema50)
            g["data_used"]["ema20_ema50"] = {"ema20": ema20, "ema50": ema50, "mid_above": above}
            if above: bullish += 1; g["rules_triggered"].append("ema20_above_ema50")
            else: bearish += 1; g["rules_triggered"].append("ema20_below_ema50")

        if _is_available(ema200) and _is_available(close):
            above = float(close) > float(ema200)
            g["data_used"]["close_ema200"] = {"close": close, "ema200": ema200, "above": above}
            if above: bullish += 1; g["rules_triggered"].append("close_above_ema200")
            else: bearish += 1; g["rules_triggered"].append("close_below_ema200")

        if _is_available(adx):
            g["data_used"]["adx"] = float(adx)
            if float(adx) >= self.config["adx"]["strong_threshold"]:
                g["rules_triggered"].append("adx_strong")
            elif float(adx) >= self.config["adx"]["trend_threshold"]:
                g["rules_triggered"].append("adx_trending")
            else:
                g["rules_not_triggered"].append("adx_weak")

        signal, _, _ = _classify_direction(bullish, bearish, total)
        g.update({"signal": signal, "_bullish": bullish, "_bearish": bearish})
        return self._finalize(g, data_state, total)

    def _momentum_evidence(self, snapshot: dict, data_state: str) -> dict:
        g = self._base_group("momentum", data_state)
        rsi = snapshot.get("rsi")
        macd = snapshot.get("macd")
        macd_signal = snapshot.get("macd_signal")
        data_state_val = snapshot.get("data_state", data_state)

        rsi_av = _is_available(rsi)
        macd_av = _is_available(macd) and _is_available(macd_signal)
        total = sum([rsi_av, macd_av])

        if total == 0:
            g["reason"] = "No momentum data available"
            return g

        bullish = 0; bearish = 0

        if rsi_av:
            rv = float(rsi)
            g["data_used"]["rsi"] = rv
            if rv > self.config["rsi"]["overbought"]:
                bearish += 1; g["rules_triggered"].append("rsi_overbought")
            elif rv < self.config["rsi"]["oversold"]:
                bearish += 1; g["rules_triggered"].append("rsi_oversold")
                g["notes"] = "RSI oversold but not necessarily bullish (context-dependent)"
            else:
                g["rules_not_triggered"].append("rsi_neutral")

        if macd_av:
            above = float(macd) > float(macd_signal)
            g["data_used"]["macd"] = {"macd": float(macd), "signal": float(macd_signal), "above": above}
            if above: bullish += 1; g["rules_triggered"].append("macd_above_signal")
            else: bearish += 1; g["rules_triggered"].append("macd_below_signal")

        signal, _, _ = _classify_direction(bullish, bearish, total)
        g.update({"signal": signal, "_bullish": bullish, "_bearish": bearish})
        return self._finalize(g, data_state, total)

    def _structure_evidence(self, snapshot: dict, data_state: str) -> dict:
        g = self._base_group("structure", data_state)
        close = snapshot.get("close")
        prev_day_high = snapshot.get("prev_day_high")
        prev_day_low = snapshot.get("prev_day_low")
        support = snapshot.get("support")
        resistance = snapshot.get("resistance")
        data_state_val = snapshot.get("data_state", data_state)

        checks = sum(_is_available(v) for v in [close, prev_day_high, prev_day_low, support, resistance])
        total = max(1, checks)

        if checks == 0:
            g["reason"] = "No structure data available"
            return g

        bullish = 0; bearish = 0

        if _is_available(close) and _is_available(prev_day_high):
            above = float(close) > float(prev_day_high)
            g["data_used"]["price_vs_prev_high"] = {"close": close, "prev_high": prev_day_high, "above": above}
            if above: bullish += 1; g["rules_triggered"].append("above_prev_day_high")
            else: g["rules_not_triggered"].append("below_prev_day_high")

        if _is_available(close) and _is_available(prev_day_low):
            above = float(close) > float(prev_day_low)
            g["data_used"]["price_vs_prev_low"] = {"close": close, "prev_low": prev_day_low, "above": above}
            if above: bullish += 1; g["rules_triggered"].append("above_prev_day_low")
            else: bearish += 1; g["rules_triggered"].append("below_prev_day_low")

        if _is_available(close) and _is_available(resistance):
            above = float(close) > float(resistance)
            g["data_used"]["price_vs_resistance"] = {"close": close, "resistance": resistance, "above": above}
            if above: bullish += 1; g["rules_triggered"].append("above_resistance")
            else: g["rules_not_triggered"].append("below_resistance")

        if _is_available(close) and _is_available(support):
            below = float(close) < float(support)
            g["data_used"]["price_vs_support"] = {"close": close, "support": support, "below": below}
            if below: bearish += 1; g["rules_triggered"].append("below_support")
            else: g["rules_not_triggered"].append("above_support")

        signal, _, _ = _classify_direction(bullish, bearish, sum([_is_available(v) for v in [close, prev_day_high, prev_day_low, support, resistance]]))

        if _is_available(close) and _is_available(support) and _is_available(resistance):
            between = float(close) >= float(support) and float(close) <= float(resistance)
            if between and bullish <= 1 and bearish == 0:
                signal = "RANGE"
                g["rules_triggered"].append("range_between_support_resistance")
        g.update({"signal": signal, "_bullish": bullish, "_bearish": bearish})
        return self._finalize(g, data_state, total)

    def _volatility_evidence(self, snapshot: dict, data_state: str) -> dict:
        g = self._base_group("volatility", data_state)
        vix = snapshot.get("vix")
        atr = snapshot.get("atr")
        high = snapshot.get("high")
        low = snapshot.get("low")
        close = snapshot.get("close")
        data_state_val = snapshot.get("data_state", data_state)

        vix_av = _is_available(vix)
        atr_av = _is_available(atr)
        range_av = _is_available(high) and _is_available(low) and _is_available(close)
        total = sum([vix_av, atr_av, range_av])

        if total == 0:
            g["reason"] = "No volatility data available"
            return g

        high_vol = 0; low_vol = 0

        if vix_av:
            vv = float(vix)
            g["data_used"]["vix"] = vv
            if vv >= self.config["volatility"]["high_vix"]: high_vol += 1; g["rules_triggered"].append("vix_high")
            elif vv <= self.config["volatility"]["normal_vix"]: low_vol += 1; g["rules_triggered"].append("vix_low")
            else: g["rules_not_triggered"].append("vix_normal")

        if atr_av and _is_available(close):
            ratio = float(atr) / float(close) * 100
            g["data_used"]["atr_ratio"] = ratio
            if ratio >= self.config["atr"]["high_ratio"]: high_vol += 1; g["rules_triggered"].append("atr_high")
            elif ratio <= self.config["atr"]["normal_ratio"]: low_vol += 1; g["rules_triggered"].append("atr_low")

        if high_vol >= 2:
            signal, strength = "HIGH_VOLATILITY", "STRONG" if high_vol >= 3 else "MODERATE"
        elif low_vol >= 2:
            signal, strength = "LOW_VOLATILITY", "MODERATE"
        else:
            signal, strength = "NORMAL", "MODERATE"

        g.update({"signal": signal, "strength": strength, "confidence": "MODERATE",
                   "_bullish": high_vol, "_bearish": low_vol})
        g["availability"] = _availability_from_state(data_state_val, total > 0)
        return g

    def _options_evidence(self, snapshot: dict, data_state: str) -> dict:
        g = self._base_group("options", data_state)
        pcr = snapshot.get("pcr")
        call_oi = snapshot.get("call_oi")
        put_oi = snapshot.get("put_oi")
        data_state_val = snapshot.get("data_state", data_state)

        pcr_av = _is_available(pcr)
        oi_av = _is_available(call_oi) and _is_available(put_oi)
        total = sum([pcr_av, oi_av])

        if total == 0:
            g.update({"reason": "No verified live option-chain data available"})
            g["availability"] = _availability_from_state(data_state_val, False)
            return g

        bullish = 0; bearish = 0

        if pcr_av:
            pv = float(pcr)
            g["data_used"]["pcr"] = pv
            if pv < 0.8: bullish += 1; g["rules_triggered"].append("pcr_bullish")
            elif pv > 1.2: bearish += 1; g["rules_triggered"].append("pcr_bearish")
            else: g["rules_not_triggered"].append("pcr_neutral")

        if oi_av:
            co = float(call_oi); po = float(put_oi)
            g["data_used"]["call_oi"] = co
            g["data_used"]["put_oi"] = po
            if co > po: bullish += 1; g["rules_triggered"].append("call_oi_dominant")
            else: bearish += 1; g["rules_triggered"].append("put_oi_dominant")

        signal, _, _ = _classify_direction(bullish, bearish, total)
        g.update({"signal": signal, "_bullish": bullish, "_bearish": bearish})
        return self._finalize(g, data_state, total)

    def _confirmation_evidence(self, snapshot: dict, data_state: str, symbol: str) -> dict:
        g = self._base_group("confirmation", data_state)
        breadth = snapshot.get("breadth")
        vix = snapshot.get("vix")
        data_state_val = snapshot.get("data_state", data_state)

        breadth_av = _is_available(breadth)
        vix_av = _is_available(vix)
        total = sum([breadth_av, vix_av])

        if total == 0:
            g["reason"] = "No confirmation data available"
            return g

        bullish = 0; bearish = 0

        if breadth_av:
            bv = float(breadth)
            g["data_used"]["breadth"] = bv
            if bv > 0: bullish += 1; g["rules_triggered"].append("breadth_positive")
            else: bearish += 1; g["rules_triggered"].append("breadth_negative")

        if vix_av:
            vv = float(vix)
            g["data_used"]["vix"] = vv
            if vv < self.config["volatility"]["normal_vix"]: bullish += 1; g["rules_triggered"].append("vix_low")
            elif vv > self.config["volatility"]["high_vix"]: bearish += 1; g["rules_triggered"].append("vix_high")

        signal, _, _ = _classify_direction(bullish, bearish, total)
        g.update({"signal": signal, "_bullish": bullish, "_bearish": bearish})
        return self._finalize(g, data_state, total)

    def _aggregate(self, groups: dict) -> dict:
        bullish = bearish = neutral = unavailable = 0
        for name, g in groups.items():
            sig = g.get("signal", "NEUTRAL")
            if sig == "BULLISH": bullish += 1
            elif sig == "BEARISH": bearish += 1
            elif sig == "UNAVAILABLE": unavailable += 1
            else: neutral += 1

        total = len(groups)
        total_dir = bullish + bearish

        if total_dir == 0 and unavailable > 0:
            overall_signal = "INSUFFICIENT_DATA"; overall_strength = "NONE"
        elif bullish > bearish and bullish > neutral:
            overall_signal = "BULLISH"; overall_strength = _strength_from_count(bullish, total)
        elif bearish > bullish and bearish > neutral:
            overall_signal = "BEARISH"; overall_strength = _strength_from_count(bearish, total)
        elif bullish == bearish and bullish > 0:
            overall_signal = "MIXED"; overall_strength = _strength_from_count(bullish, total)
        elif bullish > 0 or bearish > 0:
            overall_signal = "MIXED" if abs(bullish - bearish) <= 1 else ("BULLISH" if bullish > bearish else "BEARISH")
            overall_strength = _strength_from_count(max(bullish, bearish), total)
        else:
            overall_signal = "RANGE"; overall_strength = "MODERATE"

        return {
            "overall_signal": overall_signal, "overall_strength": overall_strength,
            "bullish_groups": bullish, "bearish_groups": bearish, "neutral_groups": neutral,
            "unavailable_groups": unavailable, "total_groups": total,
            "conflict_level": _detect_conflict_level(bullish, bearish, neutral),
        }

    def _detect_conflict(self, groups: dict) -> dict:
        signals = {}
        for name, g in groups.items():
            sig = g.get("signal", "NEUTRAL")
            if sig not in ("UNAVAILABLE", "NEUTRAL"):
                signals[name] = sig
        unique = set(signals.values())
        has_bullish = "BULLISH" in unique
        has_bearish = "BEARISH" in unique
        detected = has_bullish and has_bearish
        conflicting = [n for n, s in signals.items() if s in ("BULLISH", "BEARISH")]
        severity = "NONE"
        if detected:
            severity = "HIGH" if len(conflicting) >= 3 else "MODERATE"
        return {"detected": detected, "groups": conflicting, "severity": severity, "signals": signals}
