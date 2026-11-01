"""Isolated research: NIFTY 50 previous-day price action and continuous intraday setups."""
import csv
import os
import sqlite3
from datetime import datetime
from collections import defaultdict, OrderedDict
import zoneinfo

BASE = "/opt/tradingai"
DB_PATH = os.path.join(BASE, "database", "tradingai.db")
OUT_DIR = os.path.dirname(os.path.abspath(__file__))
IST = zoneinfo.ZoneInfo("Asia/Kolkata")

BULL_THRESHOLD_PCT = 0.30
BEAR_THRESHOLD_PCT = -0.30
GAP_SMALL_PCT = 0.25
GAP_LARGE_PCT = 0.75
LEVEL_TOL_PCT = 0.0015
STOP_PCT = 0.005
TARGET_PCT = 0.02
PARTIAL_MIN_CANDLES = 75


def load_candles():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT timestamp, open, high, low, close FROM market_candles_5m "
        "WHERE instrument_id='NIFTY' ORDER BY timestamp"
    ).fetchall()
    conn.close()
    out = []
    for r in rows:
        ts = r["timestamp"]
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=IST)
        out.append({
            "timestamp": ts, "dt": dt, "date": ts[:10], "time": ts[11:16],
            "open": float(r["open"]), "high": float(r["high"]),
            "low": float(r["low"]), "close": float(r["close"]),
        })
    return out


def group_sessions(candles):
    sessions = OrderedDict()
    for c in candles:
        sessions.setdefault(c["date"], []).append(c)
    return sessions


def classify_prev_direction(prev):
    if prev is None:
        return "UNKNOWN"
    oc = (prev["close"] - prev["open"]) / prev["open"] * 100.0
    if oc >= BULL_THRESHOLD_PCT:
        return "BULLISH"
    if oc <= BEAR_THRESHOLD_PCT:
        return "BEARISH"
    return "SIDEWAYS"


def cpr_levels(prev):
    try:
        from app.research.cpr_strategy_engine import calculate_cpr, pivot_levels
        cpr = calculate_cpr(prev["high"], prev["low"], prev["close"])
        piv = pivot_levels(prev["high"], prev["low"], cpr["pp"])
        return {"pp": cpr["pp"], "bc": cpr["bc"], "tc": cpr["tc"],
                "r1": piv["r1"], "r2": piv["r2"], "s1": piv["s1"], "s2": piv["s2"]}
    except Exception:
        return None


def prev_context(prev_candles):
    if not prev_candles:
        return None
    o = prev_candles[0]["open"]
    h = max(c["high"] for c in prev_candles)
    l = min(c["low"] for c in prev_candles)
    cl = prev_candles[-1]["close"]
    ctx = {"date": prev_candles[0]["date"], "open": o, "high": h, "low": l,
           "close": cl, "range": h - l, "mid": (h + l) / 2.0,
           "direction": classify_prev_direction({"open": o, "close": cl}),
           "cpr": cpr_levels({"high": h, "low": l, "close": cl})}
    return ctx


def gap_category(cur_open, prev_close):
    if prev_close == 0:
        return "UNKNOWN"
    gap_pct = (cur_open - prev_close) / prev_close * 100.0
    if gap_pct >= GAP_LARGE_PCT:
        return "LARGE_UP"
    if gap_pct >= GAP_SMALL_PCT:
        return "SMALL_UP"
    if gap_pct <= -GAP_LARGE_PCT:
        return "LARGE_DOWN"
    if gap_pct <= -GAP_SMALL_PCT:
        return "SMALL_DOWN"
    return "FLAT"


def level_tolerance(level):
    return max(abs(level) * LEVEL_TOL_PCT, 1.0)


def near(price, level):
    return abs(price - level) <= level_tolerance(level)


def opening_location(price, ctx):
    if ctx is None:
        return "UNKNOWN"
    pdh, pdl, pdc, mid = ctx["high"], ctx["low"], ctx["close"], ctx["mid"]
    if price > pdh:
        base = "ABOVE_PDH"
    elif near(price, pdh):
        base = "NEAR_PDH"
    elif price < pdl:
        base = "BELOW_PDL"
    elif near(price, pdl):
        base = "NEAR_PDL"
    elif near(price, pdc):
        base = "NEAR_PDC"
    else:
        base = "INSIDE_RANGE"
    cpr = ctx["cpr"]
    if cpr is not None:
        if price > cpr["tc"]:
            base += "_ABOVE_TC"
        elif price < cpr["bc"]:
            base += "_BELOW_BC"
        elif cpr["bc"] <= price <= cpr["tc"]:
            base += "_INSIDE_CPR"
    return base


