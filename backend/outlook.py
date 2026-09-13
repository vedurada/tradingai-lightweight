from __future__ import annotations

"""Intraday Market Outlook generator (framework v1, 2026-09-11).

Builds a structured, data-driven market outlook from the SQLite database using
only stored values (indicators, regime, VIX, PCR/OI, price gaps, P&L history).
Persists the record to `market_outlooks` and writes a dated static page
`market/outlook-<date>.html`.

Usage: python3 outlook.py [--date 2026-09-11] [--symbol NIFTY] [--webroot /var/www/tradingai.in/html]
"""

import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from daily_page import _foot, _head, _nav

IST = ZoneInfo("Asia/Kolkata")
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "database", "tradingai.db")
SYMBOL = "NIFTY"
INDEX_SYMS = ["NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX"]

REGIME_MAP = {
    "TRENDING_BEARISH": "BEARISH",
    "BEARISH": "BEARISH",
    "TRENDING_BULLISH": "BULLISH",
    "BULLISH": "BULLISH",
    "RANGE_BOUND": "NEUTRAL / RANGE",
    "RANGE": "NEUTRAL / RANGE",
    "HIGH_VOLATILITY": "EVENT / ABNORMAL VOLATILITY",
    "BULLISH_RANGE": "BULLISH RANGE",
    "BEARISH_RANGE": "BEARISH RANGE",
}


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _num(v, dec: int = 2) -> float:
    try:
        return round(float(v), dec)
    except Exception:
        return None


def _parse_json(v, default=None):
    try:
        return json.loads(v)
    except Exception:
        return default


def _gap(day: dict, prev_close, vix: dict | None = None) -> dict:
    o, h, l, c = day.get("open"), day.get("high"), day.get("low"), day.get("close")
    if not all(v is not None for v in (o, h, l, c, prev_close)) or prev_close == 0:
        return {"available": False}
    gap_pts = o - prev_close
    gap_pct = round(gap_pts / prev_close * 100, 2)
    kind = "GAP UP" if gap_pts > prev_close * 0.0015 else "GAP DOWN" if gap_pts < -prev_close * 0.0015 else "FLAT OPEN"
    if kind == "GAP UP":
        full = o - prev_close
        travelled = max(0.0, l - o)
        fill_pct = round(min(100.0, travelled / full * 100.0), 1) if full > 0 else 0.0
        unfilled = max(0.0, prev_close - l)
    elif kind == "GAP DOWN":
        full = prev_close - o
        travelled = max(0.0, h - o)
        fill_pct = round(min(100.0, travelled / full * 100.0), 1) if full > 0 else 0.0
        unfilled = max(0.0, h - prev_close)
    else:
        fill_pct, unfilled = 0.0, 0.0
    # VIX-based gap cover prediction: not every gap fills
    vix_close = (vix or {}).get("close") if vix else None
    cover_prob = None
    if vix_close is not None:
        try:
            v = float(vix_close)
            if kind == "GAP DOWN":
                if v < 14 and abs(gap_pct) < 1.0:
                    cover_prob = 75  # low VIX, small gap → likely to fill
                elif v < 18 and abs(gap_pct) < 0.7:
                    cover_prob = 60
                elif v >= 22:
                    cover_prob = 25  # high VIX, gap less likely to fill quickly
                else:
                    cover_prob = 45
            elif kind == "GAP UP":
                if v < 14 and gap_pct < 1.0:
                    cover_prob = 70
                elif v >= 22:
                    cover_prob = 30
                else:
                    cover_prob = 50
            else:
                cover_prob = 50
        except:
            cover_prob = 50
    return {
        "available": True,
        "kind": kind,
        "prev_close": _num(prev_close),
        "open": _num(o),
        "gap_pts": round(gap_pts, 2),
        "gap_pct": gap_pct,
        "high": _num(h),
        "low": _num(l),
        "close": _num(c),
        "range": round(h - l, 2),
        "close_vs_open": round(c - o, 2),
        "fill_pct": fill_pct,
        "unfilled_pts": round(unfilled, 2),
        "cover_prob": cover_prob,
        "vix_at_open": _num(vix_close, 1) if vix_close is not None else None,
    }


def _vix_regime(vix) -> tuple:
    close = vix.get("close")
    chg = vix.get("change_pct") or 0
    if close is None:
        return "UNKNOWN", "flat"
    v = float(close)
    reg = "VERY LOW" if v < 11 else "LOW" if v < 13 else "NORMAL" if v < 16 else "ELEVATED" if v < 20 else "HIGH"
    if v >= 25:
        reg = "EXTREME"
    trend = "rising" if chg > 1 else "falling" if chg < -1 else "flat"
    return reg, trend


def _bias(regime: str, rsi, gap: dict) -> tuple:
    key = regime.upper()
    if "BEARISH" in key:
        b, n, a = 45, 32, 23
        bias = "BEARISH"
    elif "BULLISH" in key:
        b, n, a = 20, 30, 50
        bias = "BULLISH"
    else:
        b, n, a = 32, 38, 30
        bias = "NEUTRAL"
    if rsi is not None and rsi < 30:
        a += 5
        b -= 5
    elif rsi is not None and rsi > 70:
        b += 5
        a -= 5
    if gap.get("available"):
        gap_pct = gap.get("gap_pct", 0) or 0
        fill = gap.get("fill_pct", 0) or 0
        # gap with oversold/overbought is strong mean-reversion signal — keep with existing ADX/RSI/VIX
        if gap_pct <= -0.5 and rsi is not None and rsi < 30 and fill < 50:
            # gap-down oversold, unfilled → bullish bounce likely → boost bullish, cut bearish
            a += 12
            b -= 10
            n += 2
        elif gap_pct >= 0.5 and rsi is not None and rsi > 70 and fill < 50:
            b += 12
            a -= 10
            n += 2
        elif abs(gap_pct) >= 0.5 and fill >= 90:
            a += 2
            b -= 2
        elif abs(gap_pct) < 0.3:
            n += 2
    total = a + n + b
    a, n, b = round(100 * a / total), round(100 * n / total), round(100 * b / total)
    vals = [a, n, b]
    vals[vals.index(min(vals))] += 100 - sum(vals)
    if b > a and b >= 40:
        label = "MILDLY BEARISH" if b < 50 else "BEARISH"
    elif a > b and a >= 40:
        label = "MILDLY BULLISH" if a < 50 else "BULLISH"
    else:
        label = "NEUTRAL"
    return label, {"bullish": vals[0], "neutral": vals[1], "bearish": vals[2]}


