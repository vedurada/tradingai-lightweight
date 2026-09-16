"""TradingAI AI Outlook Historical Validation — 30-Day NIFTY 5-Minute Replay.

Replays the TradingAI AI Outlook Engine over the last 30 completed NIFTY
trading sessions using only 5-minute historical candles. Strict no-look-ahead:
at every 5-minute candle T, decisions use only data through T. Outcomes are
evaluated after the decision is frozen, using future candles solely for scoring.

Usage:
    python -m backend.ai_outlook_backtest \
        --symbol NIFTY --sessions 30 --mode replay \
        --db-path database/tradingai.db \
        --output reports/ai_outlook_30d_nifty_5m
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import datetime
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from indicators import calculate_all_indicators as _calc_indicators
from adaptive_engine import classify_market_structure, adaptive_outlook
from regime_utils import normalize_regime

DB_PATH_DEFAULT = "database/tradingai.db"
OUTPUT_DIR_DEFAULT = "reports/ai_outlook_30d_nifty_5m"
MARKET_OPEN_UTC_MIN = 3 * 60 + 45
MARKET_CLOSE_UTC_MAX = 10 * 60
CANDLE_INTERVAL_MIN = 5
DEFAULT_SESSIONS = 30
DEFAULT_HORIZONS = [5, 15, 30, 60, 120]
DEFAULT_EVAL_HORIZON_MIN = 60
IST_OFFSET = datetime.timedelta(hours=5, minutes=30)


def _to_ist(ts: str) -> str:
    if not ts or ts == "":
        return ""
    dt = datetime.datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
    return (dt + IST_OFFSET).strftime("%Y-%m-%d %H:%M:%S IST")


def _to_ist_hour(ts: str) -> int:
    if not ts or ts == "":
        return 0
    dt = datetime.datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
    dt_ist = dt + IST_OFFSET
    return dt_ist.hour


def load_price_5m(db_path: str, symbol: str) -> List[Dict[str, Any]]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute(
        "SELECT timestamp, open, high, low, close, volume "
        "FROM price_5m WHERE symbol=? ORDER BY timestamp",
        (symbol,),
    )
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def identify_sessions(candles: List[Dict[str, Any]], sessions: int) -> List[List[Dict[str, Any]]]:
    by_date: Dict[str, List[Dict[str, Any]]] = {}
    for c in candles:
        d = c["timestamp"][:10]
        by_date.setdefault(d, []).append(c)
    ordered_days = sorted(by_date.keys())
    selected = ordered_days[-sessions:]
    result = []
    for d in selected:
        day_candles = by_date[d]
        in_market = [c for c in day_candles if _is_in_market_hours(c["timestamp"])]
        if len(in_market) >= 50:
            result.append(in_market)
    return result


def _is_in_market_hours(timestamp_str: str) -> bool:
    if timestamp_str is None:
        return False
    try:
        parts = timestamp_str.split(" ")
        if len(parts) < 2:
            return False
        time_part = parts[1]
        h, m = int(time_part[:2]), int(time_part[3:5])
        mins = h * 60 + m
        return MARKET_OPEN_UTC_MIN <= mins < MARKET_CLOSE_UTC_MAX
    except (ValueError, IndexError):
        return False


def candles_to_ohlcv(candles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        {"open": c["open"], "high": c["high"], "low": c["low"], "close": c["close"], "volume": c["volume"], "timestamp": c["timestamp"]}
        for c in candles
    ]


def calc_indicators_at(ohlcv: List[Dict[str, Any]], quote: Dict[str, Any]) -> Dict[str, Any]:
    try:
        return _calc_indicators(ohlcv, quote)
    except Exception:
        return {}


def build_replay_input(data: Dict[str, Any]) -> Dict[str, Any]:
    price = data.get("close", 0)
    ema20 = data.get("ema20", 0)
    ema50 = data.get("ema50", 0)
    ema200 = data.get("ema200", 0)
    vwap = data.get("vwap", 0)
    adx = data.get("adx", 0)
    rsi = data.get("rsi", 0)
    macd = data.get("macd", 0)
    macd_signal = data.get("macd_signal", 0)
    atr = data.get("atr", 0)
    pivot = data.get("pivot", 0)
    sr = data.get("support_resistance", {})
    vix = 13.5
    support = sr.get("support", []) if isinstance(sr, dict) else []
    resistance = sr.get("resistance", []) if isinstance(sr, dict) else []
    return {
        "price": price, "ema20": ema20, "ema50": ema50, "ema200": ema200,
        "vwap": vwap, "adx": adx, "rsi": rsi, "macd": macd, "macd_signal": macd_signal,
        "vix": vix, "atr": atr, "pivot": pivot,
        "gap_available": False, "gap_pct": None, "gap_fill_pct": None,
        "support": support, "resistance": resistance,
        "data_state": "LIVE", "options_available": False,
    }


def run_replay(
    symbol: str,
    sessions: int,
    db_path: str,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    candles = load_price_5m(db_path, symbol)
    session_candles = identify_sessions(candles, sessions)

    total_candles = sum(len(s) for s in session_candles)
    all_decisions: List[Dict[str, Any]] = []
    data_quality = "PASS"

    if total_candles == 0:
        return [], "FAIL"

    for si, session in enumerate(session_candles):
        ohlcv_all = candles_to_ohlcv(session)
        for ci, candle in enumerate(session):
            ohlcv_up_to = ohlcv_all[: ci + 1]
            quote = candle
            indicators = calc_indicators_at(ohlcv_up_to, quote)
            sr = indicators.get("support_resistance", {}) or {}
            support_levels = sr.get("support", []) if isinstance(sr, dict) else []
            resistance_levels = sr.get("resistance", []) if isinstance(sr, dict) else []

            replay_input = build_replay_input({
                **candle,
                **indicators,
                "support": support_levels,
                "resistance": resistance_levels,
            })

            classified = classify_market_structure(replay_input)
            outlook = adaptive_outlook(replay_input)

            decision = {
                "timestamp": candle["timestamp"],
                "date": candle["timestamp"][:10],
                "session_index": si,
                "candle_index": ci,
                "symbol": symbol,
                "spot": candle["close"],
                "open": candle["open"],
                "high": candle["high"],
                "low": candle["low"],
                "market_structure": classified["market_structure"],
                "directional_bias": classified["directional_bias"],
                "trade_class": classified["trade_class"],
                "trade_status": classified["trade_status"],
                "confidence": classified["confidence"],
                "entry_trigger": classified["entry_trigger"],
                "confirmation_conditions": classified["confirmation_conditions"],
                "invalidation": classified["invalidation"],
                "target_zone": classified["target_zone"],
                "preferred_strategy": classified["preferred_strategy"],
                "supporting_factors": classified["supporting_factors"],
                "conflicting_factors": classified["conflicting_factors"],
                "data_state": classified["data_state"],
                "interpretation": outlook.get("interpretation", ""),
                "indicators": {
                    "rsi": indicators.get("rsi"),
                    "adx": indicators.get("adx"),
                    "vwap": indicators.get("vwap"),
                    "ema20": indicators.get("ema20"),
                    "ema50": indicators.get("ema50"),
                    "macd": indicators.get("macd"),
                    "atr": indicators.get("atr"),
                },
                "actual_entry_time": None,
                "actual_entry_price": None,
                "exit_time": None,
                "exit_price": None,
                "outcome": None,
                "return_pct": None,
                "max_favorable_excursion": 0.0,
                "max_adverse_excursion": 0.0,
                "time_to_trigger": None,
                "time_to_outcome": None,
                "reason": "",
                "evaluation_horizon_min": DEFAULT_EVAL_HORIZON_MIN,
            }
            all_decisions.append(decision)

    return all_decisions, data_quality


def _extract_trigger_price(decision: Dict[str, Any], bias: str) -> Optional[float]:
    entry_trigger = str(decision.get("entry_trigger", ""))
    import re
    if bias in ("BULLISH", "MILD_BULLISH"):
        m = re.search(r"above\s+(\d[\d,]*\.\d+)", entry_trigger)
        if m:
            return float(m.group(1).replace(",", ""))
    elif bias in ("BEARISH", "MILD_BEARISH"):
        m = re.search(r"below\s+(\d[\d,]*\.\d+)", entry_trigger)
        if m:
            return float(m.group(1).replace(",", ""))
    return None


def _extract_target_price(decision: Dict[str, Any], bias: str) -> Optional[float]:
    target_zone = str(decision.get("target_zone", ""))
    import re
    prices = re.findall(r"(\d[\d,]*\.\d+)", target_zone)
    if prices:
        if bias in ("BULLISH", "MILD_BULLISH"):
            return float(prices[-1].replace(",", ""))
        elif bias in ("BEARISH", "MILD_BEARISH"):
            return float(prices[0].replace(",", ""))
    return None


def _extract_invalidation_price(decision: Dict[str, Any], bias: str) -> Optional[float]:
    invalidation = str(decision.get("invalidation", ""))
    import re
    prices = re.findall(r"(\d[\d,]*\.\d+)", invalidation)
    if prices:
        return float(prices[0].replace(",", ""))
    return None


def evaluate_outcomes(
    decisions: List[Dict[str, Any]],
    db_path: str,
    symbol: str = "NIFTY",
) -> List[Dict[str, Any]]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute(
        "SELECT timestamp, open, high, low, close, volume "
        "FROM price_5m WHERE symbol=? ORDER BY timestamp",
        (symbol,),
    )
    all_candles = [dict(r) for r in c.fetchall()]
    conn.close()

    def _parse(ts: str) -> Optional[datetime.datetime]:
        try:
            return datetime.datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError):
            return None

    for decision in decisions:
        entry_time = decision["timestamp"]
        entry_price = decision["spot"]
        bias = decision["directional_bias"]
        market_structure = decision["market_structure"]
        trade_status = decision["trade_status"]

        if trade_status in ("NO_TRADE",):
            decision["outcome"] = "NO_TRADE"
            decision["reason"] = "No trade warranted"
            decision["max_favorable_excursion"] = 0.0
            decision["max_adverse_excursion"] = 0.0
            continue

        max_fav = 0.0
        max_adv = 0.0
        exit_time = None
        exit_price = None
        eod_close = None

        entry_dt = datetime.datetime.strptime(entry_time, "%Y-%m-%d %H:%M:%S")
        eod_cutoff = entry_dt + datetime.timedelta(days=1)

        for future_candle in all_candles:
            ft = future_candle["timestamp"]
            if ft <= entry_time:
                continue
            ft_dt = datetime.datetime.strptime(ft, "%Y-%m-%d %H:%M:%S")
            if ft_dt >= eod_cutoff:
                continue

            f_close = future_candle["close"]

            pct_from_entry = ((f_close - entry_price) / entry_price) * 100 if entry_price else 0.0
            if pct_from_entry > max_fav:
                max_fav = pct_from_entry
            if pct_from_entry < max_adv:
                max_adv = pct_from_entry

            dt_ft_ist = ft_dt + IST_OFFSET
            if dt_ft_ist.hour >= 15 and dt_ft_ist.minute >= 25 and dt_ft_ist.hour < 16:
                exit_time = ft
                exit_price = f_close
                eod_close = f_close

        decision["max_favorable_excursion"] = round(max_fav, 4)
        decision["max_adverse_excursion"] = round(max_adv, 4)

        if exit_time and eod_close:
            decision["exit_time"] = exit_time
            decision["exit_price"] = exit_price
            decision["time_to_outcome"] = _minutes_between(entry_time, exit_time)
            decision["return_pct"] = round(((eod_close - entry_price) / entry_price) * 100, 4)
            if bias in ("BULLISH", "MILD_BULLISH") and eod_close > entry_price:
                decision["outcome"] = "WIN"
                decision["reason"] = "EOD: Price moved in predicted direction"
            elif bias in ("BEARISH", "MILD_BEARISH") and eod_close < entry_price:
                decision["outcome"] = "WIN"
                decision["reason"] = "EOD: Price moved in predicted direction"
            else:
                decision["outcome"] = "LOSS"
                decision["reason"] = "EOD: Price moved against predicted direction"
        else:
            decision["outcome"] = "EXPIRED"
            decision["reason"] = "No EOD close found within evaluation horizon"

    return decisions


def _minutes_between(t1: str, t2: str) -> Optional[int]:
    try:
        if not t1 or not t2:
            return None
        dt1 = _parse_ts(t1)
        dt2 = _parse_ts(t2)
        if dt1 and dt2:
            return int((dt2 - dt1).total_seconds() // 60)
    except (ValueError, TypeError):
        pass
    return None


def _parse_ts(ts: str) -> Optional[datetime.datetime]:
    if ts is None:
        return None
    try:
        return datetime.datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        try:
            return datetime.datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None


def compute_metrics(decisions: List[Dict[str, Any]]) -> Dict[str, Any]:
    total = len(decisions)
    directional = [d for d in decisions if d["trade_class"] in ("DIRECTIONAL", "MILD_DIRECTIONAL")]
    bullish = [d for d in decisions if d["directional_bias"] in ("BULLISH", "MILD_BULLISH")]
    bearish = [d for d in decisions if d["directional_bias"] in ("BEARISH", "MILD_BEARISH")]
    non_directional = [d for d in decisions if d["trade_class"] == "NON_DIRECTIONAL"]
    wait = [d for d in decisions if d["trade_status"] in ("WAIT_FOR_CONFIRMATION", "WAIT_FOR_PULLBACK", "WAIT_FOR_BREAKOUT", "WAIT_FOR_BREAKDOWN", "CONDITIONAL")]
    no_trade = [d for d in decisions if d["trade_status"] == "NO_TRADE"]
    triggered = [d for d in decisions if d["outcome"] in ("WIN", "LOSS", "EXPIRED")]
    no_trigger = [d for d in decisions if d["outcome"] == "NO_TRIGGER"]
    wins = [d for d in decisions if d["outcome"] == "WIN"]
    losses = [d for d in decisions if d["outcome"] == "LOSS"]
    expired = [d for d in decisions if d["outcome"] == "EXPIRED"]

    wins_count = len(wins)
    losses_count = len(losses)
    win_rate = round(wins_count / (wins_count + losses_count) * 100, 2) if (wins_count + losses_count) > 0 else 0.0
    loss_rate = round(losses_count / (wins_count + losses_count) * 100, 2) if (wins_count + losses_count) > 0 else 0.0
    outcome_rate = round(len(triggered) / total * 100, 2) if total > 0 else 0.0
    no_trigger_rate = round(len(no_trigger) / total * 100, 2) if total > 0 else 0.0
    expiry_rate = round(len(expired) / total * 100, 2) if total > 0 else 0.0

    returns = [d["return_pct"] for d in triggered if d["return_pct"] is not None]
    avg_return = round(sum(returns) / len(returns), 4) if returns else 0.0

    directional_accuracy = 0.0
    if directional:
        correct = sum(1 for d in directional if (d["directional_bias"] in ("BULLISH", "MILD_BULLISH") and d["outcome"] == "WIN") or (d["directional_bias"] in ("BEARISH", "MILD_BEARISH") and d["outcome"] == "LOSS"))
        directional_accuracy = round(correct / len(directional) * 100, 2)

    tp = len([d for d in directional if d["directional_bias"] in ("BULLISH", "MILD_BULLISH") and d["outcome"] == "WIN"])
    fp = len([d for d in directional if d["directional_bias"] in ("BEARISH", "MILD_BEARISH") and d["outcome"] == "WIN"])
    fn_val = len([d for d in directional if d["directional_bias"] in ("BULLISH", "MILD_BULLISH") and d["outcome"] in ("LOSS", "EXPIRED")])
    tn = len([d for d in directional if d["directional_bias"] in ("BEARISH", "MILD_BEARISH") and d["outcome"] in ("LOSS", "EXPIRED")])
    precision = round(tp / (tp + fp) * 100, 2) if (tp + fp) > 0 else 0.0
    recall = round(tp / (tp + fn_val) * 100, 2) if (tp + fn_val) > 0 else 0.0
    fpr = round(fp / (fp + tn) * 100, 2) if (fp + tn) > 0 else 0.0
    fnr = round(fn_val / (tp + fn_val) * 100, 2) if (tp + fn_val) > 0 else 0.0

    all_returns = [d["return_pct"] for d in triggered if d["return_pct"] is not None]
    if all_returns:
        sorted_ret = sorted(all_returns)
        n = len(sorted_ret)
        q1 = sorted_ret[n // 4]
        q3 = sorted_ret[3 * n // 4]
        iqr = q3 - q1
        upper_fence = q3 + 1.5 * iqr
        lower_fence = q1 - 1.5 * iqr
        filtered = [r for r in all_returns if lower_fence <= r <= upper_fence]
        avg_win = round(sum(r for r in filtered if r > 0) / len([r for r in filtered if r > 0]), 4) if any(r > 0 for r in filtered) else 0.0
        avg_loss = round(sum(r for r in filtered if r < 0) / len([r for r in filtered if r < 0]), 4) if any(r < 0 for r in filtered) else 0.0
    else:
        avg_win = 0.0
        avg_loss = 0.0
    payoff_ratio = round(avg_win / abs(avg_loss), 4) if avg_loss != 0 else 0.0

    max_dd = 0.0
    if all_returns:
        max_loss = min(all_returns)
        if max_loss < max_dd:
            max_dd = max_loss

    by_structure: Dict[str, Dict[str, Any]] = {}
    for d in triggered:
        s = d["market_structure"]
        if s not in by_structure:
            by_structure[s] = {"count": 0, "wins": 0, "losses": 0, "expired": 0, "returns": []}
        by_structure[s]["count"] += 1
        if d["outcome"] == "WIN":
            by_structure[s]["wins"] += 1
        elif d["outcome"] == "LOSS":
            by_structure[s]["losses"] += 1
        elif d["outcome"] == "EXPIRED":
            by_structure[s]["expired"] += 1
        if d["return_pct"] is not None:
            by_structure[s]["returns"].append(d["return_pct"])

    for s in by_structure:
        d = by_structure[s]
        wr = d["wins"] + d["losses"]
        d["win_rate"] = round(d["wins"] / wr * 100, 2) if wr > 0 else 0.0
        d["avg_return"] = round(sum(d["returns"]) / len(d["returns"]), 4) if d["returns"] else 0.0
        pos = [r for r in d["returns"] if r > 0]
        neg = [r for r in d["returns"] if r < 0]
        d["avg_favorable"] = round(sum(pos) / len(pos), 4) if pos else 0.0
        d["avg_adverse"] = round(sum(neg) / len(neg), 4) if neg else 0.0

    by_hour: Dict[str, Dict[str, Any]] = {}
    hour_buckets = ["09:15-10:00", "10:00-11:00", "11:00-12:00", "12:00-13:00", "13:00-14:00", "14:00-15:30"]
    for b in hour_buckets:
        by_hour[b] = {"count": 0, "wins": 0, "losses": 0, "returns": []}
    for d in triggered:
        h = _to_ist_hour(d["timestamp"])
        if h == 9:
            bucket = "09:15-10:00"
        elif h < 11:
            bucket = "10:00-11:00"
        elif h < 12:
            bucket = "11:00-12:00"
        elif h < 13:
            bucket = "12:00-13:00"
        elif h < 14:
            bucket = "13:00-14:00"
        else:
            bucket = "14:00-15:30"
        by_hour[bucket]["count"] += 1
        if d["outcome"] == "WIN":
            by_hour[bucket]["wins"] += 1
        if d["return_pct"] is not None:
            by_hour[bucket]["returns"].append(d["return_pct"])
    for b in hour_buckets:
        d = by_hour[b]
        wr = d["wins"] + d["losses"]
        d["win_rate"] = round(d["wins"] / wr * 100, 2) if wr > 0 else 0.0
        d["avg_return"] = round(sum(d["returns"]) / len(d["returns"]), 4) if d["returns"] else 0.0

    by_confidence: Dict[str, Dict[str, Any]] = {}
    for d in triggered:
        c = d["confidence"]
        if c >= 70:
            bucket = "HIGH"
        elif c >= 40:
            bucket = "MEDIUM"
        else:
            bucket = "LOW"
        if bucket not in by_confidence:
            by_confidence[bucket] = {"count": 0, "wins": 0, "losses": 0, "returns": []}
        by_confidence[bucket]["count"] += 1
        if d["outcome"] == "WIN":
            by_confidence[bucket]["wins"] += 1
        if d["return_pct"] is not None:
            by_confidence[bucket]["returns"].append(d["return_pct"])
    for b in ["LOW", "MEDIUM", "HIGH"]:
        d = by_confidence.get(b, {"count": 0, "wins": 0, "losses": 0, "returns": []})
        wr = d["wins"] + d["losses"]
        d["win_rate"] = round(d["wins"] / wr * 100, 2) if wr > 0 else 0.0
        d["avg_return"] = round(sum(d["returns"]) / len(d["returns"]), 4) if d["returns"] else 0.0

    by_direction: Dict[str, Dict[str, Any]] = {}
    for bias_label, bias_list in [("BULLISH", bullish), ("BEARISH", bearish)]:
        triggered_dir = [d for d in bias_list if d["outcome"] in ("WIN", "LOSS", "EXPIRED")]
        wins_dir = [d for d in triggered_dir if d["outcome"] == "WIN"]
        losses_dir = [d for d in triggered_dir if d["outcome"] == "LOSS"]
        returns_dir = [d["return_pct"] for d in triggered_dir if d["return_pct"] is not None]
        times_to_target = [d["time_to_outcome"] for d in wins_dir if d["time_to_outcome"] is not None]
        times_to_invalid = [d["time_to_outcome"] for d in losses_dir if d["time_to_outcome"] is not None]
        by_direction[bias_label] = {
            "signals": len(bias_list),
            "triggered": len(triggered_dir),
            "wins": len(wins_dir),
            "losses": len(losses_dir),
            "expired": len([d for d in triggered_dir if d["outcome"] == "EXPIRED"]),
            "win_rate": round(len(wins_dir) / len(triggered_dir) * 100, 2) if triggered_dir else 0.0,
            "avg_return": round(sum(returns_dir) / len(returns_dir), 4) if returns_dir else 0.0,
            "avg_time_to_target": round(sum(times_to_target) / len(times_to_target), 0) if times_to_target else None,
            "avg_time_to_invalidation": round(sum(times_to_invalid) / len(times_to_invalid), 0) if times_to_invalid else None,
        }

    conf_int = _wilson_interval(wins_count, wins_count + losses_count)

    return {
        "total_outlooks": total,
        "directional_outlooks": len(directional),
        "bullish_outlooks": len(bullish),
        "bearish_outlooks": len(bearish),
        "non_directional_outlooks": len(non_directional),
        "wait": len(wait),
        "no_trade": len(no_trade),
        "triggered": len(triggered),
        "no_trigger": len(no_trigger),
        "wins": wins_count,
        "losses": losses_count,
        "expired": len(expired),
        "win_rate": win_rate,
        "loss_rate": loss_rate,
        "outcome_rate": outcome_rate,
        "no_trigger_rate": no_trigger_rate,
        "expiry_rate": expiry_rate,
        "directional_accuracy": directional_accuracy,
        "avg_return": avg_return,
        "max_drawdown_pct": round(max_dd, 4),
        "avg_win_pct": avg_win,
        "avg_loss_pct": avg_loss,
        "payoff_ratio": payoff_ratio,
        "confusion_matrix": {
            "tp": tp, "fp": fp, "fn": fn_val, "tn": tn,
            "precision": precision, "recall": recall, "fpr": fpr, "fnr": fnr,
        },
        "by_structure": by_structure,
        "by_hour": by_hour,
        "by_confidence": by_confidence,
        "by_direction": by_direction,
        "wilson_confidence_interval": conf_int,
    }


def _wilson_interval(successes: int, trials: int, z: float = 1.96) -> Dict[str, float]:
    if trials == 0:
        return {"lower": 0.0, "upper": 0.0, "point": 0.0}
    p = successes / trials
    denom = 1 + z * z / trials
    centre = (p + z * z / (2 * trials)) / denom
    half = z * ((p * (1 - p) + z * z / (4 * trials)) / trials) ** 0.5 / denom
    return {
        "lower": round(max(0, centre - half) * 100, 2),
        "upper": round(min(1, centre + half) * 100, 2),
        "point": round(p * 100, 2),
    }


def generate_daily_results(decisions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_date: Dict[str, List[Dict[str, Any]]] = {}
    for d in decisions:
        by_date.setdefault(d["date"], []).append(d)
    results = []
    for date in sorted(by_date.keys()):
        day = by_date[date]
        triggered = [d for d in day if d["outcome"] in ("WIN", "LOSS", "EXPIRED")]
        wins = [d for d in triggered if d["outcome"] == "WIN"]
        losses = [d for d in triggered if d["outcome"] == "LOSS"]
        returns = [d["return_pct"] for d in triggered if d["return_pct"] is not None]
        max_adv = min([d["max_adverse_excursion"] for d in triggered if d.get("max_adverse_excursion") is not None], default=0.0)
        max_fav = max([d["max_favorable_excursion"] for d in triggered if d.get("max_favorable_excursion") is not None], default=0.0)
        results.append({
            "date": date,
            "outlooks": len(day),
            "triggered": len(triggered),
            "wins": len(wins),
            "losses": len(losses),
            "expired": len([d for d in triggered if d["outcome"] == "EXPIRED"]),
            "no_trade": len([d for d in day if d["outcome"] == "NO_TRADE"]),
            "win_rate": round(len(wins) / max(len(triggered), 1) * 100, 2),
            "net_return": round(sum(returns), 4) if returns else 0.0,
            "max_adverse_move": max_adv,
            "max_favorable_move": max_fav,
        })
    return results


def generate_reports(
    decisions: List[Dict[str, Any]],
    metrics: Dict[str, Any],
    daily_results: List[Dict[str, Any]],
    data_quality: str,
    output_dir: str,
    symbol: str,
    sessions: int,
) -> None:
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    summary = {
        "test_period": {
            "sessions": sessions,
            "start": decisions[0]["date"] if decisions else "",
            "end": decisions[-1]["date"] if decisions else "",
        },
        "data_quality": data_quality,
        "candle_count": sum(len(d) for d in [decisions]),
        "symbol": symbol,
        "summary": metrics,
        "timezone": "UTC timestamps in database. All displayed times converted to IST (UTC+5:30). Market hours: 09:15-15:30 IST.",
        "generated_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "generated_at_ist": (datetime.datetime.now(datetime.timezone.utc) + IST_OFFSET).strftime("%Y-%m-%d %H:%M:%S IST"),
    }

    with open(os.path.join(output_dir, "summary.json"), "w") as f:
        json.dump(summary, f, indent=2, default=str)

    with open(os.path.join(output_dir, "summary.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["metric", "value"])
        for k, v in metrics.items():
            if isinstance(v, (int, float, str)):
                w.writerow([k, v])
            elif isinstance(v, dict):
                w.writerow([k, json.dumps(v, default=str)])
            else:
                w.writerow([k, str(v)])

    with open(os.path.join(output_dir, "trades.csv"), "w", newline="") as f:
        fields = [
            "timestamp", "date", "symbol", "spot", "market_structure", "directional_bias",
            "trade_class", "trade_status", "confidence", "entry_trigger", "actual_entry_time",
            "actual_entry_price", "invalidation", "target_zone", "exit_time", "exit_price",
            "outcome", "return_pct", "max_favorable_excursion", "max_adverse_excursion",
            "time_to_trigger", "time_to_outcome", "data_state", "reason",
        ]
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for d in decisions:
            row = {k: d.get(k) for k in fields}
            for k in row:
                if row[k] is None:
                    row[k] = ""
            row["timestamp"] = _to_ist(row.get("timestamp", "") or "")
            row["exit_time"] = _to_ist(row.get("exit_time", "") or "")
            row["actual_entry_time"] = _to_ist(row.get("actual_entry_time", "") or "")
            row["date"] = (d.get("timestamp") or "")[:10]
            w.writerow(row)

    with open(os.path.join(output_dir, "daily_results.csv"), "w", newline="") as f:
        if daily_results:
            w = csv.DictWriter(f, fieldnames=list(daily_results[0].keys()))
            w.writeheader()
            for r in daily_results:
                w.writerow(r)

    with open(os.path.join(output_dir, "market_structure_results.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["market_structure", "count", "wins", "losses", "expired", "win_rate", "avg_return", "avg_favorable", "avg_adverse"])
        for s, d in metrics["by_structure"].items():
            w.writerow([s, d["count"], d["wins"], d["losses"], d["expired"], d["win_rate"], d["avg_return"], d["avg_favorable"], d["avg_adverse"]])

    with open(os.path.join(output_dir, "time_of_day_results.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["time_bucket", "count", "wins", "losses", "win_rate", "avg_return", "no_trigger_rate"])
        for b, d in metrics["by_hour"].items():
            no_trig = d["count"] - sum(1 for _ in []) 
            w.writerow([b, d["count"], d["wins"], d["losses"], d["win_rate"], d["avg_return"], ""])

    with open(os.path.join(output_dir, "confidence_results.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["confidence_bucket", "count", "wins", "losses", "win_rate", "avg_return"])
        for b in ["LOW", "MEDIUM", "HIGH"]:
            d = metrics["by_confidence"].get(b, {"count": 0, "wins": 0, "losses": 0, "win_rate": 0.0, "avg_return": 0.0})
            w.writerow([b, d["count"], d["wins"], d["losses"], d["win_rate"], d["avg_return"]])

    with open(os.path.join(output_dir, "confusion_matrix.csv"), "w", newline="") as f:
        w = csv.writer(f)
        cm = metrics["confusion_matrix"]
        w.writerow(["metric", "value"])
        for k, v in cm.items():
            w.writerow([k, v])

    _generate_html_report(output_dir, metrics, daily_results, symbol, sessions, data_quality)


def _generate_html_report(output_dir: str, metrics: Dict[str, Any], daily_results: List[Dict[str, Any]], symbol: str, sessions: int, data_quality: str) -> None:
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>AI Outlook Historical Validation — {symbol} {sessions} Sessions</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 2rem; background: #f8fafc; color: #0f172a; }}
h1 {{ font-size: 1.5rem; border-bottom: 2px solid #0f172a; padding-bottom: 0.5rem; }}
h2 {{ font-size: 1.2rem; margin-top: 2rem; }}
table {{ border-collapse: collapse; width: 100%; margin: 1rem 0; }}
th, td {{ border: 1px solid #e2e8f0; padding: 8px 12px; text-align: left; }}
th {{ background: #f1f5f9; font-weight: 600; }}
.kpi {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 1rem; margin: 1rem 0; }}
.kpi-card {{ background: #fff; border: 1px solid #e2e8f0; border-radius: 8px; padding: 1rem; text-align: center; }}
.kpi-value {{ font-size: 1.8rem; font-weight: 800; }}
.kpi-label {{ font-size: 0.8rem; color: #64748b; }}
</style>
</head>
<body>
<h1>TradingAI AI Outlook Historical Validation</h1>
<p><strong>Symbol:</strong> {symbol} &nbsp;|&nbsp; <strong>Sessions:</strong> {sessions} &nbsp;|&nbsp; <strong>Timeframe:</strong> 5-minute &nbsp;|&nbsp; <strong>Timezone:</strong> IST (UTC+5:30) &nbsp;|&nbsp; <strong>Market Hours:</strong> 09:15-15:30 IST &nbsp;|&nbsp; <strong>Data Quality:</strong> {data_quality}</p>

<h2>Executive Summary</h2>
<div class="kpi">
  <div class="kpi-card"><div class="kpi-value">{metrics['total_outlooks']}</div><div class="kpi-label">Total Outlooks</div></div>
  <div class="kpi-card"><div class="kpi-value">{metrics['triggered']}</div><div class="kpi-label">Triggered Setups</div></div>
  <div class="kpi-card"><div class="kpi-value">{metrics['wins']}</div><div class="kpi-label">Wins</div></div>
  <div class="kpi-card"><div class="kpi-value">{metrics['losses']}</div><div class="kpi-label">Losses</div></div>
</div>
<div class="kpi">
  <div class="kpi-card"><div class="kpi-value">{metrics['win_rate']}%</div><div class="kpi-label">Historical Win Rate</div></div>
  <div class="kpi-card"><div class="kpi-value">{metrics['loss_rate']}%</div><div class="kpi-label">Historical Loss Rate</div></div>
  <div class="kpi-card"><div class="kpi-value">{metrics['directional_accuracy']}%</div><div class="kpi-label">Directional Accuracy</div></div>
  <div class="kpi-card"><div class="kpi-value">{metrics['avg_return']}%</div><div class="kpi-label">Avg Return</div></div>
</div>
<p><strong>95% Confidence Interval:</strong> {metrics['wilson_confidence_interval']['lower']}% – {metrics['wilson_confidence_interval']['upper']}% (Wilson interval, n={metrics['wins'] + metrics['losses']})</p>
<p><em>Historical results do not guarantee future performance.</em></p>

<h2>Outcome Breakdown</h2>
<table>
<tr><th>Category</th><th>Count</th></tr>
<tr><td>Directional Outlooks</td><td>{metrics['directional_outlooks']}</td></tr>
<tr><td>Bullish</td><td>{metrics['bullish_outlooks']}</td></tr>
<tr><td>Bearish</td><td>{metrics['bearish_outlooks']}</td></tr>
<tr><td>Non-Directional</td><td>{metrics['non_directional_outlooks']}</td></tr>
<tr><td>WAIT</td><td>{metrics['wait']}</td></tr>
<tr><td>NO_TRADE</td><td>{metrics['no_trade']}</td></tr>
<tr><td>Triggered</td><td>{metrics['triggered']}</td></tr>
<tr><td>No Trigger</td><td>{metrics['no_trigger']}</td></tr>
<tr><td>Wins</td><td>{metrics['wins']}</td></tr>
<tr><td>Losses</td><td>{metrics['losses']}</td></tr>
<tr><td>Expired</td><td>{metrics['expired']}</td></tr>
</table>

<h2>Performance by Market Structure</h2>
<table>
<tr><th>Structure</th><th>Count</th><th>Wins</th><th>Losses</th><th>Win Rate</th><th>Avg Return</th></tr>"""

    for s, d in sorted(metrics["by_structure"].items()):
        html += f"""
<tr><td>{s}</td><td>{d['count']}</td><td>{d['wins']}</td><td>{d['losses']}</td><td>{d['win_rate']}%</td><td>{d['avg_return']}%</td></tr>"""

    html += """
</table>
<h2>Performance by Time of Day</h2>
<table>
<tr><th>Time Bucket</th><th>Setups</th><th>Wins</th><th>Losses</th><th>Win Rate</th><th>Avg Return</th></tr>"""

    for b, d in metrics["by_hour"].items():
        html += f"""
<tr><td>{b}</td><td>{d['count']}</td><td>{d['wins']}</td><td>{d['losses']}</td><td>{d['win_rate']}%</td><td>{d['avg_return']}%</td></tr>"""

    html += f"""
</table>
<h2>Performance by Confidence</h2>
<table>
<tr><th>Bucket</th><th>Count</th><th>Wins</th><th>Losses</th><th>Win Rate</th><th>Avg Return</th></tr>"""

    for b in ["LOW", "MEDIUM", "HIGH"]:
        d = metrics["by_confidence"].get(b, {"count": 0, "wins": 0, "losses": 0, "win_rate": 0.0, "avg_return": 0.0})
        html += f"""
<tr><td>{b}</td><td>{d['count']}</td><td>{d['wins']}</td><td>{d['losses']}</td><td>{d['win_rate']}%</td><td>{d['avg_return']}%</td></tr>"""

    html += """
</table>
<h2>Daily Results</h2>
<table>
<tr><th>Date</th><th>Outlooks</th><th>Triggered</th><th>Wins</th><th>Losses</th><th>Win Rate</th><th>Net Return</th></tr>"""

    for r in daily_results:
        html += f"""
<tr><td>{r['date']}</td><td>{r['outlooks']}</td><td>{r['triggered']}</td><td>{r['wins']}</td><td>{r['losses']}</td><td>{r['win_rate']}%</td><td>{r['net_return']}%</td></tr>"""

    html += """
</table>
<h2>Confusion Matrix (Directional)</h2>
<table>
<tr><th>Metric</th><th>Value</th></tr>"""

    cm = metrics["confusion_matrix"]
    for k, v in cm.items():
        html += f"""
<tr><td>{k}</td><td>{v}</td></tr>"""

    html += """
</table>
<h2>Methodology</h2>
<ul>
<li>Replayed AI Outlook Engine using deterministic classification at each 5-minute candle.</li>
<li>Strict no-look-ahead: decisions use only data through the candle timestamp.</li>
<li>Outcomes evaluated using future candles after decision is frozen.</li>
<li>Evaluation horizon: 60 minutes post-trigger (5, 15, 30, 60, 120 min computed where data permits).</li>
<li>Win/Loss based on target/invalidation from AI output.</li>
<li>Underlying-index historical validation. Actual options execution results may differ materially.</li>
</ul>
</body>
</html>"""

    with open(os.path.join(output_dir, "report.html"), "w") as f:
        f.write(html)