def first15_direction(session_candles):
    first3 = session_candles[:3]
    if len(first3) < 3:
        return "INCOMPLETE"
    closes = [c["close"] for c in first3]
    if closes[-1] > closes[0]:
        return "BULLISH"
    if closes[-1] < closes[0]:
        return "BEARISH"
    return "NEUTRAL"


def evaluate_setup(cur, history, prev_ctx, trade_open):
    if trade_open:
        return {"setup": "NO_TRADE", "trigger": "OPEN_POSITION", "reason": "one_open_trade_at_a_time", "level": None}
    if prev_ctx is None:
        return {"setup": "INVALID_DATA", "trigger": "NO_PREV_SESSION", "reason": "missing_previous_session", "level": None}
    if len(history) < 1:
        return {"setup": "INVALID_DATA", "trigger": "NO_HISTORY", "reason": "no_completed_candles", "level": None}

    pdh = prev_ctx["high"]
    pdl = prev_ctx["low"]
    mid = prev_ctx["mid"]
    cpr = prev_ctx["cpr"]

    orh = max(c["high"] for c in history[:3]) if len(history) >= 3 else None
    orl = min(c["low"] for c in history[:3]) if len(history) >= 3 else None

    prev_close = history[-2]["close"] if len(history) >= 2 else None
    cur_close = cur["close"]
    cur_open = cur["open"]
    cur_high = cur["high"]
    cur_low = cur["low"]

    triggers = []

    supports = [pdl, mid]
    if cpr is not None:
        supports.append(cpr["bc"])
    if orl is not None:
        supports.append(orl)
    for lvl in supports:
        if cur_low <= lvl + level_tolerance(lvl) and cur_close > lvl and cur_close > cur_open:
            triggers.append(("BULLISH_SETUP", "SUPPORT_BOUNCE", "close above support %.2f" % lvl, lvl))
            break

    resistances = [pdh, mid]
    if cpr is not None:
        resistances.append(cpr["tc"])
    if orh is not None:
        resistances.append(orh)
    for lvl in resistances:
        if cur_high >= lvl - level_tolerance(lvl) and cur_close < lvl and cur_close < cur_open:
            triggers.append(("BEARISH_SETUP", "RESISTANCE_REJECTION", "close below resistance %.2f" % lvl, lvl))
            break

    for lvl in [pdh, orh]:
        if lvl is not None and prev_close is not None and prev_close <= lvl and cur_close > lvl:
            triggers.append(("BULLISH_SETUP", "BREAKOUT", "close above %.2f" % lvl, lvl))
            break

    for lvl in [pdl, orl]:
        if lvl is not None and prev_close is not None and prev_close >= lvl and cur_close < lvl:
            triggers.append(("BEARISH_SETUP", "BREAKDOWN", "close below %.2f" % lvl, lvl))
            break

    for lvl in [pdh, orh]:
        if lvl is not None and prev_close is not None and prev_close > lvl and cur_close < lvl:
            triggers.append(("BEARISH_SETUP", "FAILED_BREAKOUT", "failed breakout at %.2f" % lvl, lvl))
            break

    for lvl in [pdl, orl]:
        if lvl is not None and prev_close is not None and prev_close < lvl and cur_close > lvl:
            triggers.append(("BULLISH_SETUP", "FAILED_BREAKDOWN", "failed breakdown at %.2f" % lvl, lvl))
            break

    if not triggers:
        return {"setup": "NO_TRADE", "trigger": "NONE", "reason": "no_confirmed_setup", "level": None}

    bull = [t for t in triggers if t[0] == "BULLISH_SETUP"]
    bear = [t for t in triggers if t[0] == "BEARISH_SETUP"]
    if bull and bear:
        return {"setup": "NO_TRADE", "trigger": "CONFLICT", "reason": "conflicting_bull_bear_triggers", "level": None}
    t = triggers[0]
    return {"setup": t[0], "trigger": t[1], "reason": t[2], "level": t[3]}


def eod_exit_price(candles):
    for c in candles:
        if c["time"] == "15:20":
            return c["open"], c["timestamp"]
    for c in candles:
        if c["time"] == "15:15":
            return c["close"], c["timestamp"]
    return candles[-1]["close"], candles[-1]["timestamp"]