def _tradeability(adx, rsi, vix_reg, gap, missing_oi) -> tuple:
    score = 50
    if adx is not None and adx > 40:
        score += 10
    elif adx is not None and adx > 25:
        score += 5
    if vix_reg in ("VERY LOW", "LOW", "NORMAL"):
        score += 10
    if rsi is not None and rsi < 30:
        score -= 8
    if gap.get("available") and abs(gap.get("gap_pct", 0)) >= 0.5:
        score -= 4
    if missing_oi:
        score -= 5
    score = max(0, min(100, score))
    band = "AVOID" if score <= 20 else "VERY LOW" if score <= 40 else "LOW" if score <= 55 else "MODERATE" if score <= 70 else "GOOD" if score <= 85 else "VERY GOOD"
    return score, band


def _confidence(adx, rsi, vix_reg, missing_oi, gap) -> int:
    conf = 62
    if adx is not None and adx > 40:
        conf += 8
    if rsi is not None and rsi < 30:
        conf -= 6
    if vix_reg in ("HIGH", "EXTREME"):
        conf -= 8
    if missing_oi:
        conf -= 4
    if gap.get("available") and abs(gap.get("gap_pct", 0)) >= 0.5:
        conf -= 2
    return max(0, min(100, conf))


def _pcr_info(conn, symbol: str) -> dict:
    exps = conn.execute(
        "SELECT DISTINCT expiry FROM option_chain WHERE symbol=? ORDER BY expiry", (symbol,)
    ).fetchall()
    out = []
    for e in exps[:2]:
        expiry = e["expiry"]
        pe = conn.execute("SELECT COALESCE(SUM(open_interest),0) s FROM option_chain WHERE symbol=? AND expiry=? AND option_type='PE'", (symbol, expiry)).fetchone()["s"]
        ce = conn.execute("SELECT COALESCE(SUM(open_interest),0) s FROM option_chain WHERE symbol=? AND expiry=? AND option_type='CE'", (symbol, expiry)).fetchone()["s"]
        pcr = round(pe / ce, 2) if ce > 0 else None
        out.append({"expiry": expiry, "pe_oi": pe, "ce_oi": ce, "pcr": pcr, "pcr_txt": f"{pcr:.2f}" if pcr is not None else None})
    return {"expiries": out, "available": bool(out)}


def _ce_wall(conn, symbol: str, expiry: str, n: int = 3) -> list:
    rows = conn.execute(
        "SELECT strike, open_interest FROM oi_top_strikes WHERE symbol=? AND expiry=? AND side='CE' ORDER BY rank LIMIT ?",
        (symbol, expiry, n),
    ).fetchall()
    return [{"strike": _num(r["strike"]), "oi": r["open_interest"]} for r in rows]


def _prev_day_top_strikes(conn, symbol: str, date: str, n: int = 3) -> dict:
    """Previous trading day's highest OI strikes for precise direction — point-in-time."""
    prev = conn.execute("SELECT date(timestamp) FROM price_1d WHERE symbol=? AND date(timestamp) < date(?) ORDER BY date(timestamp) DESC LIMIT 1", (symbol, date)).fetchone()
    prev_date = prev[0] if prev else None
    if not prev_date:
        return {"available": False, "date": None, "ce": [], "pe": [], "max_ce_strike": None, "max_pe_strike": None}
    # Try option_chain first, then oi_top_strikes as fallback
    ce = []
    pe = []
    try:
        ce = conn.execute("SELECT strike, open_interest FROM option_chain WHERE symbol=? AND date(timestamp)=? AND option_type='CE' ORDER BY open_interest DESC LIMIT ?", (symbol, prev_date, n)).fetchall()
        pe = conn.execute("SELECT strike, open_interest FROM option_chain WHERE symbol=? AND date(timestamp)=? AND option_type='PE' ORDER BY open_interest DESC LIMIT ?", (symbol, prev_date, n)).fetchall()
        ce = [{"strike": _num(r["strike"]), "oi": r["open_interest"]} for r in ce]
        pe = [{"strike": _num(r["strike"]), "oi": r["open_interest"]} for r in pe]
    except:
        pass
    if not ce:
        try:
            # fallback to oi_top_strikes with prev expiry
            exp_row = conn.execute("SELECT expiry FROM option_expiries WHERE symbol=? AND expiry>=? ORDER BY expiry LIMIT 1", (symbol, prev_date)).fetchone()
            exp = exp_row["expiry"] if exp_row else None
            if exp:
                ce = conn.execute("SELECT strike, open_interest FROM oi_top_strikes WHERE symbol=? AND expiry=? AND side='CE' ORDER BY rank LIMIT ?", (symbol, exp, n)).fetchall()
                pe = conn.execute("SELECT strike, open_interest FROM oi_top_strikes WHERE symbol=? AND expiry=? AND side='PE' ORDER BY rank LIMIT ?", (symbol, exp, n)).fetchall()
                ce = [{"strike": _num(r["strike"]), "oi": r["open_interest"]} for r in ce]
                pe = [{"strike": _num(r["strike"]), "oi": r["open_interest"]} for r in pe]
        except:
            pass
    return {"available": bool(ce or pe), "date": prev_date, "ce": ce, "pe": pe, "max_ce_strike": ce[0]["strike"] if ce else None, "max_pe_strike": pe[0]["strike"] if pe else None}


def _pcr_read(pcr) -> str:
    if pcr is None:
        return "unavailable"
    if pcr < 0.7:
        return "bearish (Call OI dominates — put protection thin)"
    if pcr < 1.0:
        return "leaning bearish"
    if pcr < 1.25:
        return "balanced / neutral"
    return "bullish (Put OI dominates)"


