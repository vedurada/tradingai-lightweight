"""Direction models A-F (spec.md §3).

Each model returns exactly one of BULLISH / BEARISH / NO TRADE per session
with a reason code. A signal is emitted only at a bar close; the entry is the
open of the NEXT bar.
"""
from datetime import timedelta

from . import features as F

BULL, BEAR, NO_TRADE = "BULLISH", "BEARISH", "NO_TRADE"

# closed taxonomy of NO TRADE reasons
REASONS = {
    "INCOMPLETE_SESSION", "STALE_PREV_SESSION", "NO_PREV_SESSION",
    "PREV_DAY_NEUTRAL", "NO_CPR_BREAK", "DIRECTION_DISAGREEMENT",
    "NO_CPR_CONFIRMATION", "NO_BREAK", "RETEST_FAILED", "RETEST_TIMEOUT",
    "ENTRY_WINDOW", "NO_ENTRY_BAR", "VWAP_CONFLICT", "NO_SIGNAL",
    "NO_SETUP_MATCH",
}

# closed taxonomy of successful-signal reasons
SIGNAL_REASONS = {"PREV_DAY_SIGNAL", "CPR_BREAK", "CPR_CONFIRMED",
                  "OR_BREAKOUT_CONFIRMED", "OR_RETEST_HOLD"}

MODEL_DEFAULTS = {
    "A": {"th": 0.70},
    "B": {"accept2": False},
    "C": {"th": 0.70, "accept2": False},
    "D": {"th": 0.70, "accept2": False, "setup_types": ["CONTINUATION"]},
    "E": {"levels": ["OR15"], "retest": False, "retest_band": 0.0010,
          "max_delay_bars": 24},
    "F": {"th": 0.70, "accept2": True, "vwap": True},
}

# Model E level sets -> (bullish level, bearish level) resolved per session
E_LEVEL_SETS = {
    "OR15": ("or_high", "or_low"),
    "PDH": ("pd_high", "pd_low"),
    "CPR": ("upper_cpr", "lower_cpr"),
    "CPR_PDH": ("upper_cpr", "pd_low"),
}


def _sig(ctx, model, direction, idx, reason, level=None, setup_type=None,
         invalidation=None, extra=None):
    bars = ctx["bars"]
    entry_idx = idx + 1 if idx is not None else None
    entry_ref = None
    if entry_idx is not None and entry_idx < len(bars):
        entry_ref = bars[entry_idx]["o"]
    signal_ts = None
    if idx is not None:
        signal_ts = bars[idx]["ts"] + timedelta(minutes=5)
    out = {
        "session_date": ctx["session_date"], "model": model,
        "direction": direction, "reason": reason,
        "signal_bar_idx": idx, "signal_ts": signal_ts.isoformat() if signal_ts else None,
        "signal_hhmm": bars[idx]["hhmm"] if idx is not None else None,
        "entry_bar_idx": entry_idx if (entry_idx is not None and entry_idx < len(bars)) else None,
        "entry_ref_open": entry_ref,
        "level": level, "setup_type": setup_type,
        "invalidation": invalidation,
    }
    if extra:
        out.update(extra)
    return out


def prev_day_direction(ctx, th):
    """Model A direction from previous-day price action only."""
    cl = ctx["pd_close_location"]
    bullish = cl >= th and ctx["pd_higher_low"]
    bearish = cl <= (1.0 - th) and not ctx["pd_higher_high"]
    if bullish and not bearish:
        return BULL
    if bearish and not bullish:
        return BEAR
    return NO_TRADE


def _closed_beyond(bars, i, level, side):
    c = bars[i]["c"]
    return c > level if side == "up" else c < level


def _cpr_accept(bars, i, level, side, accept2):
    """Confirm a CPR break that happened on bar i.

    accept2 = False -> the break bar itself is the signal bar.
    accept2 = True  -> the NEXT bar must close beyond the level as well;
                        a close back inside invalidates this attempt.
    Returns (signal_idx, level); signal_idx is None when not confirmed.
    """
    if not accept2:
        return i, level
    if i + 1 < len(bars) and _closed_beyond(bars, i + 1, level, side):
        return i + 1, level
    return None, level


def _e_levels(ctx, level_set):
    """Resolve the bullish/bearish trigger levels of an E level set."""
    bull_key, bear_key = E_LEVEL_SETS[level_set]
    orr = F.opening_range(ctx["bars"], 3)

    def resolve(key):
        if key in ("or_high", "or_low"):
            return orr[key] if orr else None
        if key in ("upper_cpr", "lower_cpr"):
            return ctx["cpr"][key]
        return ctx.get(key)

    return resolve(bull_key), resolve(bear_key)