def simulate_trades(sessions, session_contexts, exit_mode='eod'):
    trades = []
    all_setups = []

    for d, candles in sessions.items():
        if len(candles) < PARTIAL_MIN_CANDLES:
            continue
        prev_ctx = session_contexts[d]
        if prev_ctx is None:
            continue
        first15 = first15_direction(candles)
        gap = gap_category(candles[0]["open"], prev_ctx["close"])
        open_loc = opening_location(candles[0]["open"], prev_ctx)

        # First pass: all qualifying setups (trade_open ignored)
        for i, c in enumerate(candles):
            history = candles[:i + 1]
            res = evaluate_setup(c, history, prev_ctx, False)
            if res["setup"] in ("BULLISH_SETUP", "BEARISH_SETUP"):
                all_setups.append({
                    "session": d, "signal_time": c["timestamp"],
                    "prev_direction": prev_ctx["direction"],
                    "gap_category": gap, "opening_location": open_loc,
                    "first15_direction": first15, "setup": res["setup"],
                    "trigger": res["trigger"], "reason": res["reason"],
                    "level": res.get("level"),
                    "entry_time": candles[i + 1]["timestamp"] if i + 1 < len(candles) else None,
                })

        # Second pass: stateful execution
        i = 0
        n = len(candles)
        while i < n:
            c = candles[i]
            history = candles[:i + 1]
            res = evaluate_setup(c, history, prev_ctx, False)
            if res["setup"] in ("BULLISH_SETUP", "BEARISH_SETUP") and i + 1 < n:
                entry_candle = candles[i + 1]
                entry_price = entry_candle["open"]
                direction = "BULL" if res["setup"] == "BULLISH_SETUP" else "BEAR"
                if direction == "BULL":
                    stop = entry_price * (1 - STOP_PCT)
                    target = entry_price * (1 + TARGET_PCT)
                else:
                    stop = entry_price * (1 + STOP_PCT)
                    target = entry_price * (1 - TARGET_PCT)

                exit_price = None
                exit_time = None
                exit_reason = None
                mfe = 0.0
                mae = 0.0
                # levels for rejection exit
                pdh = prev_ctx["high"]
                pdl = prev_ctx["low"]
                mid = prev_ctx["mid"]
                cpr = prev_ctx["cpr"]
                orh = max(x["high"] for x in candles[:3]) if len(candles) >= 3 else None
                orl = min(x["low"] for x in candles[:3]) if len(candles) >= 3 else None
                resistances = [x for x in [pdh, mid, (cpr["tc"] if cpr else None), orh] if x is not None]
                supports = [x for x in [pdl, mid, (cpr["bc"] if cpr else None), orl] if x is not None]

                j = i + 1
                while j < n:
                    cc = candles[j]
                    if direction == "BULL":
                        mfe = max(mfe, cc["high"] - entry_price)
                        mae = max(mae, entry_price - cc["low"])
                    else:
                        mfe = max(mfe, entry_price - cc["low"])
                        mae = max(mae, cc["high"] - entry_price)
                    hit_stop = False
                    hit_target = False
                    if direction == "BULL":
                        if cc["low"] <= stop:
                            hit_stop = True
                        if cc["high"] >= target:
                            hit_target = True
                    else:
                        if cc["high"] >= stop:
                            hit_stop = True
                        if cc["low"] <= target:
                            hit_target = True
                    if hit_stop:
                        exit_price = stop
                        exit_time = cc["timestamp"]
                        exit_reason = "STOP"
                        break
                    if hit_target:
                        exit_price = target
                        exit_time = cc["timestamp"]
                        exit_reason = "TARGET"
                        break
                    if exit_mode == "rejection" and j > i + 1:
                        rej = False
                        for lvl in resistances + supports:
                            tol = level_tolerance(lvl)
                            if (cc["high"] >= lvl - tol and cc["close"] < lvl and cc["close"] < cc["open"]) or                                (cc["low"] <= lvl + tol and cc["close"] < lvl and cc["close"] < cc["open"]):
                                rej = True
                                break
                        if rej:
                            exit_price = cc["close"]
                            exit_time = cc["timestamp"]
                            exit_reason = "REJ_EXIT"
                            break
                    j += 1

                if exit_price is None:
                    exit_price, exit_time = eod_exit_price(candles)
                    exit_reason = "EOD"

                risk = abs(entry_price - stop)
                if direction == "BULL":
                    points = exit_price - entry_price
                else:
                    points = entry_price - exit_price
                r_mult = points / risk if risk else 0.0
                try:
                    t0 = datetime.fromisoformat(entry_candle["timestamp"])
                    t1 = datetime.fromisoformat(exit_time)
                    holding_min = (t1 - t0).total_seconds() / 60.0
                except Exception:
                    holding_min = None

                trades.append({
                    "session": d, "direction": direction, "setup": res["setup"],
                    "trigger": res["trigger"], "signal_time": c["timestamp"],
                    "entry_time": entry_candle["timestamp"],
                    "entry_price": round(entry_price, 2), "stop": round(stop, 2),
                    "target": round(target, 2), "exit_time": exit_time,
                    "exit_price": round(exit_price, 2), "exit_reason": exit_reason,
                    "points": round(points, 2), "r_multiple": round(r_mult, 3),
                    "mfe_points": round(mfe, 2), "mae_points": round(mae, 2),
                    "holding_minutes": round(holding_min, 1) if holding_min is not None else None,
                    "prev_direction": prev_ctx["direction"],
                    "gap_category": gap, "opening_location": open_loc,
                    "first15_direction": first15,
                    "setup_level": res.get("level"),
                })

                # resume after exit candle
                exit_idx = next((k for k in range(i + 1, n) if candles[k]["timestamp"] == exit_time), n - 1)
                i = n
                continue
            i += 1

    # Build signal log with trade-open flags
    trade_intervals = []
    for t in trades:
        trade_intervals.append((t["session"], t["entry_time"], t["exit_time"]))

    signal_log = []
    for d, candles in sessions.items():
        if len(candles) < PARTIAL_MIN_CANDLES:
            for c in candles:
                signal_log.append({
                    "session": d, "timestamp": c["timestamp"], "prev_direction": None,
                    "gap_category": None, "opening_location": None, "first15_direction": None,
                    "setup": "INVALID_DATA", "trigger": "PARTIAL_SESSION",
                    "reason": "partial_session_excluded", "entry_eligible": False,
                    "trade_open": False,
                })
            continue
        prev_ctx = session_contexts[d]
        first15 = first15_direction(candles)
        gap = gap_category(candles[0]["open"], prev_ctx["close"]) if prev_ctx else "UNKNOWN"
        open_loc = opening_location(candles[0]["open"], prev_ctx) if prev_ctx else "UNKNOWN"
        for i, c in enumerate(candles):
            history = candles[:i + 1]
            res = evaluate_setup(c, history, prev_ctx, False)
            # trade_open if timestamp within any trade interval for this session
            to = False
            for (s, et, xt) in trade_intervals:
                if s == d and et <= c["timestamp"] <= xt:
                    to = True
                    break
            entry_eligible = (res["setup"] in ("BULLISH_SETUP", "BEARISH_SETUP")) and (not to)
            signal_log.append({
                "session": d, "timestamp": c["timestamp"],
                "prev_direction": prev_ctx["direction"] if prev_ctx else None,
                "gap_category": gap, "opening_location": open_loc,
                "first15_direction": first15, "setup": res["setup"],
                "trigger": res["trigger"], "reason": res["reason"],
                "entry_eligible": entry_eligible, "trade_open": to,
            })

    return signal_log, all_setups, trades