def _strategies(bias_label, probs, reg, vix_reg, vix_trend, adx, rsi, pcr_info, ce_wall, gap) -> dict:
    p = probs
    gap_pct = gap.get("gap_pct", 0) or 0 if gap.get("available") else 0
    gap_fill = gap.get("fill_pct", 0) or 0 if gap.get("available") else 0
    gap_down_oversold = gap.get("available") and gap_pct <= -0.5 and rsi is not None and rsi < 30 and gap_fill < 50
    gap_up_overbought = gap.get("available") and gap_pct >= 0.5 and rsi is not None and rsi > 70 and gap_fill < 50
    basic = {
        "Long Call": round(0.35 * p["bullish"] + (0 if vix_reg in ("HIGH", "EXTREME") else 8) + (10 if gap_down_oversold else 0)),
        "Long Put": round(0.35 * p["bearish"] + (0 if vix_reg in ("HIGH", "EXTREME") else 8) + (6 if rsi is not None and rsi > 30 else -18) + (10 if gap_up_overbought else 0)),
        "Bull Call Spread": round(0.55 * p["bullish"] + 10 + (8 if gap_down_oversold else 0)),
        "Bear Put Spread": round(0.55 * p["bearish"] + 10 + (6 if rsi is not None and rsi < 30 else 0) - (12 if gap_down_oversold else 0)),
        "Bull Put Spread": round(0.4 * p["neutral"] + 0.3 * p["bullish"] + 12 + (12 if gap_down_oversold else 0)),
        "Bear Call Spread": round(0.5 * p["bearish"] + 0.3 * p["neutral"] + 12 + (8 if ce_wall else 0) - (14 if gap_down_oversold else 0) + (12 if gap_up_overbought else 0)),
        "Iron Condor": round(0.5 * p["neutral"] + 0.25 * p["bullish"] + 0.25 * p["bearish"] + (14 if vix_reg in ("VERY LOW", "LOW") else 4) - (10 if adx is not None and adx > 45 else 0) - (10 if gap_down_oversold or gap_up_overbought else 0)),
        "Short Strangle": round(0.4 * p["neutral"] + 8 - (12 if gap.get("available") and abs(gap_pct) >= 0.5 else 0) - (10 if gap_down_oversold or gap_up_overbought else 0)),
        "Short Straddle": round(0.4 * p["neutral"] + 4 - (14 if gap.get("available") and abs(gap_pct) >= 0.5 else 0) - (10 if gap_down_oversold or gap_up_overbought else 0)),
        "Calendar Spread": round(0.3 * p["neutral"] + 6 + (6 if gap_down_oversold or gap_up_overbought else 0)),
    }
    for k in basic:
        basic[k] = max(0, min(100, basic[k]))
    # realistic: when bias is strong, don't let No Trade dominate — let directional spreads win
    strong_bias = (p.get("bullish") or 0) >= 40 or (p.get("bearish") or 0) >= 40 or bias_label in ("BULLISH","BEARISH","MILDLY BULLISH","MILDLY BEARISH")
    if strong_bias:
        basic["No Trade"] = 30
    else:
        basic["No Trade"] = 100 - max(basic.values()) if min(basic.values()) < 25 else 30
    ranked = sorted(basic.items(), key=lambda kv: -kv[1])
    avoid = "Long Put" if (rsi is not None and rsi < 30) else ("Short Straddle" if ranked[0][0] != "Short Straddle" else "Calendar Spread")
    return basic, ranked, avoid


def _expected_range(pivot, atr) -> dict:
    if pivot is None or atr is None:
        return {"upper": None, "lower": None}
    return {"upper": round(pivot + atr, 2), "lower": round(pivot - atr, 2)}


def _trades(conn, date: str, symbol: str | None = None) -> list:
    sql = ("SELECT symbol, direction, strategy, entry_time, locked_price, exit_time, closed_price, points, result, no_trade_conditions, entry_outlook "
           "FROM history WHERE date=? ")
    params: list = [date]
    if symbol:
        sql += "AND symbol=? "
        params.append(symbol)
    sql += "ORDER BY symbol"
    rows = conn.execute(sql, params).fetchall()
    return [
        {
            "symbol": r["symbol"],
            "direction": r["direction"],
            "strategy": r["strategy"],
            "entry_time": r["entry_time"],
            "entry_price": _num(r["locked_price"]),
            "exit_time": r["exit_time"],
            "exit_price": _num(r["closed_price"]),
            "points": _num(r["points"]),
            "result": r["result"],
            "reason": r["no_trade_conditions"],
            "entry_outlook": _parse_json(r["entry_outlook"]),
        }
        for r in rows
    ]


