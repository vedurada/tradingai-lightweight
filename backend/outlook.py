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


def _gap(day: dict, prev_close) -> dict:
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
        if abs(gap.get("gap_pct", 0)) >= 0.5 and gap.get("fill_pct", 0) >= 90:
            a += 2
            b -= 2
        elif abs(gap.get("gap_pct", 0)) < 0.3:
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
    basic = {
        "Long Call": round(0.35 * p["bullish"] + (0 if vix_reg in ("HIGH", "EXTREME") else 8)),
        "Long Put": round(0.35 * p["bearish"] + (0 if vix_reg in ("HIGH", "EXTREME") else 8) + (6 if rsi is not None and rsi > 30 else -18)),
        "Bull Call Spread": round(0.55 * p["bullish"] + 10),
        "Bear Put Spread": round(0.55 * p["bearish"] + 10 + (6 if rsi is not None and rsi < 30 else 0)),
        "Bull Put Spread": round(0.4 * p["neutral"] + 0.3 * p["bullish"] + 12),
        "Bear Call Spread": round(0.5 * p["bearish"] + 0.3 * p["neutral"] + 12 + (8 if ce_wall else 0)),
        "Iron Condor": round(0.5 * p["neutral"] + 0.25 * p["bullish"] + 0.25 * p["bearish"] + (14 if vix_reg in ("VERY LOW", "LOW") else 4) - (10 if adx is not None and adx > 45 else 0)),
        "Short Strangle": round(0.4 * p["neutral"] + 8 - (12 if gap.get("available") and abs(gap.get("gap_pct", 0)) >= 0.5 else 0)),
        "Short Straddle": round(0.4 * p["neutral"] + 4 - (14 if gap.get("available") and abs(gap.get("gap_pct", 0)) >= 0.5 else 0)),
        "Calendar Spread": round(0.3 * p["neutral"] + 6),
    }
    for k in basic:
        basic[k] = max(0, min(100, basic[k]))
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
    ind = conn.execute("SELECT * FROM indicators WHERE symbol=? ORDER BY timestamp DESC LIMIT 1", (symbol,)).fetchone()
    reg = conn.execute("SELECT * FROM market_regime WHERE symbol=? ORDER BY timestamp DESC LIMIT 1", (symbol,)).fetchone()
    vix = conn.execute("SELECT * FROM vix_data ORDER BY timestamp DESC LIMIT 1").fetchone()
    day = conn.execute("SELECT open, high, low, close, volume FROM price_1d WHERE symbol=? AND date(timestamp)=? ORDER BY timestamp DESC LIMIT 1", (symbol, date)).fetchone()

    ind = dict(ind) if ind else {}
    reg = dict(reg) if reg else {}
    vix = dict(vix) if vix else {}
    day = dict(day) if day else {}

    rsi, adx, atr = ind.get("rsi"), ind.get("adx"), ind.get("atr")
    pivot = ind.get("pivot")
    prev_close = ind.get("prev_day_close")
    if prev_close is None and day:
        pc = conn.execute("SELECT close FROM price_1d WHERE symbol=? AND date(timestamp)<date(?) ORDER BY date(timestamp) DESC LIMIT 1", (symbol, date)).fetchone()
        prev_close = pc["close"] if pc else None

    gap = _gap(day or {"open": ind.get("day_high"), "high": ind.get("day_high"), "low": ind.get("day_low"), "close": ind.get("day_high"), "open": None, "close": None}, prev_close) if day else {"available": False}
    if (not day) and ind.get("day_high") and prev_close:
        gap = _gap({"open": prev_close, "high": ind.get("day_high"), "low": ind.get("day_low"), "close": round(float(ind.get("day_high")), 2)}, prev_close)

    vix_reg, vix_trend = _vix_regime(vix)
    reg_key = str(reg.get("regime", "")).upper()
    regime_label = REGIME_MAP.get(reg_key, reg_key if reg_key else "UNKNOWN")
    bias_label, probs = _bias(regime_label, rsi, gap)

    pcr = _pcr_info(conn, symbol)
    next_exp = None
    if pcr["expiries"]:
        next_exp = pcr["expiries"][0]["expiry"]
    wall = _ce_wall(conn, symbol, next_exp) if next_exp else []
    missing_oi = not pcr["available"]

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
    if rsi_bounce and gap.get("available") and gap.get("fill_pct", 0) >= 90:
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
                    "oi_signal": oi_signal, "iv_environment": iv_env},
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