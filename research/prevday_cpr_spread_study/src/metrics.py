"""Metrics and session-level uncertainty (spec.md §7)."""
import math
import random
from collections import Counter, defaultdict


def wilson_ci(wins, n, z=1.96):
    if not n:
        return (None, None, None)
    p = wins / float(n)
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (p, max(0.0, centre - half), min(1.0, centre + half))


def max_drawdown(series):
    """series: list of (label, value). Returns (max_dd, dd_len, peak_label, trough_label)."""
    peak = None
    peak_lab = None
    max_dd = 0.0
    dd_len = 0
    best = (0.0, 0, None, None)
    cur_len = 0
    for lab, val in series:
        if peak is None or val > peak:
            peak = val
            peak_lab = lab
            cur_len = 0
        else:
            cur_len += 1
        dd = val - peak
        if dd < max_dd:
            max_dd = dd
            best = (dd, cur_len, peak_lab, lab)
    return (abs(best[0]), best[1], best[2], best[3])


def _mean(xs):
    return sum(xs) / float(len(xs)) if xs else 0.0


def _median(xs):
    if not xs:
        return 0.0
    s = sorted(xs)
    n = len(s)
    m = n // 2
    return s[m] if n % 2 else (s[m - 1] + s[m]) / 2.0


def block_bootstrap(daily_rows, n_boot=4000, block=5, seed=20261022):
    """Session-level block bootstrap.

    daily_rows: list of (session_date, n_trades, sum_r)
    Returns dict with mean R per trade, CI and one-sided p-value.
    """
    rows = [r for r in daily_rows if r[1] > 0]
    if len(rows) < 2:
        return {"mean_r": None, "ci_low": None, "ci_high": None,
                "p_value": None, "n_sessions": len(rows), "n_boot": 0}
    rng = random.Random(seed)
    n = len(rows)
    means = []
    nblocks = int(math.ceil(n / float(block)))
    for _ in range(n_boot):
        picked = []
        for _ in range(nblocks):
            start = rng.randrange(0, max(1, n - block + 1)) if n > block else 0
            picked.extend(rows[start:start + block] if n > block else rows[:])
        picked = picked[:n] if n > block else picked
        tot_r = sum(r[2] for r in picked)
        tot_n = sum(r[1] for r in picked)
        means.append(tot_r / tot_n if tot_n else 0.0)
    means.sort()
    lo = means[int(0.025 * (len(means) - 1))]
    hi = means[int(0.975 * (len(means) - 1))]
    obs = sum(r[2] for r in rows) / float(sum(r[1] for r in rows))
    p = sum(1 for m in means if m <= 0) / float(len(means))
    return {"mean_r": obs, "ci_low": lo, "ci_high": hi, "p_value": p,
            "n_sessions": n, "n_boot": n_boot,
            "boot_mean": _mean(means)}


def summarize(trades, cost_r=0.0, sessions=None, capital_ref=200000.0,
              daily_loss_limit_r=3.0):
    """Full metric block for a set of trades."""
    if not trades:
        return {"n_trades": 0}
    rs = [t["r"] - cost_r for t in trades]
    pts = [t["points"] for t in trades]
    wins = [t for t, r in zip(trades, rs) if r > 0]
    losses = [t for t, r in zip(trades, rs) if r < 0]
    gp = sum(r for r in rs if r > 0)
    gl = abs(sum(r for r in rs if r < 0))
    wr, wr_lo, wr_hi = wilson_ci(len(wins), len(rs))
    by_day = defaultdict(list)
    for t, r in zip(trades, rs):
        by_day[t["session_date"]].append(r)
    curve = []
    cum = 0.0
    for d in sorted(by_day):
        cum += sum(by_day[d])
        curve.append((d, cum))
    mdd, mdd_len, mdd_peak, mdd_trough = max_drawdown(curve)
    # max consecutive losses (chronological)
    chron = sorted(trades, key=lambda t: (t["session_date"], t["entry_ts"] or ""))
    streak = 0
    max_streak = 0
    for t, r in zip(chron, rs):
        if r < 0:
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 0
    daily_rows = [(d, len(v), sum(v)) for d, v in sorted(by_day.items())]
    breaches = sum(1 for d, v in by_day.items() if sum(v) <= -daily_loss_limit_r)
    mfe = [t["mfe_r"] for t in trades]
    mae = [t["mae_r"] for t in trades]
    best = max(rs)
    total = sum(rs)
    excl_best = (total - best) / float(len(rs) - 1) if len(rs) > 1 else None
    return {
        "n_trades": len(rs),
        "win_rate": wr, "win_rate_ci_lo": wr_lo, "win_rate_ci_hi": wr_hi,
        "n_win": len(wins), "n_loss": len(losses),
        "bull_trades": sum(1 for t in trades if t["direction"] == "BULLISH"),
        "bear_trades": sum(1 for t in trades if t["direction"] == "BEARISH"),
        "total_r": total, "total_points": sum(pts),
        "avg_r": _mean(rs), "median_r": _median(rs),
        "avg_points": _mean(pts), "median_points": _median(pts),
        "avg_win_r": _mean([r for r in rs if r > 0]),
        "avg_loss_r": _mean([r for r in rs if r < 0]),
        "profit_factor": (gp / gl) if gl > 0 else None,
        "expectancy_r": _mean(rs), "expectancy_points": _mean(pts),
        "max_dd_r": mdd, "max_dd_len_sessions": mdd_len,
        "max_dd_peak": mdd_peak, "max_dd_trough": mdd_trough,
        "max_consecutive_losses": max_streak,
        "worst_trade_r": min(rs),
        "stop_hit_rate": sum(1 for t in trades if t["exit_reason"] in
                             ("STOP", "STOP_GAP")) / float(len(trades)),
        "target_hit_rate": sum(1 for t in trades if t["exit_reason"] ==
                               "TARGET") / float(len(trades)),
        "time_exit_rate": sum(1 for t in trades if t["exit_reason"] in
                              ("TIME_EXIT", "EOD_LAST_CLOSE")) / float(len(trades)),
        "gap_fill_count": sum(1 for t in trades if t["gap_fill"]),
        "missing_exit_bar_count": sum(1 for t in trades if t["missing_exit_bar"]),
        "avg_mfe_r": _mean(mfe), "avg_mae_r": _mean(mae),
        "avg_hold_bars": _mean([t["hold_bars"] for t in trades]),
        "avg_hold_minutes": _mean([t["hold_minutes"] for t in trades]),
        "median_hold_minutes": _median([t["hold_minutes"] for t in trades]),
        "daily_loss_breaches": breaches,
        "best_trade_r": best,
        "best_trade_share_of_profit": (best / total) if total > 0 else None,
        "avg_r_excl_best": excl_best,
        "cost_r": cost_r,
    }


def breakdown(trades, key, cost_r=0.0):
    groups = defaultdict(list)
    for t in trades:
        groups[t.get(key)].append(t)
    out = {}
    for k, v in sorted(groups.items(), key=lambda kv: str(kv[0])):
        s = summarize(v, cost_r=cost_r)
        out[str(k)] = {kk: s.get(kk) for kk in
                       ("n_trades", "win_rate", "total_r", "avg_r",
                        "profit_factor", "max_dd_r", "expectancy_r")}
    return out


def no_trade_reasons(sigs):
    c = Counter(s["reason"] for s in sigs if s["direction"] == "NO_TRADE")
    return dict(c)