def build_outlook(conn, symbol: str, date: str) -> dict:
    # date-aware: for historical replay (2016) use the latest row *as of* that date, not the latest overall
    ind = conn.execute("SELECT * FROM indicators WHERE symbol=? AND date(timestamp) <= date(?) ORDER BY timestamp DESC LIMIT 1", (symbol, date)).fetchone()
    reg = conn.execute("SELECT * FROM market_regime WHERE symbol=? AND date(timestamp) <= date(?) ORDER BY timestamp DESC LIMIT 1", (symbol, date)).fetchone()
    vix = conn.execute("SELECT * FROM vix_data WHERE date(timestamp) <= date(?) ORDER BY timestamp DESC LIMIT 1", (date,)).fetchone()
    day = conn.execute("SELECT open, high, low, close, volume FROM price_1d WHERE symbol=? AND date(timestamp)=? ORDER BY timestamp DESC LIMIT 1", (symbol, date)).fetchone()

    # robust dict conversion (caller may pass plain tuple cursor)
    def _row_to_dict(r):
        if not r:
            return {}
        if isinstance(r, dict):
            return r
        try:
            return dict(r)
        except:
            try:
                return {k: r[k] for k in r.keys()}  # noqa
            except:
                return {}
    ind = _row_to_dict(ind)
    reg = _row_to_dict(reg)
    vix = _row_to_dict(vix)
    day = _row_to_dict(day)

    # historical fallback: if no indicator/ regime as of that date (price_1d only has 2026-06+), synthesize from price_1d SMA
    if not ind or ind.get("rsi") is None:
        try:
            closes = [r[0] for r in conn.execute("SELECT close FROM price_1d WHERE symbol=? AND date(timestamp) <= date(?) ORDER BY date(timestamp) DESC LIMIT 50", (symbol, date)).fetchall()]
            closes = list(reversed(closes))  # asc
            if len(closes) >= 20 and day and day.get("close"):
                sma20 = sum(closes[-20:]) / 20
                sma50 = sum(closes[-50:]) / 50 if len(closes) >= 50 else sma20
                c = float(day["close"])
                # simple RSI proxy: price momentum
                mom = (c - closes[-10]) / closes[-10] * 100 if len(closes) >= 10 and closes[-10] else 0
                rsi_proxy = 55 if mom > 1 else 45 if mom < -1 else 50
                # regime from price vs SMA
                if c > sma20 > sma50:
                    reg_proxy = "TRENDING_BULLISH"
                elif c < sma20 < sma50:
                    reg_proxy = "TRENDING_BEARISH"
                elif c > sma50:
                    reg_proxy = "BULLISH_RANGE"
                elif c < sma50:
                    reg_proxy = "BEARISH_RANGE"
                else:
                    reg_proxy = "RANGE_BOUND"
                ind = {"rsi": rsi_proxy, "adx": 25, "atr": (closes[-1]-closes[-2]) if len(closes)>=2 else 100, "pivot": sma20, "prev_day_close": closes[-2] if len(closes)>=2 else None, "day_high": day.get("high"), "day_low": day.get("low")}
                if not reg or not reg.get("regime"):
                    reg = {"regime": reg_proxy, "confidence": 55}
                # also synthesize vix if missing
                if not vix or not vix.get("close"):
                    vix = {"close": 14.0, "change_pct": 0, "open": 14, "high": 14.5, "low": 13.5}
        except Exception:
            pass

    rsi, adx, atr = ind.get("rsi"), ind.get("adx"), ind.get("atr")
    pivot = ind.get("pivot")
    prev_close = ind.get("prev_day_close")
    if prev_close is None and day:
        pc = conn.execute("SELECT close FROM price_1d WHERE symbol=? AND date(timestamp)<date(?) ORDER BY date(timestamp) DESC LIMIT 1", (symbol, date)).fetchone()
        prev_close = pc["close"] if pc else None

    gap = _gap(day or {"open": ind.get("day_high"), "high": ind.get("day_high"), "low": ind.get("day_low"), "close": ind.get("day_high"), "open": None, "close": None}, prev_close, vix) if day else {"available": False}
    if (not day) and ind.get("day_high") and prev_close:
        gap = _gap({"open": prev_close, "high": ind.get("day_high"), "low": ind.get("day_low"), "close": round(float(ind.get("day_high")), 2)}, prev_close, vix)

    # === Feature Engine: Previous-day price action (point-in-time) ===
    prev_day = conn.execute("SELECT open, high, low, close FROM price_1d WHERE symbol=? AND date(timestamp) = date(?, '-1 day') ORDER BY timestamp DESC LIMIT 1", (symbol, date)).fetchone()
    prev_day = _row_to_dict(prev_day)
    # 3/5/10/20-day returns and range analysis (point-in-time, only data <= date)
    closes_prev = [r[0] for r in conn.execute("SELECT close FROM price_1d WHERE symbol=? AND date(timestamp) <= date(?, '-1 day') ORDER BY date(timestamp) DESC LIMIT 20", (symbol, date)).fetchall()]
    closes_prev = list(reversed(closes_prev))
    prev_close_actual = closes_prev[-1] if closes_prev else prev_close
    def _ret(days):
        if len(closes_prev) >= days and closes_prev[-days]:
            return round((prev_close_actual - closes_prev[-days]) / closes_prev[-days] * 100, 2)
        return None
    returns = {"3d": _ret(3), "5d": _ret(5), "10d": _ret(10), "20d": _ret(20)}
    prev_range = (prev_day.get("high") - prev_day.get("low")) if prev_day.get("high") and prev_day.get("low") else None
    avg_range = None
    if len(closes_prev) >= 10:
        # avg range last 10 days
        ranges = conn.execute("SELECT AVG(high - low) FROM price_1d WHERE symbol=? AND date(timestamp) <= date(?, '-1 day') ORDER BY date(timestamp) DESC LIMIT 10", (symbol, date)).fetchone()
        avg_range = ranges[0] if ranges else None
    # Previous-day candle features
    prev_body_pct = None
    prev_wick_up = prev_wick_down = None
    prev_trend = "unknown"
    if prev_day.get("open") and prev_day.get("close") and prev_day.get("high") and prev_day.get("low"):
        body = abs(prev_day["close"] - prev_day["open"])
        rng = prev_day["high"] - prev_day["low"]
        if rng:
            prev_body_pct = round(body / rng * 100, 1)
            prev_wick_up = round((prev_day["high"] - max(prev_day["open"], prev_day["close"])) / rng * 100, 1)
            prev_wick_down = round((min(prev_day["open"], prev_day["close"]) - prev_day["low"]) / rng * 100, 1)
        if prev_day["close"] > prev_day["open"] and prev_day["close"] > (prev_day["high"] - rng*0.1):
            prev_trend = "strong_bullish_close_near_high"
        elif prev_day["close"] < prev_day["open"] and prev_day["close"] < (prev_day["low"] + rng*0.1):
            prev_trend = "strong_bearish_close_near_low"
        elif prev_day["close"] > prev_day["open"]:
            prev_trend = "bullish"
        elif prev_day["close"] < prev_day["open"]:
            prev_trend = "bearish"
    # Past few days confirmation (3-5 day trend + OI) for real verdict
    past_closes = closes_prev[-5:] if len(closes_prev) >= 5 else closes_prev
    past_trend = "unknown"
    if len(past_closes) >= 3:
        ups = sum(1 for i in range(1, len(past_closes)) if past_closes[i] > past_closes[i-1])
        downs = len(past_closes) - 1 - ups
        if downs >= 3 and past_closes[-1] < past_closes[-3]:
            past_trend = "3d_downtrend"
        elif ups >= 3 and past_closes[-1] > past_closes[-3]:
            past_trend = "3d_uptrend"
        elif past_closes[-1] > past_closes[0]:
            past_trend = "5d_up"
        elif past_closes[-1] < past_closes[0]:
            past_trend = "5d_down"
    # OI trend past 3 days if available
    oi_trend = "unknown"
    try:
        ce_ois = []
        pe_ois = []
        for d in [row[0] for row in conn.execute("SELECT date(timestamp) FROM price_1d WHERE symbol=? AND date(timestamp) <= date(?, '-1 day') ORDER BY date(timestamp) DESC LIMIT 3", (symbol, date)).fetchall()]:
            ce = conn.execute("SELECT SUM(open_interest) FROM option_chain WHERE symbol=? AND date(timestamp)=? AND option_type='CE'", (symbol, d)).fetchone()[0] or 0
            pe = conn.execute("SELECT SUM(open_interest) FROM option_chain WHERE symbol=? AND date(timestamp)=? AND option_type='PE'", (symbol, d)).fetchone()[0] or 0
            ce_ois.append(ce); pe_ois.append(pe)
        if len(ce_ois) >= 2 and ce_ois[0] > ce_ois[-1] * 1.1:
            oi_trend = "call_buildup"
        elif len(pe_ois) >= 2 and pe_ois[0] > pe_ois[-1] * 1.1:
            oi_trend = "put_buildup"
    except:
        pass
    # Market-open information (if day has open)
    open_vs_prev_high = open_vs_prev_low = None
    if day.get("open") and prev_day.get("high") and prev_day.get("low"):
        open_vs_prev_high = round((day["open"] - prev_day["high"]) / prev_day["high"] * 100, 2)
        open_vs_prev_low = round((day["open"] - prev_day["low"]) / prev_day["low"] * 100, 2)

    # Previous day highest OI strikes for precise direction (point-in-time)
    prev_oi = _prev_day_top_strikes(conn, symbol, date)
    vix_reg, vix_trend = _vix_regime(vix)
    reg_key = str(reg.get("regime", "")).upper()
    regime_label = REGIME_MAP.get(reg_key, reg_key if reg_key else "UNKNOWN")
    # Hierarchical: Regime → Direction → Probability → Expected behaviour (gap + prev-day PA influence)
    bias_label, probs = _bias(regime_label, rsi, gap)
    # VIX-based gap cover prediction: not every gap fills — adjust bias with VIX
    cover_prob = gap.get("cover_prob") if gap.get("available") else None
    if cover_prob is not None:
        if gap.get("kind") == "GAP DOWN" and cover_prob >= 70:
            # gap likely to fill → bullish bounce
            probs["bullish"] = min(100, probs["bullish"] + 6)
            probs["bearish"] = max(0, probs["bearish"] - 4)
        elif gap.get("kind") == "GAP DOWN" and cover_prob <= 30:
            # high VIX, gap unlikely to fill quickly → bearish continuation
            probs["bearish"] = min(100, probs["bearish"] + 5)
        elif gap.get("kind") == "GAP UP" and cover_prob >= 70:
            probs["bearish"] = min(100, probs["bearish"] + 6)
            probs["bullish"] = max(0, probs["bullish"] - 4)
    # Adjust bias with previous-day price action (along with existing gap/RSI)
    if prev_trend == "strong_bullish_close_near_high" and gap.get("available") and gap.get("gap_pct", 0) > -0.3:
        probs["bullish"] = min(100, probs["bullish"] + 8)
        probs["bearish"] = max(0, probs["bearish"] - 5)
    elif prev_trend == "strong_bearish_close_near_low" and gap.get("available") and gap.get("gap_pct", 0) < 0.3:
        probs["bearish"] = min(100, probs["bearish"] + 8)
        probs["bullish"] = max(0, probs["bullish"] - 5)
    # Previous day highest OI strikes influence direction precisely
    if prev_oi.get("available") and day.get("close"):
        try:
            spot = float(day["close"])
            ce_strike = prev_oi.get("max_ce_strike")
            pe_strike = prev_oi.get("max_pe_strike")
            if ce_strike and abs(ce_strike - spot) / spot < 0.015 and ce_strike > spot:
                probs["bearish"] = min(100, probs["bearish"] + 6)
                probs["bullish"] = max(0, probs["bullish"] - 4)
            if pe_strike and abs(pe_strike - spot) / spot < 0.015 and pe_strike < spot:
                probs["bullish"] = min(100, probs["bullish"] + 6)
                probs["bearish"] = max(0, probs["bearish"] - 4)
        except:
            pass
        _total2 = probs["bullish"] + probs["neutral"] + probs["bearish"]
        if _total2:
            for k in probs:
                probs[k] = round(probs[k] / _total2 * 100)
            probs["neutral"] += 100 - sum(probs.values())

    pcr = _pcr_info(conn, symbol)
    next_exp = None
    if pcr["expiries"]:
        next_exp = pcr["expiries"][0]["expiry"]
    wall = _ce_wall(conn, symbol, next_exp) if next_exp else []
    missing_oi = not pcr["available"] and not prev_oi["available"]

    score, band = _tradeability(adx, rsi, vix_reg, gap, missing_oi)
    conf = _confidence(adx, rsi, vix_reg, missing_oi, gap)

    exp = conn.execute("SELECT expiry FROM option_expiries WHERE symbol=? AND expiry>=date(?) ORDER BY expiry LIMIT 1", (symbol, date)).fetchone()
    exp_txt = exp["expiry"] if exp else ("NEXT_WEEKLY" if pcr["expiries"] else "—")

    er = _expected_range(pivot, atr)

    sup = [_num(ind.get(k)) for k in ("s1", "s2", "s3")]
    res = [_num(ind.get(k)) for k in ("r1", "r2", "r3")]

    basic, ranked, avoid = _strategies(bias_label, probs, regime_label, vix_reg, vix_trend, adx, rsi, pcr, wall, gap)

    best = ranked[0]
    second = next((it for it in ranked if it[0] != best[0]), None)
    rsi_bounce = rsi is not None and rsi < 30
    trend_strong = adx is not None and adx > 45
    # Past few days confirmation: need alignment of past trend + OI with bias for real verdict
    past_confirms_bias = False
    if bias_label in ("BEARISH", "MILDLY BEARISH") and past_trend in ("3d_downtrend", "5d_down") and oi_trend in ("call_buildup", "unknown"):
        past_confirms_bias = True
    elif bias_label in ("BULLISH", "MILDLY BULLISH") and past_trend in ("3d_uptrend", "5d_up") and oi_trend in ("put_buildup", "unknown"):
        past_confirms_bias = True
    elif bias_label == "NEUTRAL" and past_trend == "unknown":
        past_confirms_bias = True
    if rsi_bounce and gap.get("available") and gap.get("fill_pct", 0) >= 90:
        verdict = "WAIT"
    elif past_trend != "unknown" and not past_confirms_bias and bias_label not in ("NEUTRAL",):
        # past 3-5d contradicts current bias → wait for confirmation, not trade
        verdict = "WAIT"
    elif best[1] >= 70 and not (gap.get("available") and abs(gap.get("gap_pct", 0)) >= 1):
        verdict = "TRADE"
    else:
        verdict = "WAIT"

    res2 = res[1] if len(res) > 1 else res[0]
    sup2 = sup[1] if len(sup) > 1 else sup[0]
    res0 = res[0] if res else None
    sup0 = sup[0] if sup else None

    wall_txt = " · ".join(f"{w['strike']:,} ({w['oi']:,.0f} OI)" for w in wall) if wall else "no readable wall"
    call_oi = (f"Wall above spot at {wall_txt} — overhead resistance for {exp_txt}." if wall else
               "Call OI build-up above spot not available (missing EOD chain).")
    pe_oi_week = pcr["expiries"][0]["pe_oi"] if pcr["expiries"] else 0
    ce_oi_week = pcr["expiries"][0]["ce_oi"] if pcr["expiries"] else 0
    week_pcr = pcr["expiries"][0]["pcr"] if pcr["expiries"] else None
    put_oi = (f"Put protection thin vs calls (weekly PE {pe_oi_week:,.0f} vs CE {ce_oi_week:,.0f}) — weak support beyond {sup0}."
              if pe_oi_week else "Put OI detail unavailable (missing EOD chain).")
    if week_pcr is not None and week_pcr < 0.95:
        oi_signal = "MIXED"
    oi_signal = "BEARISH" if (week_pcr is not None and week_pcr < 0.7) else "MIXED" if pcr["available"] else "NEUTRAL"
    iv_env = (f"{vix_reg} VIX ({vix.get('close')} ) — {vix_trend}. Environment favours defined-risk premium selling; not naked selling, not late option buying."
              if vix.get("close") is not None else "IV data unavailable.")

    vol_fav = "defined-risk premium selling" if vix_reg in ("VERY LOW", "LOW", "NORMAL") else "waiting"

    strat_list = []
    why1 = [
        f"Sells into overhead resistance (weekly CE wall {wall_txt}) priced {res0}–{res2}.",
        f"Defined-risk; {vix_reg} VIX environment favours premium capture.",
        f"Aligns with {bias_label} bias while {('RSI ' + str(rsi) + ' oversold caps downside-selling edge') if rsi_bounce else 'trend supports it'}.",
    ]
    strat_list.append({
        "rank": 1, "name": best[0], "fit": best[1],
        "why": why1,
        "entry": f"ONLY if {symbol} rallies into {res0}–{res2} and stalls/rejects, or opens near prior close. Never unconditional.",
        "entry_trigger": {"mode": "rally_into_resistance", "zone": {"lower": res0, "upper": res2}, "direction": "SHORT"} if res0 and res2 else {},
        "risk": f"Gap/event upside above {res0}; stop if spot trades through the sold strike with conviction.",
        "exit": "Decay to ~50% of credit, or flat by 15:20; hard invalidation above the sold strike.",
    })
    if second and second[0] != "No Trade":
        strat_list.append({"rank": 2, "name": second[0], "fit": second[1], "why": "Companion defined-risk alternative if price confirms a range.", "entry": "", "risk": "", "exit": ""})
    avoid_reason = ("Oversold (RSI %.0f) + near-full gap fill = late, high-premium entry with IV-expansion risk." % rsi) if rsi_bounce else "Typically poor risk/reward in the current regime; check invalidation first."

    breakout_txt = (f"Sustained close above {res2} → gap fully filled, bear thesis weakens.") if res2 else "—"
    breakdown_txt = (f"Close below {sup2} → downtrend resumes toward {sup[2] if len(sup) > 2 else sup2}.") if sup2 else "—"

    primary_view = (
        f"Regime is {regime_label.lower()} (ADX {adx}, price below EMA20/50) but the tape is short-term oversold "
        f"(RSI {rsi}) after a {gap.get('gap_pct') if gap.get('available') else 'N/A'}% gap-down that filled to "
        f"{gap.get('fill_pct')}% — netting fresh shorts into that squeeze failed (see trade record). "
        f"{vix_reg} volatility ({vix.get('close') if vix.get('close') is not None else 'N/A'}) keeps the edge with "
        f"defined-risk premium selling. Fresh exposure stays conditioned on resolution of the gap zone."
    )

    trades = _trades(conn, date, symbol) if verdict == "TRADE" else []

    payload = {
        "date": date,
        "symbol": symbol,
        "as_of_ist": datetime.now(IST).strftime("%Y-%m-%d %H:%M IST"),
        "regime": {"primary": regime_label, "engine": reg_key, "confidence": _num(reg.get("confidence"))},
        "bias": {"label": bias_label, "probs": probs},
        "confidence": conf,
        "vix": {"value": _num(vix.get("close"), 1), "regime": vix_reg, "trend": vix_trend,
                "change_pct": _num(vix.get("change_pct"), 2), "open": _num(vix.get("open"), 1),
                "high": _num(vix.get("high"), 1), "low": _num(vix.get("low"), 1)},
        "tradeability": {"score": score, "band": band},
        "expected_range": er,
        "volatility_favours": vol_fav,
        "gap": gap,
        "key_levels": {"supports": sup, "resistances": res, "breakout": breakout_txt, "breakdown": breakdown_txt},
        "indicators": {"adx": _num(adx), "rsi": _num(rsi), "atr": _num(atr),
                       "ema20": _num(ind.get("ema20")), "ema50": _num(ind.get("ema50")),
                       "vwap": _num(ind.get("vwap")), "macd": _num(ind.get("macd"), 2)},
        "expiry": exp_txt,
        "options": {"pcr": pcr, "ce_wall": wall, "call_oi": call_oi, "put_oi": put_oi,
                    "oi_signal": oi_signal, "iv_environment": iv_env, "prev_day_oi": prev_oi},
        "feature_engine": {
            "prev_day": {"open": _num(prev_day.get("open")), "high": _num(prev_day.get("high")), "low": _num(prev_day.get("low")), "close": _num(prev_day.get("close")),
                         "body_pct": prev_body_pct, "wick_up": prev_wick_up, "wick_down": prev_wick_down, "trend": prev_trend,
                         "range": _num(prev_range), "avg_range": _num(avg_range), "returns": returns},
            "market_open": {"gap_pct": gap.get("gap_pct"), "fill_pct": gap.get("fill_pct"), "open_vs_prev_high": open_vs_prev_high, "open_vs_prev_low": open_vs_prev_low},
            "past_confirmation": {"past_trend": past_trend, "oi_trend": oi_trend, "confirms_bias": past_confirms_bias if 'past_confirms_bias' in locals() else False},
            "hierarchy": {"regime": regime_label, "direction": bias_label, "probs": probs, "expected_behaviour": "Bullish continuation" if prev_trend == "strong_bullish_close_near_high" else "Bearish continuation" if prev_trend == "strong_bearish_close_near_low" else "Range"},
            "prev_day_oi": prev_oi,
            "point_in_time": True
        },
        "strategies": strat_list,
        "strategy_to_avoid": avoid,
        "avoid_reason": avoid_reason,
        "decision": {"verdict": verdict, "primary_view": primary_view,
                     "bull_invalidation": (f"Daily close above {res0}" if res0 else "—"),
                     "bear_invalidation": (f"Close below {sup2}" if sup2 else "—")},
        "trades": trades,
    }
    return payload