def write_csv(name, rows, fieldnames):
    path = os.path.join(OUT_DIR, name)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    return path


def main():
    candles = load_candles()
    sessions = group_sessions(candles)

    session_contexts = {}
    session_list = list(sessions.keys())
    for i, d in enumerate(session_list):
        if i == 0:
            session_contexts[d] = None
        else:
            session_contexts[d] = prev_context(sessions[session_list[i - 1]])

    signal_log, all_setups, trades = simulate_trades(sessions, session_contexts)

    write_csv("continuous_signal_log.csv", signal_log, [
        "session", "timestamp", "prev_direction", "gap_category", "opening_location",
        "first15_direction", "setup", "trigger", "reason", "entry_eligible", "trade_open",
    ])
    write_csv("all_qualifying_setups.csv", all_setups, [
        "session", "signal_time", "prev_direction", "gap_category", "opening_location",
        "first15_direction", "setup", "trigger", "reason", "level", "entry_time",
    ])
    write_csv("trade_simulation.csv", trades, [
        "session", "direction", "setup", "trigger", "signal_time", "entry_time",
        "entry_price", "stop", "target", "exit_time", "exit_price", "exit_reason",
        "points", "r_multiple", "mfe_points", "mae_points", "holding_minutes",
        "prev_direction", "gap_category", "opening_location", "first15_direction",
        "setup_level",
    ])

    bucket_order = OrderedDict([
        ("09:15-10:00", None), ("10:00-11:00", None), ("11:00-12:00", None),
        ("12:00-13:00", None), ("13:00-14:00", None), ("14:00-15:00", None),
        ("15:00+", None),
    ])
    bucket_trades = defaultdict(lambda: {"trades": 0, "wins": 0, "points": 0.0, "R": 0.0})
    for t in trades:
        ts = t["entry_time"][11:16]
        if ts < "10:00":
            b = "09:15-10:00"
        elif ts < "11:00":
            b = "10:00-11:00"
        elif ts < "12:00":
            b = "11:00-12:00"
        elif ts < "13:00":
            b = "12:00-13:00"
        elif ts < "14:00":
            b = "13:00-14:00"
        elif ts < "15:00":
            b = "14:00-15:00"
        else:
            b = "15:00+"
        bucket_trades[b]["trades"] += 1
        if t["points"] > 0:
            bucket_trades[b]["wins"] += 1
        bucket_trades[b]["points"] += t["points"]
        bucket_trades[b]["R"] += t["r_multiple"]

    eta_rows = []
    for b in bucket_order:
        d = bucket_trades[b]
        n = d["trades"]
        eta_rows.append({
            "entry_bucket": b, "trades": n, "wins": d["wins"],
            "win_rate_pct": round(100.0 * d["wins"] / n, 1) if n else 0.0,
            "total_points": round(d["points"], 2), "total_R": round(d["R"], 2),
            "avg_R": round(d["R"] / n, 3) if n else 0.0,
        })
    write_csv("entry_time_analysis.csv", eta_rows, [
        "entry_bucket", "trades", "wins", "win_rate_pct", "total_points", "total_R", "avg_R",
    ])

    groups = defaultdict(lambda: {"sessions": set(), "setups": 0, "trades": 0, "wins": 0, "R": 0.0, "points": 0.0})
    for sl in signal_log:
        key = (sl["prev_direction"], sl["gap_category"], sl["opening_location"], sl["first15_direction"])
        groups[key]["sessions"].add(sl["session"])
    for s in all_setups:
        key = (s["prev_direction"], s["gap_category"], s["opening_location"], s["first15_direction"])
        groups[key]["setups"] += 1
    for t in trades:
        key = (t["prev_direction"], t["gap_category"], t["opening_location"], t["first15_direction"])
        groups[key]["trades"] += 1
        if t["points"] > 0:
            groups[key]["wins"] += 1
        groups[key]["R"] += t["r_multiple"]
        groups[key]["points"] += t["points"]

    cm_rows = []
    for key, d in groups.items():
        n = d["trades"]
        cm_rows.append({
            "prev_direction": key[0], "gap_category": key[1],
            "opening_location": key[2], "first15_direction": key[3],
            "sessions": len(d["sessions"]), "setups": d["setups"], "trades": n,
            "wins": d["wins"],
            "win_rate_pct": round(100.0 * d["wins"] / n, 1) if n else 0.0,
            "total_points": round(d["points"], 2), "total_R": round(d["R"], 2),
            "avg_R": round(d["R"] / n, 3) if n else 0.0,
        })
    cm_rows.sort(key=lambda r: (r["sessions"], r["trades"]), reverse=True)
    write_csv("condition_matrix.csv", cm_rows, [
        "prev_direction", "gap_category", "opening_location", "first15_direction",
        "sessions", "setups", "trades", "wins", "win_rate_pct", "total_points", "total_R", "avg_R",
    ])

    sessions_sorted = list(sessions.keys())
    n_sess = len(sessions_sorted)
    cuts = [0, n_sess // 3, 2 * n_sess // 3, n_sess]
    labels = ["train", "validation", "test"]
    wf_rows = []
    for li in range(3):
        block_sessions = set(sessions_sorted[cuts[li]:cuts[li + 1]])
        bt = [t for t in trades if t["session"] in block_sessions]
        n = len(bt)
        wins = sum(1 for t in bt if t["points"] > 0)
        wf_rows.append({
            "period": labels[li],
            "session_start": sessions_sorted[cuts[li]],
            "session_end": sessions_sorted[cuts[li + 1] - 1],
            "sessions": len(block_sessions), "trades": n, "wins": wins,
            "win_rate_pct": round(100.0 * wins / n, 1) if n else 0.0,
            "total_points": round(sum(t["points"] for t in bt), 2),
            "total_R": round(sum(t["r_multiple"] for t in bt), 2),
            "avg_R": round(sum(t["r_multiple"] for t in bt) / n, 3) if n else 0.0,
        })
    write_csv("walk_forward_results.csv", wf_rows, [
        "period", "session_start", "session_end", "sessions", "trades", "wins",
        "win_rate_pct", "total_points", "total_R", "avg_R",
    ])

    total_setups = len(all_setups)
    total_trades = len(trades)
    total_wins = sum(1 for t in trades if t["points"] > 0)
    total_points = sum(t["points"] for t in trades)
    total_R = sum(t["r_multiple"] for t in trades)
    partial_sessions = [d for d, c in sessions.items() if len(c) < PARTIAL_MIN_CANDLES]

    trigger_counts = defaultdict(int)
    for s in all_setups:
        trigger_counts[s["trigger"]] += 1
    with open(os.path.join(OUT_DIR, "pattern_catalog.md"), "w") as f:
        f.write("# Pattern Catalog - NIFTY 50 Previous-Day Price Action (Isolated Research)\n\n")
        f.write("Triggers evaluated on every completed 5-minute candle. Entry at next candle open. EOD exit at 15:20 open (fallback 15:15 close).\n\n")
        f.write("| Trigger | Setups |\n|---|---|\n")
        for k, v in sorted(trigger_counts.items(), key=lambda x: -x[1]):
            f.write("| %s | %d |\n" % (k, v))
        f.write("\nNo-trade outcomes dominate; see continuous_signal_log.csv for per-candle diagnostics.\n")

    with open(os.path.join(OUT_DIR, "research_report.md"), "w") as f:
        f.write("# Research Report - NIFTY 50 Previous-Day Price Action (Continuous Intraday)\n\n")
        f.write("## Scope\n")
        f.write("- Sessions loaded: %d\n" % len(sessions))
        f.write("- Candles loaded: %d\n" % len(candles))
        f.write("- Partial sessions excluded from trade sim: %s\n" % partial_sessions)
        f.write("- Evaluated candles (signal log rows): %d\n" % len(signal_log))
        f.write("- Qualifying setups: %d\n" % total_setups)
        f.write("- Executable trades (one open at a time): %d\n" % total_trades)
        f.write("- Wins: %d (%s%%)\n" % (total_wins, round(100.0 * total_wins / total_trades, 1) if total_trades else 0))
        f.write("- Total points: %s\n" % round(total_points, 2))
        f.write("- Total R: %s\n\n" % round(total_R, 2))
        f.write("## Method\n")
        f.write("Previous-day context frozen at session start. Setups evaluated on every completed 5-minute candle using only data available at that time. Entry at next candle open. EOD exit at 15:20 open (fallback 15:15 close). Stop/target 0.5%/2.0%. One open trade at a time; no re-entry until closed. Partial sessions excluded from trade simulation but retained in signal log as INVALID_DATA.\n\n")
        f.write("## Entry-time distribution\n")
        for r in eta_rows:
            f.write("- %s: trades=%d, wins=%d, win_rate=%s%%, total_R=%s\n" % (
                r["entry_bucket"], r["trades"], r["wins"], r["win_rate_pct"], r["total_R"]))
        f.write("\n## Walk-forward\n")
        for r in wf_rows:
            f.write("- %s (%s to %s): sessions=%d, trades=%d, win_rate=%s%%, total_R=%s\n" % (
                r["period"], r["session_start"], r["session_end"], r["sessions"],
                r["trades"], r["win_rate_pct"], r["total_R"]))
        f.write("\n## Limitations\n")
        f.write("- ~3.5 months of data (77 sessions); many condition cells are sparse.\n")
        f.write("- Simplified deterministic triggers; not an exhaustive search of all price-action patterns.\n")
        f.write("- Index points only; no option premium, charges, slippage beyond documented assumptions.\n")
        f.write("- Two partial sessions excluded from strict trade simulation.\n")
        f.write("- Thresholds are documented defaults, not optimized on the test period.\n")

    print("Done. sessions=%d candles=%d setups=%d trades=%d" % (
        len(sessions), len(candles), total_setups, total_trades))


if __name__ == "__main__":
    main()