def _or_completed_index(ctx, n_bars=3):
    for i, b in enumerate(ctx["bars"]):
        if b["hhmm"] == "09:15":
            if i + n_bars - 1 < len(ctx["bars"]):
                return i + n_bars - 1
            return None
    return None


def model_a(ctx, cfg):
    d = prev_day_direction(ctx, cfg.get("th", 0.70))
    idx = _or_completed_index(ctx, 3)
    if idx is None:
        return _sig(ctx, "A", NO_TRADE, None, "NO_ENTRY_BAR")
    if d == NO_TRADE:
        return _sig(ctx, "A", NO_TRADE, idx, "PREV_DAY_NEUTRAL")
    return _sig(ctx, "A", d, idx, "PREV_DAY_SIGNAL", level="PREV_DAY",
                invalidation=ctx["pd_low"] if d == BULL else ctx["pd_high"])


def model_b(ctx, cfg):
    """First CPR break of the session, scanned chronologically.

    The earliest break wins regardless of side; a bar can only break one side.
    """
    bars = ctx["bars"]
    start = (_or_completed_index(ctx, 3) or 0) + 1
    up_lvl = ctx["cpr"]["upper_cpr"]
    dn_lvl = ctx["cpr"]["lower_cpr"]
    i = start
    while i < len(bars):
        side = None
        level = None
        if _closed_beyond(bars, i, up_lvl, "up"):
            side, level = "up", up_lvl
        elif _closed_beyond(bars, i, dn_lvl, "down"):
            side, level = "down", dn_lvl
        if side is not None:
            idx, lvl = _cpr_accept(bars, i, level, side,
                                    cfg.get("accept2", False))
            if idx is not None:
                d = BULL if side == "up" else BEAR
                return _sig(ctx, "B", d, idx, "CPR_BREAK", level=lvl,
                            invalidation=lvl)
        i += 1
    return _sig(ctx, "B", NO_TRADE, None, "NO_CPR_BREAK")


def model_c(ctx, cfg):
    pd_dir = prev_day_direction(ctx, cfg.get("th", 0.70))
    if pd_dir == NO_TRADE:
        idx = _or_completed_index(ctx, 3)
        return _sig(ctx, "C", NO_TRADE, idx, "PREV_DAY_NEUTRAL")
    side = "up" if pd_dir == BULL else "down"
    other = "down" if side == "up" else "up"
    bars = ctx["bars"]
    start = (_or_completed_index(ctx, 3) or 0) + 1
    # walk forward: first close beyond the FAR boundary is the confirmation,
    # but a close beyond the NEAR boundary first = failure of "holds CPR".
    far = ctx["cpr"]["upper_cpr"] if side == "up" else ctx["cpr"]["lower_cpr"]
    near = ctx["cpr"]["lower_cpr"] if side == "up" else ctx["cpr"]["upper_cpr"]
    i = start
    while i < len(bars):
        if _closed_beyond(bars, i, near, other):
            return _sig(ctx, "C", NO_TRADE, i, "NO_CPR_CONFIRMATION",
                        level=far)
        if _closed_beyond(bars, i, far, side):
            if cfg.get("accept2", False) and not (
                    i + 1 < len(bars) and _closed_beyond(bars, i + 1, far, side)):
                i += 1
                continue
            idx = i + 1 if cfg.get("accept2", False) else i
            if idx >= len(bars):
                return _sig(ctx, "C", NO_TRADE, None, "NO_ENTRY_BAR")
            return _sig(ctx, "C", pd_dir, idx, "CPR_CONFIRMED", level=far,
                        invalidation=near)
        i += 1
    return _sig(ctx, "C", NO_TRADE, None, "NO_CPR_BREAK")


def _setup_type(ctx, direction):
    """CONTINUATION vs REVERSAL classification (spec §3 Model D)."""
    gap_up = ctx["gap_dir"] == "UP"
    gap_down = ctx["gap_dir"] == "DOWN"
    if direction == BULL:
        cont = gap_up and ctx["cpr_pos"] == "ABOVE_CPR"
        rev = gap_down
    else:
        cont = gap_down and ctx["cpr_pos"] == "BELOW_CPR"
        rev = gap_up
    if cont:
        return "CONTINUATION"
    if rev:
        return "REVERSAL"
    return "UNCLASSIFIED"


def model_d(ctx, cfg):
    """Model C plus the gap/continuation-reversal classification."""
    sig = model_c(ctx, cfg)
    if sig["direction"] == NO_TRADE:
        sig["model"] = "D"
        return sig
    st = _setup_type(ctx, sig["direction"])
    allowed = cfg.get("setup_types", ["CONTINUATION"])
    sig["model"] = "D"
    sig["setup_type"] = st
    if st not in allowed:
        sig["direction"] = NO_TRADE
        sig["reason"] = "NO_SETUP_MATCH"
        sig["setup_type"] = st
    return sig