def merge_llm_into_payload(conn, symbol: str, payload: dict) -> dict:
    """Overlay the most recent genuine LLM outlook onto the rule-based framework.

    LLM is primary for regime/bias/confidence/narrative; the rule engine remains
    the structural backbone (expected range, gap, options, tradeability, trades).
    A rule-based ai_outlooks row (market_summary marked '<SYM> analysis - <REGIME>')
    or absence of any LLM row leaves the framework untouched (rule-based fallback).
    """
    try:
        row = conn.execute(
            "SELECT outlook, timestamp FROM ai_outlooks WHERE symbol=? ORDER BY timestamp DESC LIMIT 1",
            (symbol,),
        ).fetchone()
    except Exception:
        row = None
    if not row:
        return payload
    try:
        llm = json.loads(row["outlook"]) if isinstance(row["outlook"], str) else row["outlook"]
        if not isinstance(llm, dict):
            return payload
    except Exception:
        return payload
    summary = (llm.get("market_summary") or "").strip()
    if not summary or "analysis - " in summary:
        return payload  # rule-based fallback row, not a genuine LLM narrative

    regime = str(llm.get("market_regime") or "").upper().replace(" ", "_")
    bias = str(llm.get("directional_bias") or "").upper()
    conf = llm.get("confidence")
    try:
        conf = max(0.0, min(100.0, float(conf)))
    except (TypeError, ValueError):
        conf = None

    decision = payload.setdefault("decision", {})
    if summary:
        decision["primary_view"] = summary
    if regime:
        decision.setdefault("regime_override", {})["engine"] = regime
    if bias:
        decision.setdefault("regime_override", {})["bias"] = bias
    if conf is not None:
        decision.setdefault("regime_override", {})["confidence"] = round(conf)

    if regime:
        p_regime = payload.setdefault("regime", {})
        p_regime["engine"] = regime
        mapped = REGIME_MAP.get(regime, regime)
        p_regime["primary"] = mapped
    if bias:
        payload.setdefault("bias", {})["label"] = bias
    if conf is not None:
        payload["confidence"] = round(conf)

    sup = [n for n in (llm.get("support_levels") or []) if isinstance(n, (int, float))]
    res = [n for n in (llm.get("resistance_levels") or []) if isinstance(n, (int, float))]
    if sup or res:
        kl = payload.setdefault("key_levels", {})
        if sup:
            kl["supports"] = [_num(n) for n in sup]
        if res:
            kl["resistances"] = [_num(n) for n in res]

    payload["ai_source"] = "LLM"
    payload["llm_generated_at"] = row["timestamp"]
    return payload


