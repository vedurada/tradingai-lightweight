from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

sys_path = os.path.dirname(os.path.abspath(__file__))
if sys_path not in __import__("sys").path:
    __import__("sys").path.insert(0, sys_path)

from data_quality import DATA_QUALITY_LIVE, DATA_QUALITY_STALE, DATA_QUALITY_UNAVAILABLE, DATA_QUALITY_PARTIAL
from regime_utils import normalize_regime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "database", "tradingai.db")

REQUIRED_SCENARIO_FIELDS = [
    "scenario_id", "instrument", "session_date", "created_at", "scenario_type",
    "direction", "trigger", "confirmation_conditions", "invalidation",
    "expected_movement", "target_zone", "expected_horizon", "data_quality",
    "historical_sample_size", "historical_probability", "status",
    "supporting_evidence", "contradictory_evidence", "positioning_context",
    "liquidity_context", "market_intent_context",
]

SCENARIO_STATE_MACHINE = [
    "DRAFT", "ARMED", "WATCH", "PRE_TRIGGER",
    "ACTIVATED", "CONFIRMED", "INVALIDATED", "EXPIRED", "COMPLETED",
]

SCENARIO_TYPES = [
    "BULLISH_BREAKOUT", "BEARISH_BREAKDOWN",
    "BULLISH_CONTINUATION", "BEARISH_CONTINUATION",
    "BULLISH_REVERSAL", "BEARISH_REVERSAL",
    "RANGE_ROTATION", "VOLATILITY_EXPANSION", "VOLATILITY_COMPRESSION",
]

MAX_SCENARIOS_PER_INSTRUMENT = 3

SCENARIO_DIRECTION_MAP = {
    "BULLISH_BREAKOUT": "LONG",
    "BEARISH_BREAKDOWN": "SHORT",
    "BULLISH_CONTINUATION": "LONG",
    "BEARISH_CONTINUATION": "SHORT",
    "BULLISH_REVERSAL": "LONG",
    "BEARISH_REVERSAL": "SHORT",
    "RANGE_ROTATION": None,
    "VOLATILITY_EXPANSION": None,
    "VOLATILITY_COMPRESSION": None,
}

SCENARIO_HORIZON_MAP = {
    "BULLISH_BREAKOUT": "15-45 MIN",
    "BEARISH_BREAKDOWN": "15-45 MIN",
    "BULLISH_CONTINUATION": "30-90 MIN",
    "BEARISH_CONTINUATION": "30-90 MIN",
    "BULLISH_REVERSAL": "45-120 MIN",
    "BEARISH_REVERSAL": "45-120 MIN",
    "RANGE_ROTATION": "30-60 MIN",
    "VOLATILITY_EXPANSION": "15-60 MIN",
    "VOLATILITY_COMPRESSION": "60-180 MIN",
}


