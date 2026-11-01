"""Point-in-time feature construction (spec.md §2).

Every function here takes only the bars that were available at the moment the
feature becomes knowable. Nothing reads a future bar.
"""
import statistics
from datetime import datetime, timedelta


# ---------------------------------------------------------------- session agg
def daily_stats(bars):
    """Aggregate one session's bars into the daily OHLC + wick features."""
    if not bars:
        return None
    o = bars[0]["o"]
    h = max(b["h"] for b in bars)
    l = min(b["l"] for b in bars)
    c = bars[-1]["c"]
    rng = h - l
    close_loc = 0.0 if rng <= 0 else (c - l) / rng
    return {
        "open": o, "high": h, "low": l, "close": c, "range": rng,
        "body": c - o, "body_pct": 0.0 if rng <= 0 else (c - o) / rng,
        "upper_wick": h - max(o, c), "lower_wick": min(o, c) - l,
        "close_location": close_loc,
        "first_bar": bars[0]["hhmm"], "last_bar": bars[-1]["hhmm"],
        "n_bars": len(bars),
    }


# ---------------------------------------------------------------------- CPR
def cpr_from(high, low, close):
    """Production formula (app/research/cpr_strategy_engine.py:33).

    P = (H+L+C)/3 ; BC = (H+L)/2 ; TC = 2P-BC ; lower=min(BC,TC) ; upper=max(BC,TC)
    """
    p = (high + low + close) / 3.0
    bc = (high + low) / 2.0
    tc = 2.0 * p - bc
    lower, upper = (bc, tc) if bc <= tc else (tc, bc)
    return {
        "pp": p, "bc": bc, "tc": tc, "lower_cpr": lower, "upper_cpr": upper,
        "width_pts": upper - lower,
        "width_pct": 0.0 if p == 0 else 100.0 * (upper - lower) / p,
    }


def pivots_from(high, low, pp):
    rng = high - low
    return {"r1": 2 * pp - low, "s1": 2 * pp - high,
            "r2": pp + rng, "s2": pp - rng}


def cpr_class(width_pct, narrow=0.15, wide=0.30):
    """Production thresholds (cpr_strategy_engine.classify_cpr)."""
    if width_pct < narrow:
        return "NARROW"
    if width_pct > wide:
        return "WIDE"
    return "NORMAL"


# ------------------------------------------------------- previous-day action
def prev_day_features(stats, prev_stats, prior_ranges):
    """Model A features for a session, computed from the PRIOR session only."""
    if stats is None or prev_stats is None:
        return None
    rng = stats["range"]
    cl = stats["close_location"]
    if rng > 0:
        day_type = ("INSIDE" if (stats["high"] <= prev_stats["high"] and
                                 stats["low"] >= prev_stats["low"]) else
                    "OUTSIDE" if (stats["high"] >= prev_stats["high"] and
                                  stats["low"] <= prev_stats["low"]) else "NORMAL")
    else:
        day_type = "NORMAL"
    hh = stats["high"] > prev_stats["high"]
    hl = stats["low"] > prev_stats["low"]
    structure = ("HH_HL" if hh and hl else "HH_LL" if hh else
                 "LH_HL" if hl else "LH_LH")
    if cl >= 0.70:
        close_class = "NEAR_HIGH"
    elif cl <= 0.30:
        close_class = "NEAR_LOW"
    else:
        close_class = "MIDDLE"
    ret = None
    if prev_stats["close"]:
        ret = 100.0 * (stats["close"] - prev_stats["close"]) / prev_stats["close"]
    ratio = None
    if prior_ranges and len(prior_ranges) >= 5 and statistics.median(prior_ranges):
        ratio = rng / statistics.median(prior_ranges)
    return {
        "pd_open": stats["open"], "pd_high": stats["high"],
        "pd_low": stats["low"], "pd_close": stats["close"], "pd_range": rng,
        "pd_body": stats["body"], "pd_body_pct": stats["body_pct"],
        "pd_upper_wick": stats["upper_wick"], "pd_lower_wick": stats["lower_wick"],
        "pd_close_location": cl, "pd_return_pct": ret,
        "pd_range_ratio": ratio, "pd_structure": structure,
        "pd_day_type": day_type, "pd_close_class": close_class,
        "pd_higher_high": hh, "pd_higher_low": hl,
    }