def render_html(p: dict, date: str) -> str:
    pretty = datetime.strptime(date, "%Y-%m-%d").strftime("%d %B %Y")
    sym = p.get("symbol", SYMBOL)
    title = f"AI {sym} Market Outlook — {pretty}"
    regime_lbl = (p.get("regime") or {}).get("primary", "—")
    bias_lbl = (p.get("bias") or {}).get("label", "—")
    conf = p.get("confidence")
    trade = (p.get("tradeability") or {}).get("band", "—")
    verdict = (p.get("decision") or {}).get("verdict", "—")
    desc = (f"Data-driven intraday market outlook for {sym} on {pretty}: regime {regime_lbl}, bias {bias_lbl}, "
            f"confidence {conf}%, tradeability {trade}, AI verdict {verdict} — full 8-factor scoring, options intelligence, "
            f"strategies, key levels, risk and invalidation.")
    url = f"https://tradingai.in/market/outlook-{sym.lower()}-{date}.html"
    name = (p.get("display") or sym)
    ld = json.dumps({"@context": "https://schema.org", "@graph": [
        {"@type": "Organization", "name": "TradingAI", "url": "https://tradingai.in/"},
        {"@type": "Article", "headline": title, "description": desc,
         "author": {"@type": "Organization", "name": "TradingAI"},
         "publisher": {"@type": "Organization", "name": "TradingAI"}, "url": url}
    ]}, ensure_ascii=False)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<!-- Google tag (gtag.js) -->