def _get_conn(db_path: str):
    conn = sqlite3.connect(db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


def _safe_float(v, default=None):
    if v is None:
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _safe_json(v, default=None):
    if v is None:
        return default
    if isinstance(v, (dict, list)):
        return v
    try:
        return json.loads(v)
    except (json.JSONDecodeError, TypeError):
        return default


class DataReadinessGate:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path

    def check(self, instrument: str) -> dict:
        result = {
            "instrument": instrument,
            "checked_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "sources": {},
            "overall": "PARTIAL",
            "issues": [],
        }
        conn = _get_conn(self.db_path)
        try:
            indicator_row = conn.execute(
                "SELECT * FROM indicators WHERE symbol=? ORDER BY timestamp DESC LIMIT 1",
                (instrument,),
            ).fetchone()
            if indicator_row:
                result["sources"]["indicators"] = {"available": True, "timestamp": indicator_row["timestamp"]}
            else:
                result["sources"]["indicators"] = {"available": False}
                result["issues"].append("NO_INDICATORS")

            regime_row = conn.execute(
                "SELECT * FROM market_regime WHERE symbol=? ORDER BY timestamp DESC LIMIT 1",
                (instrument,),
            ).fetchone()
            if regime_row:
                result["sources"]["market_regime"] = {"available": True, "timestamp": regime_row["timestamp"], "regime": regime_row["regime"]}
            else:
                result["sources"]["market_regime"] = {"available": False}
                result["issues"].append("NO_MARKET_REGIME")

            price_5m_row = conn.execute(
                "SELECT * FROM price_5m WHERE symbol=? ORDER BY timestamp DESC LIMIT 1",
                (instrument,),
            ).fetchone()
            if price_5m_row:
                has_volume = price_5m_row["volume"] and price_5m_row["volume"] > 0
                result["sources"]["price_5m"] = {
                    "available": True, "timestamp": price_5m_row["timestamp"],
                    "close": price_5m_row["close"], "volume": price_5m_row["volume"],
                    "has_volume": has_volume,
                }
                if not has_volume:
                    result["issues"].append("VOLUME_UNAVAILABLE")
            else:
                result["sources"]["price_5m"] = {"available": False}
                result["issues"].append("NO_PRICE_5M")

            price_1d_row = conn.execute(
                "SELECT * FROM price_1d WHERE symbol=? ORDER BY timestamp DESC LIMIT 1",
                (instrument,),
            ).fetchone()
            if price_1d_row:
                has_true_volume = price_1d_row["volume"] and price_1d_row["volume"] > 0
                result["sources"]["price_1d"] = {
                    "available": True, "timestamp": price_1d_row["timestamp"],
                    "close": price_1d_row["close"], "volume": price_1d_row["volume"],
                    "has_true_volume": has_true_volume,
                }
                if has_true_volume:
                    result["sources"]["price_1d"]["true_volume"] = price_1d_row["volume"]
            else:
                result["sources"]["price_1d"] = {"available": False}
                result["issues"].append("NO_PRICE_1D")

            option_row = conn.execute(
                "SELECT COUNT(*) as cnt FROM option_chain WHERE symbol=?",
                (instrument,),
            ).fetchone()
            if option_row and option_row["cnt"] > 0:
                result["sources"]["option_chain"] = {"available": True, "row_count": option_row["cnt"]}
            else:
                result["sources"]["option_chain"] = {"available": False, "row_count": 0}
                result["issues"].append("NO_OPTION_CHAIN")

            vix_row = conn.execute(
                "SELECT * FROM vix_data ORDER BY timestamp DESC LIMIT 1",
            ).fetchone()
            if vix_row:
                result["sources"]["vix"] = {"available": True, "timestamp": vix_row["timestamp"], "close": vix_row["close"]}
            else:
                result["sources"]["vix"] = {"available": False}
                result["issues"].append("NO_VIX_DATA")

            outcome_row = conn.execute(
                "SELECT COUNT(*) as cnt FROM research_outcome_tracking WHERE instrument=?",
                (instrument,),
            ).fetchone()
            if outcome_row and outcome_row["cnt"] > 0:
                result["sources"]["historical_outcomes"] = {"available": True, "row_count": outcome_row["cnt"]}
            else:
                result["sources"]["historical_outcomes"] = {"available": False, "row_count": 0}

            oi_row = conn.execute(
                "SELECT COUNT(*) as cnt FROM oi_top_strikes WHERE symbol=?",
                (instrument,),
            ).fetchone()
            if oi_row and oi_row["cnt"] > 0:
                result["sources"]["oi_top_strikes"] = {"available": True, "row_count": oi_row["cnt"]}
            else:
                result["sources"]["oi_top_strikes"] = {"available": False, "row_count": 0}
                result["issues"].append("NO_OI_TOP_STRIKES")

            pcr_row = conn.execute(
                "SELECT COUNT(*) as cnt FROM pcr_history WHERE symbol=?",
                (instrument,),
            ).fetchone()
            if pcr_row and pcr_row["cnt"] > 0:
                result["sources"]["pcr_history"] = {"available": True, "row_count": pcr_row["cnt"]}
            else:
                result["sources"]["pcr_history"] = {"available": False, "row_count": 0}
                result["issues"].append("NO_PCR_HISTORY")

            outlook_row = conn.execute(
                "SELECT * FROM market_outlooks WHERE symbol=? ORDER BY date DESC LIMIT 1",
                (instrument,),
            ).fetchone()
            if outlook_row:
                result["sources"]["market_outlook"] = {"available": True, "date": outlook_row["date"]}
            else:
                result["sources"]["market_outlook"] = {"available": False}

        finally:
            conn.close()

        issues = result["issues"]
        if "NO_INDICATORS" in issues or "NO_PRICE_5M" in issues:
            result["overall"] = "UNAVAILABLE"
        elif "NO_OPTION_CHAIN" in issues or "NO_OI_TOP_STRIKES" in issues or "NO_PCR_HISTORY" in issues:
            result["overall"] = "PARTIAL"
        elif "VOLUME_UNAVAILABLE" in issues:
            result["overall"] = "PARTIAL"
        else:
            result["overall"] = "LIVE"

        return result


class KeyLevelAnalyzer:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path

    def analyze(self, instrument: str, data_readiness: dict) -> dict:
        conn = _get_conn(self.db_path)
        try:
            ind = conn.execute(
                "SELECT * FROM indicators WHERE symbol=? ORDER BY timestamp DESC LIMIT 1",
                (instrument,),
            ).fetchone()
            if not ind:
                return {"available": False, "issues": ["NO_INDICATORS"]}

            ind = dict(ind)

            sr_raw = _safe_json(ind.get("support_resistance"), {})
            support_from_sr = sr_raw.get("support", []) if isinstance(sr_raw, dict) else []
            resistance_from_sr = sr_raw.get("resistance", []) if isinstance(sr_raw, dict) else []

            prev_close = _safe_float(ind.get("prev_day_close"))
            prev_high = _safe_float(ind.get("prev_day_high"))
            prev_low = _safe_float(ind.get("prev_day_low"))
            day_high = _safe_float(ind.get("day_high"))
            day_low = _safe_float(ind.get("day_low"))
            vwap = _safe_float(ind.get("vwap"))
            pivot = _safe_float(ind.get("pivot"))
            r1 = _safe_float(ind.get("r1"))
            s1 = _safe_float(ind.get("s1"))
            r2 = _safe_float(ind.get("r2"))
            s2 = _safe_float(ind.get("s2"))
            ema20 = _safe_float(ind.get("ema20"))
            ema50 = _safe_float(ind.get("ema50"))
            ema200 = _safe_float(ind.get("ema200"))
            rsi = _safe_float(ind.get("rsi"))
            adx = _safe_float(ind.get("adx"))
            atr = _safe_float(ind.get("atr"))
            cpr_class = ind.get("cpr_classification")

            price_row = data_readiness.get("sources", {}).get("price_5m", {})
            current_price = _safe_float(price_row.get("close"))

            support_levels = []
            if support_from_sr:
                support_levels.extend(support_from_sr)
            if prev_low is not None:
                support_levels.append(prev_low)
            if day_low is not None:
                support_levels.append(day_low)
            if s1 is not None:
                support_levels.append(s1)
            if s2 is not None:
                support_levels.append(s2)
            support_levels = sorted(set(support_levels), reverse=True)
            support_levels = [s for s in support_levels if s > 0]

            resistance_levels = []
            if resistance_from_sr:
                resistance_levels.extend(resistance_from_sr)
            if prev_high is not None:
                resistance_levels.append(prev_high)
            if day_high is not None:
                resistance_levels.append(day_high)
            if r1 is not None:
                resistance_levels.append(r1)
            if r2 is not None:
                resistance_levels.append(r2)
            resistance_levels = sorted(set(resistance_levels))
            resistance_levels = [r for r in resistance_levels if r > 0]

            result = {
                "available": True,
                "current_price": current_price,
                "prev_day_close": prev_close,
                "prev_day_high": prev_high,
                "prev_day_low": prev_low,
                "day_high": day_high,
                "day_low": day_low,
                "vwap": vwap,
                "pivot": pivot,
                "r1": r1, "s1": s1, "r2": r2, "s2": s2,
                "ema20": ema20, "ema50": ema50, "ema200": ema200,
                "rsi": rsi, "adx": adx, "atr": atr,
                "cpr_classification": cpr_class,
                "support_levels": support_levels[:5],
                "resistance_levels": resistance_levels[:5],
                "timestamp": ind.get("timestamp"),
            }

            if not support_levels:
                result["issues"] = ["NO_SUPPORT_LEVELS"]
            if not resistance_levels:
                result["issues"].append("NO_RESISTANCE_LEVELS")

            return result
        finally:
            conn.close()


class PreMarketScenarioEngine:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self.gate = DataReadinessGate(db_path)
        self.levels = KeyLevelAnalyzer(db_path)

    def generate_scenarios(
        self,
        instrument: str,
        session_date: str = None,
        max_scenarios: int = MAX_SCENARIOS_PER_INSTRUMENT,
    ) -> dict:
        instrument = instrument.upper()
        if session_date is None:
            session_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        data_readiness = self.gate.check(instrument)
        key_levels = self.levels.analyze(instrument, data_readiness)

        scenarios = []
        if key_levels.get("available"):
            scenario_types = self._determine_scenario_types(
                instrument, data_readiness, key_levels,
            )
            for scenario_type in scenario_types[:max_scenarios]:
                scenario = self._build_scenario(
                    scenario_type, instrument, session_date,
                    key_levels, data_readiness,
                )
                if scenario:
                    scenarios.append(scenario)

        scenarios = self._apply_max_scenarios(scenarios, instrument, max_scenarios)

        return {
            "instrument": instrument,
            "session_date": session_date,
            "data_readiness": data_readiness,
            "key_levels": key_levels,
            "scenarios": scenarios,
            "scenario_count": len(scenarios),
            "max_scenarios": max_scenarios,
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }

    def _determine_scenario_types(
        self, instrument, data_readiness, key_levels,
    ) -> list:
        regime_info = data_readiness.get("sources", {}).get("market_regime", {})
        regime_raw = regime_info.get("regime", "UNKNOWN")
        regime = normalize_regime(regime_raw)

        vwap = key_levels.get("vwap")
        current_price = key_levels.get("current_price")
        rsi = key_levels.get("rsi")
        adx = key_levels.get("adx")
        cpr_class = key_levels.get("cpr_classification")
        has_volume = data_readiness.get("sources", {}).get("price_5m", {}).get("has_volume", False)

        price_vs_vwap = "UNKNOWN"
        if vwap and current_price:
            if current_price > vwap * 1.001:
                price_vs_vwap = "ABOVE"
            elif current_price < vwap * 0.999:
                price_vs_vwap = "BELOW"
            else:
                price_vs_vwap = "NEAR"

        types = []

        if regime == "BULLISH" and price_vs_vwap == "ABOVE":
            if adx and adx > 30:
                types.append("BULLISH_BREAKOUT")
            types.append("BULLISH_CONTINUATION")
        elif regime == "BEARISH" and price_vs_vwap == "BELOW":
            if adx and adx > 30:
                types.append("BEARISH_BREAKDOWN")
            types.append("BEARISH_CONTINUATION")
        elif regime == "BEARISH" and price_vs_vwap == "ABOVE":
            types.append("BEARISH_REVERSAL")
        elif regime == "BULLISH" and price_vs_vwap == "BELOW":
            types.append("BULLISH_REVERSAL")
        elif regime == "SIDEWAYS":
            if cpr_class == "WIDE":
                types.append("VOLATILITY_EXPANSION")
            else:
                types.append("RANGE_ROTATION")
        elif regime == "HIGH_VOLATILITY":
            types.append("VOLATILITY_EXPANSION")
            types.append("BEARISH_BREAKDOWN")

        if not types:
            if price_vs_vwap == "ABOVE":
                types.append("BULLISH_CONTINUATION")
            elif price_vs_vwap == "BELOW":
                types.append("BEARISH_CONTINUATION")
            else:
                types.append("RANGE_ROTATION")

        if regime in ("BULLISH", "BEARISH") and "BREAKOUT" not in types and "BREAKDOWN" not in types:
            if current_price and key_levels.get("resistance_levels"):
                nearest_res = key_levels["resistance_levels"][0]
                if current_price < nearest_res:
                    types.append("BULLISH_BREAKOUT")
            if current_price and key_levels.get("support_levels"):
                nearest_sup = key_levels["support_levels"][0]
                if current_price > nearest_sup:
                    types.append("BEARISH_BREAKDOWN")

        if cpr_class == "NARROW" and regime != "HIGH_VOLATILITY":
            if "VOLATILITY_EXPANSION" not in types:
                types.append("VOLATILITY_EXPANSION")

        seen = set()
        unique = []
        for t in types:
            if t not in seen:
                seen.add(t)
                unique.append(t)
        return unique[:MAX_SCENARIOS_PER_INSTRUMENT]

    def _build_scenario(
        self, scenario_type: str, instrument: str, session_date: str,
        key_levels: dict, data_readiness: dict,
    ) -> dict:
        direction = SCENARIO_DIRECTION_MAP.get(scenario_type)
        horizon = SCENARIO_HORIZON_MAP.get(scenario_type, "30-90 MIN")

        trigger, confirmation, invalidation, expected_movement, target_zone = self._build_trigger_fields(
            scenario_type, key_levels, data_readiness,
        )

        supporting_evidence = self._build_evidence(scenario_type, key_levels, data_readiness, positive=True)
        contradictory_evidence = self._build_evidence(scenario_type, key_levels, data_readiness, positive=False)

        scenario = {
            "scenario_id": f"PMS-{uuid.uuid4().hex[:12].upper()}",
            "instrument": instrument,
            "session_date": session_date,
            "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "scenario_type": scenario_type,
            "direction": direction,
            "trigger": trigger,
            "confirmation_conditions": confirmation,
            "invalidation": invalidation,
            "expected_movement": expected_movement,
            "target_zone": target_zone,
            "expected_horizon": horizon,
            "data_quality": self._determine_data_quality(data_readiness, scenario_type),
            "historical_sample_size": self._get_historical_sample_size(data_readiness),
            "historical_probability": self._get_historical_probability(data_readiness, scenario_type),
            "status": "ARMED",
            "supporting_evidence": supporting_evidence,
            "contradictory_evidence": contradictory_evidence,
            "positioning_context": self._build_positioning_context(scenario_type, key_levels, data_readiness),
            "liquidity_context": self._build_liquidity_context(scenario_type, key_levels),
            "market_intent_context": self._build_market_intent_context(scenario_type, key_levels, data_readiness),
        }

        return scenario

    def _nearest_below(self, levels, price):
        if price is None:
            return levels[-1] if levels else None
        below = [l for l in levels if l < price]
        if not below:
            return levels[-1] if levels else None
        return max(below)

    def _nearest_above(self, levels, price):
        if price is None:
            return levels[0] if levels else None
        above = [l for l in levels if l > price]
        if not above:
            return levels[0] if levels else None
        return min(above)

    def _build_trigger_fields(
        self, scenario_type: str, key_levels: dict, data_readiness: dict,
    ) -> tuple:
        current_price = key_levels.get("current_price")
        support_levels = key_levels.get("support_levels", [])
        resistance_levels = key_levels.get("resistance_levels", [])
        vwap = key_levels.get("vwap")
        prev_high = key_levels.get("prev_day_high")
        prev_low = key_levels.get("prev_day_low")
        prev_close = key_levels.get("prev_day_close")
        ema20 = key_levels.get("ema20")
        ema50 = key_levels.get("ema50")
        cpr_class = key_levels.get("cpr_classification")
        has_volume = data_readiness.get("sources", {}).get("price_5m", {}).get("has_volume", True)

        atr = key_levels.get("atr")
        expected_move_pct = None
        if atr and current_price:
            expected_move_pct = round(atr / current_price * 100, 2)

        trigger = ""
        confirmation = ""
        invalidation = ""
        expected_movement = ""
        target_zone = ""

        if scenario_type == "BULLISH_BREAKOUT":
            trigger_level = self._nearest_above(resistance_levels, current_price) or (resistance_levels[0] if resistance_levels else prev_high)
            trigger = (
                f"Price closes above resistance {trigger_level:.2f}"
                if trigger_level else "Price breaks above resistance"
            )
            if not has_volume:
                confirmation = "5-min close above resistance (volume confirmation unavailable — VOLUME_UNAVAILABLE)"
            else:
                confirmation = "5-min close above resistance + volume confirmation"
            invalidation = f"Return below {vwap if vwap else (prev_close if prev_close else 'pivot')}"
            expected_movement = f"+{expected_move_pct}% to +{expected_move_pct * 1.5}%" if expected_move_pct else "1-2% upside"
            next_res = self._nearest_above(resistance_levels, trigger_level) if trigger_level else None
            target_zone = f"{next_res:.2f}" if next_res else (f"{resistance_levels[-1]:.2f}" if resistance_levels else (f"{prev_high:.2f}" if prev_high else "N/A"))

        elif scenario_type == "BEARISH_BREAKDOWN":
            trigger_level = self._nearest_below(support_levels, current_price) or (support_levels[-1] if support_levels else prev_low)
            trigger = (
                f"Price closes below support {trigger_level:.2f}"
                if trigger_level else "Price breaks below support"
            )
            if not has_volume:
                confirmation = "5-min close below support (volume confirmation unavailable — VOLUME_UNAVAILABLE)"
            else:
                confirmation = "5-min close below support + volume confirmation"
            invalidation = f"Return above {vwap if vwap else (prev_close if prev_close else 'pivot')}"
            expected_movement = f"-{expected_move_pct}% to -{expected_move_pct * 1.5}%" if expected_move_pct else "1-2% downside"
            next_sup = self._nearest_below(support_levels, trigger_level) if trigger_level else None
            target_zone = f"{next_sup:.2f}" if next_sup else (f"{support_levels[0]:.2f}" if support_levels else (f"{prev_low:.2f}" if prev_low else "N/A"))

        elif scenario_type == "BULLISH_CONTINUATION":
            trigger = (
                f"Price holds above VWAP {vwap:.2f}" if vwap else "Price holds above VWAP"
            )
            if ema20 and current_price and current_price > ema20:
                trigger += f" with price above EMA20 ({ema20:.2f})"
            confirmation = "Pullback to VWAP holds as support + follow-through above prior swing high"
            invalidation = "Daily close below VWAP with loss of momentum (RSI > 70 divergence)"
            expected_movement = f"+0.5% to +{expected_move_pct}%" if expected_move_pct else "+0.5-1.5%"
            target_zone = f"{prev_high:.2f}" if prev_high else "Prior day high"

        elif scenario_type == "BEARISH_CONTINUATION":
            trigger = (
                f"Price remains below VWAP {vwap:.2f}" if vwap else "Price remains below VWAP"
            )
            if ema20 and current_price and current_price < ema20:
                trigger += f" with price below EMA20 ({ema20:.2f})"
            confirmation = "Rebound to VWAP rejected + breakdown of recent swing low"
            invalidation = "Daily close above VWAP with momentum shift (RSI < 30 reversal)"
            expected_movement = f"-{expected_move_pct}% to -{expected_move_pct * 1.5}%" if expected_move_pct else "-0.5-1.5%"
            target_zone = f"{prev_low:.2f}" if prev_low else "Prior day low"

        elif scenario_type == "BULLISH_REVERSAL":
            trigger_level = self._nearest_below(support_levels, current_price) or (support_levels[-1] if support_levels else None)
            trigger = (
                f"Price bounces at key support {trigger_level:.2f}" if trigger_level else "Price bounces at key support"
            )
            confirmation = "Bullish candlestick pattern at support + RSI divergence (RSI < 30) + reversal candle confirmation"
            invalidation = "Break below support with close below prior day low " + (f"({prev_low:.2f})" if prev_low else "")
            expected_movement = f"+{expected_move_pct}%" if expected_move_pct else "+1-2%"
            target_zone = f"{vwap:.2f}" if vwap else "VWAP"

        elif scenario_type == "BEARISH_REVERSAL":
            trigger_level = self._nearest_above(resistance_levels, current_price) or (resistance_levels[0] if resistance_levels else None)
            trigger = (
                f"Price rejects resistance {trigger_level:.2f}" if trigger_level else "Price rejects resistance"
            )
            confirmation = "Bearish candlestick pattern at resistance + RSI divergence (RSI > 70) + reversal candle confirmation"
            invalidation = "Break above resistance with close above prior day high " + (f"({prev_high:.2f})" if prev_high else "")
            expected_movement = f"-{expected_move_pct}%" if expected_move_pct else "-1-2%"
            target_zone = f"{vwap:.2f}" if vwap else "VWAP"

        elif scenario_type == "RANGE_ROTATION":
            range_low = self._nearest_below(support_levels, current_price) or (support_levels[-1] if support_levels else None)
            range_high = self._nearest_above(resistance_levels, current_price) or (resistance_levels[0] if resistance_levels else None)
            if range_low and range_high:
                trigger = f"Price rotates within range {range_low:.2f} - {range_high:.2f}"
                target_zone = f"Mid-range {(range_low + range_high) / 2:.2f}"
            elif support_levels and resistance_levels:
                trigger = f"Price rotates within range {support_levels[-1]:.2f} - {resistance_levels[0]:.2f}"
                target_zone = f"Mid-range {(support_levels[-1] + resistance_levels[0]) / 2:.2f}"
            else:
                trigger = "Price rotates within defined range"
                target_zone = "N/A"
            confirmation = "Bounce at range low + rejection at range high with no breakout confirmation"
            invalidation = "Close outside range boundaries with momentum confirmation"
            expected_movement = "Range-bound ±0.5%"

        elif scenario_type == "VOLATILITY_EXPANSION":
            trigger = "ATR increases >20% from recent average + price breaks range boundaries"
            confirmation = "Sustained move beyond range with broadening volume (note: index volume may be unavailable)"
            invalidation = "Volatility contracts back with price returning into range"
            expected_movement = f"+/-{expected_move_pct}%" if expected_move_pct else "+/-1.5-3%"
            target_zone = "Outside current range boundaries"

        elif scenario_type == "VOLATILITY_COMPRESSION":
            trigger = "ATR decreases >15% from recent average + price squeezes toward CPR"
            confirmation = "Sustained compression with decreasing true range + breakout pending"
            invalidation = "Volatility expands with directional break from compression zone"
            expected_movement = "Breakout move 1-2% after compression release"
            if cpr_class and cpr_class != "UNKNOWN":
                target_zone = f"CPR zone ({cpr_class})"
            else:
                target_zone = "CPR zone"

        return trigger, confirmation, invalidation, expected_movement, target_zone

    def _build_evidence(
        self, scenario_type: str, key_levels: dict, data_readiness: dict, positive: bool,
    ) -> list:
        evidence = []
        regime_info = data_readiness.get("sources", {}).get("market_regime", {})
        regime = normalize_regime(regime_info.get("regime", "UNKNOWN"))
        rsi = key_levels.get("rsi")
        adx = key_levels.get("adx")
        vwap = key_levels.get("vwap")
        current_price = key_levels.get("current_price")
        cpr_class = key_levels.get("cpr_classification")
        atr = key_levels.get("atr")

        direction_is_bull = scenario_type.startswith("BULLISH")
        direction_is_bear = scenario_type.startswith("BEARISH")

        if regime_info.get("available"):
            if positive and regime == "BULLISH" and direction_is_bull:
                evidence.append(f"Regime: {regime_info.get('regime')} (bullish trend confirmed)")
            elif positive and regime == "BEARISH" and direction_is_bear:
                evidence.append(f"Regime: {regime_info.get('regime')} (bearish trend confirmed)")
            elif positive and regime == "SIDEWAYS" and scenario_type == "RANGE_ROTATION":
                evidence.append(f"Regime: {regime_info.get('regime')} (range-bound conditions)")
            elif positive and regime == "HIGH_VOLATILITY" and "VOLATILITY" in scenario_type:
                evidence.append(f"Regime: {regime_info.get('regime')} (high volatility regime)")
            elif not positive and regime != "UNKNOWN":
                evidence.append(f"Contradiction: Regime {regime_info.get('regime')} may not support {scenario_type}")

        if current_price is not None and vwap is not None:
            diff_pct = (current_price - vwap) / vwap * 100
            if positive and diff_pct > 0.1 and direction_is_bull:
                evidence.append(f"Price {current_price:.2f} above VWAP {vwap:.2f} (+{diff_pct:.2f}%)")
            elif positive and diff_pct < -0.1 and direction_is_bear:
                evidence.append(f"Price {current_price:.2f} below VWAP {vwap:.2f} ({diff_pct:.2f}%)")
            elif not positive and ((diff_pct > 0.1 and direction_is_bear) or (diff_pct < -0.1 and direction_is_bull)):
                evidence.append(f"Contradiction: Price vs VWAP direction opposes scenario")

        if rsi is not None:
            if positive and direction_is_bull and rsi < 60:
                evidence.append(f"RSI {rsi:.1f} in neutral zone with room to rise")
            elif positive and direction_is_bear and rsi > 40:
                evidence.append(f"RSI {rsi:.1f} in neutral zone with room to fall")
            elif not positive and ((direction_is_bull and rsi > 70) or (direction_is_bear and rsi < 30)):
                evidence.append(f"Contradiction: RSI {rsi:.1f} may limit {scenario_type}")

        if adx is not None:
            if positive and adx > 30:
                evidence.append(f"ADX {adx:.1f} indicates strong trend")
            elif not positive and adx < 20:
                evidence.append(f"Contradiction: ADX {adx:.1f} indicates weak trend, breakout unlikely")

        if cpr_class:
            if positive and cpr_class == "WIDE" and "EXPANSION" in scenario_type:
                evidence.append(f"CPR classification: {cpr_class} (supports volatility expansion)")

        if atr:
            if positive and "VOLATILITY" in scenario_type:
                evidence.append(f"ATR {atr:.2f} provides measurable expected movement base")

        if not evidence:
            if positive:
                evidence.append(f"Scenario type {scenario_type} consistent with current market structure")
            else:
                evidence.append(f"Counter-evidence analysis: no specific contradictions identified")

        return evidence

    def _build_positioning_context(
        self, scenario_type: str, key_levels: dict, data_readiness: dict,
    ) -> dict:
        has_volume = data_readiness.get("sources", {}).get("price_5m", {}).get("has_volume", True)
        oi_available = data_readiness.get("sources", {}).get("oi_top_strikes", {}).get("available", False)
        pcr_available = data_readiness.get("sources", {}).get("pcr_history", {}).get("available", False)
        direction = SCENARIO_DIRECTION_MAP.get(scenario_type)

        context = {
            "fear_gauge": "N/A" if data_readiness.get("sources", {}).get("vix", {}).get("available") is False else "AVAILABLE",
            "positioning_source": "OPTIONS" if (oi_available or pcr_available) else "INDICATORS_ONLY",
            "oi_context": "DATA UNAVAILABLE" if not oi_available else "AVAILABLE",
            "pcr_context": "DATA UNAVAILABLE" if not pcr_available else "AVAILABLE",
            "volume_context": "VOLUME_UNAVAILABLE" if not has_volume else "AVAILABLE",
        }

        if direction == "LONG":
            context["recommended_bias"] = "LONG BIAS with tight risk management"
            context["risk_reward_profile"] = "1:2 minimum"
        elif direction == "SHORT":
            context["recommended_bias"] = "SHORT BIAS with tight risk management"
            context["risk_reward_profile"] = "1:2 minimum"
        else:
            context["recommended_bias"] = "NEUTRAL / RANGE TRADE"
            context["risk_reward_profile"] = "1:1.5 minimum"

        if not has_volume and not oi_available:
            context["positioning_caveat"] = (
                "Positioning derived from technical indicators only; "
                "options and volume data unavailable. Reduce position size."
            )

        return context

    def _build_liquidity_context(self, scenario_type: str, key_levels: dict) -> dict:
        support_levels = key_levels.get("support_levels", [])
        resistance_levels = key_levels.get("resistance_levels", [])
        vwap = key_levels.get("vwap")

        context = {
            "primary_liquidity_zones": [],
            "stop_liquidity_clusters": [],
            "institutional_order_flow": "ESTIMATED_FROM_LEVELS",
            "gap_fills": [],
        }

        all_levels = []
        for r in resistance_levels:
            all_levels.append({"level": r, "type": "RESISTANCE", "liquidity_score": "HIGH"})
        for s in support_levels:
            all_levels.append({"level": s, "type": "SUPPORT", "liquidity_score": "HIGH"})
        if vwap:
            all_levels.append({"level": vwap, "type": "VWAP", "liquidity_score": "MEDIUM"})

        context["primary_liquidity_zones"] = all_levels[:6]

        if support_levels and resistance_levels:
            context["stop_liquidity_clusters"].append({
                "zone": f"Above {resistance_levels[0]:.2f}",
                "level": resistance_levels[0],
                "type": "STOP_HUNT_ABOVE",
            })
            context["stop_liquidity_clusters"].append({
                "zone": f"Below {support_levels[-1]:.2f}",
                "level": support_levels[-1],
                "type": "STOP_HUNT_BELOW",
            })

        prev_high = key_levels.get("prev_day_high")
        prev_low = key_levels.get("prev_day_low")
        if prev_high:
            context["gap_fills"].append({"level": prev_high, "type": "PREV_DAY_HIGH_FILL"})
        if prev_low:
            context["gap_fills"].append({"level": prev_low, "type": "PREV_DAY_LOW_FILL"})

        return context

    def _build_market_intent_context(
        self, scenario_type: str, key_levels: dict, data_readiness: dict,
    ) -> dict:
        regime_info = data_readiness.get("sources", {}).get("market_regime", {})
        outlook_available = data_readiness.get("sources", {}).get("market_outlook", {}).get("available", False)
        vix_available = data_readiness.get("sources", {}).get("vix", {}).get("available", False)
        vix_close = data_readiness.get("sources", {}).get("vix", {}).get("close")

        context = {
            "market_structure_read": f"Regime from DB: {regime_info.get('regime', 'UNKNOWN')}" if regime_info.get("available") else "No regime data",
            "institutional_bias_signal": "DERIVED_FROM_LEVELS",
            "large_player_positioning": "UNAVAILABLE" if not data_readiness.get("sources", {}).get("oi_top_strikes", {}).get("available") else "AVAILABLE",
            "volatility_regime": "N/A" if not vix_available else f"VIX {vix_close:.2f}" if vix_close else "N/A",
            "outlook_correlation": "AVAILABLE" if outlook_available else "NO_DAILY_OUTLOOK",
            "intent_summary": "",
        }

        regime = normalize_regime(regime_info.get("regime", "UNKNOWN"))
        if scenario_type.startswith("BULLISH"):
            context["intent_summary"] = (
                f"Market structure suggests {regime} conditions; "
                f"bullish scenario assumes trend continuation or reversal "
                f"from key support. Risk: {regime} reversal."
            )
        elif scenario_type.startswith("BEARISH"):
            context["intent_summary"] = (
                f"Market structure suggests {regime} conditions; "
                f"bearish scenario assumes trend continuation or reversal "
                f"from key resistance. Risk: {regime} reversal."
            )
        else:
            context["intent_summary"] = (
                f"Market structure suggests {regime} conditions; "
                f"scenario assumes range or volatility event. "
                f"Risk: directional break from current structure."
            )

        return context

    def _determine_data_quality(self, data_readiness: dict, scenario_type: str) -> str:
        issues = data_readiness.get("issues", [])
        overall = data_readiness.get("overall", "PARTIAL")

        if overall == "UNAVAILABLE":
            return DATA_QUALITY_UNAVAILABLE

        quality_parts = []
        has_volume = data_readiness.get("sources", {}).get("price_5m", {}).get("has_volume", True)
        if not has_volume:
            quality_parts.append("VOLUME_UNAVAILABLE")

        if "NO_OPTION_CHAIN" in issues or "NO_OI_TOP_STRIKES" in issues:
            quality_parts.append("OPTIONS_PARTIAL")

        if "NO_PCR_HISTORY" in issues:
            quality_parts.append("PCR_UNAVAILABLE")

        if overall == "PARTIAL":
            if quality_parts:
                return "+".join([DATA_QUALITY_PARTIAL] + quality_parts)
            return DATA_QUALITY_PARTIAL

        if quality_parts:
            return "+".join([DATA_QUALITY_LIVE] + quality_parts)

        return DATA_QUALITY_LIVE

    def _get_historical_sample_size(self, data_readiness: dict) -> int:
        outcomes = data_readiness.get("sources", {}).get("historical_outcomes", {})
        if outcomes.get("available"):
            return outcomes.get("row_count", 0)
        return 0

    def _get_historical_probability(
        self, data_readiness: dict, scenario_type: str,
    ) -> Optional[float]:
        outcomes = data_readiness.get("sources", {}).get("historical_outcomes", {})
        if not outcomes.get("available"):
            return None
        sample = outcomes.get("row_count", 0)
        if sample < 10:
            return None
        return None

    def _apply_max_scenarios(self, scenarios: list, instrument: str, max_scenarios: int) -> list:
        return scenarios[:max_scenarios]

    def validate_scenario(self, scenario: dict) -> tuple:
        missing = []
        nullable_fields = {"historical_probability"}
        for field in REQUIRED_SCENARIO_FIELDS:
            if field not in scenario:
                missing.append(field)
            elif scenario[field] is None and field not in nullable_fields:
                missing.append(field)
        is_valid = len(missing) == 0
        return is_valid, missing

    def validate_all_scenarios(self, scenarios: list) -> dict:
        results = {"total": len(scenarios), "valid": 0, "invalid": 0, "errors": []}
        for s in scenarios:
            is_valid, missing = self.validate_scenario(s)
            sid = s.get("scenario_id", "UNKNOWN")
            if is_valid:
                results["valid"] += 1
            else:
                results["invalid"] += 1
                results["errors"].append({"scenario_id": sid, "missing_fields": missing})
        return results

    def get_state_transition(self, current_state: str, next_state: str) -> dict:
        if current_state not in SCENARIO_STATE_MACHINE:
            return {"valid": False, "error": f"Invalid current state: {current_state}"}
        if next_state not in SCENARIO_STATE_MACHINE:
            return {"valid": False, "error": f"Invalid next state: {next_state}"}
        current_idx = SCENARIO_STATE_MACHINE.index(current_state)
        next_idx = SCENARIO_STATE_MACHINE.index(next_state)
        if next_idx <= current_idx:
            return {
                "valid": False,
                "error": f"Cannot transition from {current_state} to {next_state}",
                "allowed_transitions": SCENARIO_STATE_MACHINE[current_idx + 1:],
            }
        return {
            "valid": True,
            "from": current_state,
            "to": next_state,
            "from_index": current_idx,
            "to_index": next_idx,
        }

    def get_all_state_transitions(self) -> list:
        transitions = []
        for i in range(len(SCENARIO_STATE_MACHINE) - 1):
            transitions.append({
                "from": SCENARIO_STATE_MACHINE[i],
                "to": SCENARIO_STATE_MACHINE[i + 1],
            })
        return transitions


def classify_opening(instrument: str, db_path: str = DB_PATH) -> dict:
    conn = _get_conn(db_path)
    try:
        prev = conn.execute(
            "SELECT prev_day_close, prev_day_high, prev_day_low, day_open, day_high, day_low FROM indicators WHERE symbol=? ORDER BY timestamp DESC LIMIT 1",
            (instrument,),
        ).fetchone()
        if not prev:
            return {"open_type": "UNKNOWN", "gap_points": 0, "gap_percent": 0, "issues": ["NO_INDICATORS"]}
        prev = dict(prev)
        live = conn.execute(
            "SELECT close FROM price_5m WHERE symbol=? ORDER BY timestamp DESC LIMIT 1",
            (instrument,),
        ).fetchone()
        if not live:
            return {"open_type": "UNKNOWN", "gap_points": 0, "gap_percent": 0, "issues": ["NO_PRICE"]}
        current_price = live["close"]
        prev_close = _safe_float(prev.get("prev_day_close"))
        day_open = _safe_float(prev.get("day_open"))
        if not prev_close or not day_open or not current_price:
            return {"open_type": "UNKNOWN", "gap_points": 0, "gap_percent": 0, "issues": ["INCOMPLETE_DATA"]}
        gap_points = day_open - prev_close
        gap_percent = (gap_points / prev_close * 100) if prev_close else 0
        if abs(gap_percent) < 0.15:
            open_type = "FLAT_OPEN"
        elif gap_points > 0:
            open_type = "GAP_UP"
        else:
            open_type = "GAP_DOWN"
        opening_location = "UNAVAILABLE"
        if day_open > prev.get("prev_day_high", 0):
            opening_location = "ABOVE_PREV_HIGH"
        elif day_open < prev.get("prev_day_low", float("inf")):
            opening_location = "BELOW_PREV_LOW"
        elif day_open > prev.get("day_low", 0) and day_open < prev.get("day_high", float("inf")):
            opening_location = "INSIDE_PREV_RANGE"
        opening_context = {
            "prev_close": prev_close,
            "day_open": day_open,
            "current_price": current_price,
            "prev_high": prev.get("prev_day_high"),
            "prev_low": prev.get("prev_day_low"),
            "day_high": prev.get("day_high"),
            "day_low": prev.get("day_low"),
        }
        return {
            "open_type": open_type,
            "gap_points": round(gap_points, 2),
            "gap_percent": round(gap_percent, 2),
            "opening_location": opening_location,
            "opening_context": opening_context,
            "issues": [],
        }
    finally:
        conn.close()


def generate_gap_scenarios(
    instrument: str,
    session_date: str = None,
    db_path: str = DB_PATH,
) -> dict:
    opening = classify_opening(instrument, db_path)
    open_type = opening.get("open_type", "UNKNOWN")
    scenarios = generate_scenarios(instrument, session_date, MAX_SCENARIOS_PER_INSTRUMENT, db_path)
    if scenarios.get("status") != "OK":
        return scenarios
    gap_metadata = {
        "gap_points": opening.get("gap_points", 0),
        "gap_percent": opening.get("gap_percent", 0),
        "open_type": open_type,
        "opening_location": opening.get("opening_location", "UNKNOWN"),
    }
    return {
        "status": "OK",
        "instrument": instrument,
        "session_date": session_date or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "opening_classification": gap_metadata,
        "scenarios": scenarios.get("scenarios", []),
        "scenario_count": len(scenarios.get("scenarios", [])),
        "max_scenarios": MAX_SCENARIOS_PER_INSTRUMENT,
    }


def generate_scenarios(
    instrument: str,
    session_date: str = None,
    max_scenarios: int = MAX_SCENARIOS_PER_INSTRUMENT,
    db_path: str = DB_PATH,
) -> dict:
    engine = PreMarketScenarioEngine(db_path)
    return engine.generate_scenarios(instrument, session_date, max_scenarios)