# ------------------------------------------------------------------- gap
def gap_features(today_open, pd_close, pd_high, pd_low, lower_cpr, upper_cpr):
    """Magnitude and location stored separately (spec §2.3)."""
    pts = today_open - pd_close
    rng = pd_high - pd_low
    gap_pct = 0.0 if not pd_close else 100.0 * pts / pd_close
    gap_vs_range = None if rng <= 0 else pts / rng
    gap_dir = "UP" if pts > 2 else "DOWN" if pts < -2 else "FLAT"
    if today_open > upper_cpr:
        cpr_pos = "ABOVE_CPR"
    elif today_open < lower_cpr:
        cpr_pos = "BELOW_CPR"
    else:
        cpr_pos = "INSIDE_CPR"
    if today_open > pd_high:
        range_pos = "ABOVE_PDH"
    elif today_open < pd_low:
        range_pos = "BELOW_PDL"
    else:
        range_pos = "INSIDE_RANGE"
    return {
        "gap_points": pts, "gap_pct": gap_pct, "gap_vs_prev_range": gap_vs_range,
        "gap_dir": gap_dir, "cpr_pos": cpr_pos, "prev_range_pos": range_pos,
        "gap_cell": "%s|%s" % (gap_dir, cpr_pos),
    }


# ---------------------------------------------------------- opening range
def opening_range(bars, n_bars=3):
    """OR from the first n_bars bars (3 => 09:15-09:30, 6 => 09:15-09:45).

    Returns None when the range is not fully covered by completed bars.
    """
    if len(bars) < n_bars:
        return None
    head = bars[:n_bars]
    if head[0]["hhmm"] != "09:15":
        return None
    if any(not b["complete"] for b in head):
        return None
    return {
        "or_high": max(b["h"] for b in head),
        "or_low": min(b["l"] for b in head),
        "or_bars": n_bars,
        "or_end": head[-1]["hhmm"],
        "or_end_ts": head[-1]["ts"],
    }


# ------------------------------------------------------------ VWAP (proxy)
def vwap_proxy_series(bars):
    """Equal-weight typical-price VWAP (volume is 0 everywhere).

    Documented proxy - NOT a volume weighted average.
    """
    out = []
    acc = 0.0
    for b in bars:
        tp = (b["h"] + b["l"] + b["c"]) / 3.0
        acc += tp
        out.append(acc / (len(out) + 1))
    return out


# ------------------------------------------------------------------ ATR
def atr_proxy(bars, period=14):
    """ATR(period) of 5-minute true ranges from ONE session (no look-ahead)."""
    if len(bars) < 2:
        return None
    trs = []
    for i in range(1, len(bars)):
        h, l, pc = bars[i]["h"], bars[i]["l"], bars[i - 1]["c"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    if len(trs) < period:
        return None
    return sum(trs[-period:]) / float(period)


# --------------------------------------------------------------- session ctx
def build_context(sessions, session_dates, prior_map):
    """Build one context dict per session: previous-day features, CPR, gap.

    sessions: date -> bars ; session_dates: ordered list of usable dates
    """
    contexts = {}
    stats_by_date = {d: daily_stats(bars) for d, bars in sessions.items()}
    ranges_by_date = {d: (s["range"] if s else 0.0)
                      for d, s in stats_by_date.items()}
    width_history = []
    for d in session_dates:
        prev_d = prior_map.get(d)
        if not prev_d:
            continue
        pd = stats_by_date.get(prev_d)
        if pd is None:
            continue
        bars = sessions[d]
        if not bars:
            continue
        prev_d2 = prior_map.get(prev_d)
        pp = stats_by_date.get(prev_d2) if prev_d2 else None
        prior_ranges = [ranges_by_date[x] for x in session_dates
                        if x < prev_d][-10:]
        feats = prev_day_features(pd, pp, prior_ranges)
        if feats is None:
            continue
        cpr = cpr_from(pd["high"], pd["low"], pd["close"])
        piv = pivots_from(pd["high"], pd["low"], cpr["pp"])
        width_history.append(cpr["width_pct"])
        pctile = None
        if len(width_history) >= 11:
            hist = width_history[-21:-1]
            pctile = 100.0 * sum(1 for x in hist if x < cpr["width_pct"]) / len(hist)
        today_open = bars[0]["o"]
        gap = gap_features(today_open, pd["close"], pd["high"], pd["low"],
                           cpr["lower_cpr"], cpr["upper_cpr"])
        atr = atr_proxy(sessions.get(prev_d, []))
        ctx = {
            "session_date": d, "instrument": None,
            "prev_date": prev_d, "prev_date2": prev_d2,
            "today_open": today_open,
            "today_first_bar": bars[0]["hhmm"],
            "bars": bars,
            "cpr": cpr, "pivots": piv,
            "cpr_class": cpr_class(cpr["width_pct"]),
            "cpr_width_pctile": pctile,
            "prev_atr5m": atr,
            **feats, **gap,
        }
        contexts[d] = ctx
    return contexts