<script async src="https://www.googletagmanager.com/gtag/js?id=G-MJ3X88QYEL"></script>
<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-pub-2262405054444130" crossorigin="anonymous"></script>
<script>
  window.dataLayer = window.dataLayer || [];
  function gtag(){{dataLayer.push(arguments);}}
  gtag('js', new Date());
  gtag('config', 'G-MJ3X88QYEL');
</script>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<meta name="description" content="{desc}">
<link rel="canonical" href="{url}">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{desc}">
<meta property="og:type" content="article">
<meta property="og:url" content="{url}">
<meta name="twitter:card" content="summary">
<script type="application/ld+json">{ld}</script>
<link rel="icon" href="/favicon.svg" type="image/svg+xml">
<link rel="alternate icon" href="/favicon.ico" type="image/x-icon">
<link rel="apple-touch-icon" href="/apple-touch-icon.svg">
<link rel="stylesheet" href="../assets/css/main.css">
<script src="../assets/js/live-blink.js" defer></script>
</head>
<body>
<header>
  <div class="brand-row"><div><h1><a href="/index.html"><img src="/favicon.svg" alt="" width="22" height="22" style="vertical-align:-3px;margin-right:6px;border-radius:6px">TradingAI</a></h1>
  <p class="tagline">AI-Assisted Market Intelligence Platform</p></div><span id="live-clock"></span></div>
</header>
<main>
  <div class="updated-bar"><span id="last-updated-bar"></span></div>
  <div id="dashboard"></div>
  <div class="card content-card" style="margin-top:1.5rem">
    <h3>How to read this outlook</h3>
    <p>This is the TradingAI AI Market Outlook for {name} on {pretty}. Every section — the market regime, probability bars, 8-factor scoring grid, options intelligence, strategies, key levels, risk and AI decision — comes from the same automatic pipeline: publicly available NSE data in, structured analysis out.</p>
    <p>The sections reinforce one another. The regime tells you the macro posture. The probability bars quantify directional bias. The 8-factor grid breaks down why the AI holds that view — from trend and momentum to VIX and breadth. The options intelligence summarises where the big money sits, and the AI-Gated Trade Record shows the day's actual paper trades that followed this verdict.</p>
    <p>This is automated research, not advice, and derivatives risk losing the entire premium and more. Verify data with your broker and decide for yourself.</p>
  </div>
<footer>
  <p>TradingAI provides market analysis and decision-support information. No strategy or outlook guarantees profit. Verify market data and consider your own risk tolerance before trading.</p>
  <p class="status" style="margin-top:0.6rem"><a href="../about.html">About</a> · <a href="../contact.html">Contact</a> · <a href="../privacy.html">Privacy</a> · <a href="../terms.html">Terms</a> · <a href="../disclaimer.html">Disclaimer</a> · <a href="../sitemap.xml">Sitemap</a></p></footer>