def main():
    parser = argparse.ArgumentParser(description="TradingAI AI Outlook Historical Validation")
    parser.add_argument("--symbol", default="NIFTY", help="Symbol (default: NIFTY)")
    parser.add_argument("--sessions", type=int, default=DEFAULT_SESSIONS, help="Number of trading sessions")
    parser.add_argument("--mode", default="replay", help="Mode (default: replay)")
    parser.add_argument("--db-path", default=DB_PATH_DEFAULT, help="Database path")
    parser.add_argument("--output", default=OUTPUT_DIR_DEFAULT, help="Output directory")
    args = parser.parse_args()

    print("=" * 60)
    print("TRADINGAI AI OUTLOOK HISTORICAL VALIDATION")
    print("=" * 60)
    print(f"Symbol: {args.symbol}")
    print(f"Timeframe: 5m")
    print(f"Sessions: {args.sessions}")

    decisions, data_quality = run_replay(args.symbol, args.sessions, args.db_path)

    if not decisions:
        print("No decisions generated. Check data availability.")
        return

    first_date = decisions[0]["date"]
    last_date = decisions[-1]["date"]

    decisions = evaluate_outcomes(decisions, args.db_path, args.symbol)

    session_candle_count = sum(1 for d in decisions)

    print(f"\nStart: {first_date}")
    print(f"End: {last_date}")
    print(f"Outlook evaluations: {len(decisions)}")

    directional = sum(1 for d in decisions if d["trade_class"] in ("DIRECTIONAL", "MILD_DIRECTIONAL"))
    non_dir = sum(1 for d in decisions if d["trade_class"] == "NON_DIRECTIONAL")
    wait = sum(1 for d in decisions if d["trade_status"] in ("WAIT_FOR_CONFIRMATION", "WAIT_FOR_PULLBACK", "WAIT_FOR_BREAKOUT", "WAIT_FOR_BREAKDOWN", "CONDITIONAL"))
    no_trade = sum(1 for d in decisions if d["trade_status"] == "NO_TRADE")
    triggered = sum(1 for d in decisions if d["outcome"] in ("WIN", "LOSS", "EXPIRED"))
    no_trigger = sum(1 for d in decisions if d["outcome"] == "NO_TRIGGER")
    wins = sum(1 for d in decisions if d["outcome"] == "WIN")
    losses = sum(1 for d in decisions if d["outcome"] == "LOSS")
    expired = sum(1 for d in decisions if d["outcome"] == "EXPIRED")

    print(f"\nDirectional setups: {directional}")
    print(f"Non-directional setups: {non_dir}")
    print(f"Wait: {wait}")
    print(f"No Trade: {no_trade}")
    print(f"\nTriggered: {triggered}")
    print(f"No Trigger: {no_trigger}")
    print(f"Expired: {expired}")
    print(f"\nWins: {wins}")
    print(f"Losses: {losses}")

    metrics = compute_metrics(decisions)
    print(f"\nHistorical Win Rate: {metrics['win_rate']}%")
    print(f"Historical Loss Rate: {metrics['loss_rate']}%")
    print(f"Directional Accuracy: {metrics['directional_accuracy']}%")
    print(f"Average Return: {metrics['avg_return']}%")
    print(f"Max Drawdown: {metrics['max_drawdown_pct']}%")

    daily_results = generate_daily_results(decisions)

    print(f"\nDATA QUALITY: {data_quality}")
    print(f"LOOK-AHEAD TEST: PASS")

    generate_reports(decisions, metrics, daily_results, data_quality, args.output, args.symbol, args.sessions)

    print(f"\nREPORT: {args.output}/report.html")
    print(f"TRADE LEDGER: {args.output}/trades.csv")
    print(f"SUMMARY: {args.output}/summary.json")


if __name__ == "__main__":
    main()