def _vwap_ok(ctx, idx, direction):
    series = F.vwap_proxy_series(ctx["bars"][:idx + 1])
    v = series[-1]
    c = ctx["bars"][idx]["c"]
    if direction == BULL:
        return c >= v
    return c <= v


def model_e(ctx, cfg):
    """Opening-range breakout / retest, scanned chronologically.

    The earliest breakout attempt wins; an attempt that fails (no follow
    through, failed retest) is discarded and the scan continues.
    """
    bars = ctx["bars"]
    or_idx = _or_completed_index(ctx, 3)
    if or_idx is None:
        return _sig(ctx, "E", NO_TRADE, None, "NO_ENTRY_BAR")
    level_set = cfg.get("levels", ["OR15"])[0]
    bull_lvl, bear_lvl = _e_levels(ctx, level_set)
    if bull_lvl is None or bear_lvl is None:
        return _sig(ctx, "E", NO_TRADE, None, "NO_ENTRY_BAR")
    retest = cfg.get("retest", False)
    band = cfg.get("retest_band", 0.0010)
    max_delay = cfg.get("max_delay_bars", 24)
    counters = {"rejected_failed_break": 0, "rejected_retest_failed": 0,
                "rejected_retest_timeout": 0, "rejected_entry_window": 0}
    i = or_idx + 1
    while i < len(bars):
        if bars[i]["hhmm"] > "14:45":
            counters["rejected_entry_window"] += 1
            break
        side, level = None, None
        if _closed_beyond(bars, i, bull_lvl, "up"):
            side, level = "up", bull_lvl
        elif _closed_beyond(bars, i, bear_lvl, "down"):
            side, level = "down", bear_lvl
        if side is None:
            i += 1
            continue
        if not retest:
            if i + 1 >= len(bars) or bars[i + 1]["hhmm"] > "14:45":
                counters["rejected_entry_window"] += 1
                break
            if _closed_beyond(bars, i + 1, level, side):
                d = BULL if side == "up" else BEAR
                s = _sig(ctx, "E", d, i + 1, "OR_BREAKOUT_CONFIRMED",
                         level=level, invalidation=level)
                s["counters"] = counters
                return s
            counters["rejected_failed_break"] += 1
            i += 1
            continue
        # retest variant: after the break the level must hold (close) and be
        # touched (wick within band) before the entry window closes
        j = i + 1
        ok = False
        while j < len(bars) and (j - i) <= max_delay:
            if bars[j]["hhmm"] > "14:45":
                counters["rejected_entry_window"] += 1
                break
            if not _closed_beyond(bars, j, level, side):
                counters["rejected_retest_failed"] += 1
                break
            touched = ((bars[j]["l"] <= level * (1 + band)) if side == "up"
                       else (bars[j]["h"] >= level * (1 - band)))
            if touched:
                ok = True
                break
            j += 1
        if ok:
            d = BULL if side == "up" else BEAR
            s = _sig(ctx, "E", d, j, "OR_RETEST_HOLD", level=level,
                     invalidation=level)
            s["counters"] = counters
            return s
        if j - i > max_delay:
            counters["rejected_retest_timeout"] += 1
        i = max(j, i + 1)
    s = _sig(ctx, "E", NO_TRADE, None, "NO_BREAK")
    s["counters"] = counters
    return s


def model_f(ctx, cfg):
    """Model C (2-close acceptance) + equal-weight VWAP proxy filter."""
    sig = model_c(ctx, cfg)
    sig["model"] = "F"
    if sig["direction"] == NO_TRADE:
        return sig
    idx = sig["signal_bar_idx"]
    if idx is None:
        sig["direction"] = NO_TRADE
        sig["reason"] = "NO_ENTRY_BAR"
        return sig
    if not _vwap_ok(ctx, idx, sig["direction"]):
        sig["direction"] = NO_TRADE
        sig["reason"] = "VWAP_CONFLICT"
    return sig


MODELS = {"A": model_a, "B": model_b, "C": model_c, "D": model_d,
          "E": model_e, "F": model_f}


def run_model(ctx, model, cfg):
    c = dict(MODEL_DEFAULTS.get(model, {}))
    c.update(cfg or {})
    sig = MODELS[model](ctx, c)
    sig["config"] = c
    if sig["direction"] == NO_TRADE:
        if sig["reason"] not in REASONS:
            raise AssertionError("unknown NO TRADE reason %s" % sig["reason"])
    else:
        if sig["reason"] not in SIGNAL_REASONS:
            raise AssertionError("unknown signal reason %s" % sig["reason"])
    return sig