</main>
<script src="../assets/js/ai-outlook.js"></script>
<script>
(function(){{
  var _lastDataTs=null;
  function fmtIST(ts){{try{{if(ts==null||ts==='')return null;var d=new Date(ts);if(isNaN(d.getTime()))return null;var f=new Intl.DateTimeFormat('en-GB',{{timeZone:'Asia/Kolkata',day:'2-digit',month:'short',year:'numeric',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false}});var p={{}};f.formatToParts(d).forEach(function(x){{p[x.type]=x.value;}});return p.day+' '+p.month+' '+p.year+', '+p.hour+':'+p.minute+':'+p.second;}}catch(e){{return null;}}}}
  function setLastUpdated(timestamp,ok){{var bar=document.getElementById('last-updated-bar');if(!bar)return;if(timestamp){{_lastDataTs=timestamp;}}var show=fmtIST(_lastDataTs);if(ok===false){{bar.style.color='#dc2626';bar.textContent='Update failed — retrying'+(show?(' | Data as of '+show+' IST'):'');return;}}bar.style.color='';if(!show){{bar.textContent='Last refreshed: —';return;}}bar.textContent='Data as of '+show+' IST';}}
  function tickClock(){{var el=document.getElementById('live-clock');if(!el)return;try{{el.textContent=new Intl.DateTimeFormat('en-GB',{{timeZone:'Asia/Kolkata',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false}}).format(new Date())+' IST';}}catch(e){{}}}}
  setInterval(tickClock,1000);tickClock();
  setLastUpdated(new Date().toISOString(),true);
  document.addEventListener('DOMContentLoaded',function(){{
    renderOutlookDashboard('dashboard',{{symbol:'{sym}',api:'{sym.lower()}',displayName:'{name}',apiBase:'..',tabBase:'../indices/',date:'{date}'}});
  }});
}})();
</script>
</body>
</html>"""


def main() -> None:
    date_str = datetime.now(IST).strftime("%Y-%m-%d")
    symbol = SYMBOL
    webroot = None
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--date" and i + 1 < len(args):
            date_str, i = args[i + 1], i + 2
        elif args[i] == "--symbol" and i + 1 < len(args):
            symbol, i = args[i + 1], i + 2
        elif args[i] == "--webroot" and i + 1 < len(args):
            webroot, i = args[i + 1], i + 2
        else:
            i += 1
    conn = _db()
    refresh_ai_outlook(conn, symbol)
    payload = build_outlook(conn, symbol, date_str)
    payload = merge_llm_into_payload(conn, symbol, payload)
    conn.execute(
        "INSERT INTO market_outlooks (date, symbol, payload, created_at) VALUES (?,?,?,?) "
        "ON CONFLICT(date, symbol) DO UPDATE SET payload=excluded.payload, created_at=excluded.created_at",
        (date_str, symbol, json.dumps(payload, ensure_ascii=False), datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")),
    )
    conn.commit()
    conn.close()
    html = render_html(payload, date_str)
    outdir = os.path.join(webroot, "market") if webroot else os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "market")
    os.makedirs(outdir, exist_ok=True)
    name = f"outlook-{symbol.lower()}-{date_str}.html"
    with open(os.path.join(outdir, name), "w") as f:
        f.write(html)
    print(f"wrote {name} ({len(html)} bytes) for {symbol} {date_str}")


# Only these core indices get the LLM-powered outlook (twice daily via cron).
INDEX_SYMBOLS = frozenset({"NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX"})


def refresh_ai_outlook(conn, symbol: str) -> None:
    """One LLM outlook per run (twice daily via cron 09:30/19:00), rule-based fallback.

    Feeds the per-symbol `ai_outlook` narrative block shown on /api/<symbol>,
    market grid, scanner, strategies and stock-options pages. LLM is restricted to
    the 4 core indices (INDEX_SYMBOLS); any other symbol falls back to rule-based.
    The intraday poller reuses/stores the latest so it never calls the LLM itself."""
    try:
        from ai_outlook import AIOutlookEngine
        if symbol not in INDEX_SYMBOLS:
            print(f"  LLM skipped (indices only): {symbol} -> rule-based fallback")
            return
        ind = conn.execute("SELECT * FROM indicators WHERE symbol=? ORDER BY timestamp DESC LIMIT 1", (symbol,)).fetchone()
        reg = conn.execute("SELECT * FROM market_regime WHERE symbol=? ORDER BY timestamp DESC LIMIT 1", (symbol,)).fetchone()
        vix = conn.execute("SELECT * FROM vix_data ORDER BY timestamp DESC LIMIT 1").fetchone()
        q = conn.execute("SELECT * FROM price_1m WHERE symbol=? ORDER BY timestamp DESC LIMIT 1", (symbol,)).fetchone()
        ind = dict(ind) if ind else {}
        reg = dict(reg) if reg else {}
        vix = dict(vix) if vix else {}
        q = dict(q) if q else {}
        price = q.get("close") or ind.get("day_high") or 0
        data = {
            "price": price,
            "previous_close": q.get("open", 0),
            "rsi": ind.get("rsi"),
            "macd": (ind.get("macd") or {}).get("macd") if isinstance(ind.get("macd"), dict) else ind.get("macd"),
            "adx": ind.get("adx"),
            "atr": ind.get("atr"),
            "vwap": ind.get("vwap"),
            "pivot": ind.get("pivot"),
            "cpr": ind.get("cpr_classification", ""),
            "vix": (vix.get("close") or 0),
            "volume": q.get("volume", 0),
            "regime": (reg.get("regime") or "UNKNOWN"),
            "support_levels": (ind.get("support_resistance") or {}).get("support", []) if isinstance(ind.get("support_resistance"), dict) else [],
            "resistance_levels": (ind.get("support_resistance") or {}).get("resistance", []) if isinstance(ind.get("support_resistance"), dict) else [],
            "options_unavailable": True,
            "symbol": symbol,
            "data_quality": "GOOD",
        }
        engine = AIOutlookEngine()
        outlook = engine.generate(symbol, data) or {}
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        conn.execute(
            "INSERT OR REPLACE INTO ai_outlooks (symbol, timestamp, outlook, data_quality) VALUES (?,?,?,?)",
            (symbol, ts, json.dumps(outlook, ensure_ascii=False), "GOOD"),
        )
        print(f"  LLM ai_outlook refreshed for {symbol}: {outlook.get('market_regime','?')} bias={outlook.get('directional_bias','?')}")
    except Exception as e:
        print(f"  ai_outlook refresh failed for {symbol}: {repr(e)}")


if __name__ == "__main__":
    main()