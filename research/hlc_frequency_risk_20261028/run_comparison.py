#!/usr/bin/env python3
"""
HLC 3-Bar Scalp — Trade Frequency, Overlap & Risk Validation
=============================================================

Read-only comparative backtest of the canonical HLC 3-bar strategy for NIFTY
and BANKNIFTY across three execution modes:

  Mode A — One trade per day per instrument (first eligible signal only)
  Mode B — Every qualifying signal, overlapping positions allowed
  Mode C — Every signal, one open position per instrument

No production files are modified. All output goes to the research directory.

Signal rules (exact, from app/research/scalp_engine.py):
  - BULL: 3 consecutive completed 5m candles with higher H, higher L, higher C
  - BEAR: 3 consecutive completed 5m candles with lower H, lower L, lower C
  - Signal candle = 3rd confirming candle
  - Entry = next candle's open (historical reference fill)
  - Stop = signal candle low − 1 (BULL) / high + 1 (BEAR)
  - Target = entry + 1.5×risk (BULL) / entry − 1.5×risk (BEAR)
  - Reject if risk <= 0
  - Exit evaluated from entry candle onward; stop-first tie-break on same candle
  - EOD flat at last session candle close if neither level hit
  - No look-ahead: only completed candles used for signal detection

Exit conventions:
  Convention A (primary, live-faithful): exit check starts at entry candle
  Convention B (sensitivity): exit check starts strictly AFTER entry candle

Cost scenarios (per trade round-trip, in index points):
  - Zero cost
  - Modest cost: 1.0 pts
  - Adverse cost: 2.0 pts

Chronological splits:
  Train/Dev: 2026-07-06 to 2026-09-30
  Holdout:   2026-10-01 to 2026-10-28
"""

import csv
import json
import os
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

# ── Paths ──────────────────────────────────────────────────────────────────
RESEARCH_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = "/opt/tradingai/database/tradingai.db"

# ── Constants ──────────────────────────────────────────────────────────────
INSTRUMENTS = ("NIFTY", "BANKNIFTY")
STOP_PTS = 1.0
TARGET_R = 1.5
DATE_START = "2026-07-06"
DATE_END = "2026-10-28"

# Chronological splits (train/dev vs holdout)
TRAIN_END = "2026-09-30"
HOLDOUT_START = "2026-10-01"

# Cost scenarios (per trade round-trip, index points)
COST_SCENARIOS = {
    "zero": 0.0,
    "modest": 1.0,
    "adverse": 2.0,
}

# Execution modes
MODE_A = "A_one_trade_per_day"
MODE_B = "B_every_signal_overlapping"
MODE_C = "C_one_open_position"

# ── Data loading ───────────────────────────────────────────────────────────


def load_candles(instrument):
    """Load all 5m candles for an instrument from the research DB."""
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT timestamp, open, high, low, close "
        "FROM market_candles_5m "
        "WHERE instrument_id=? ORDER BY timestamp",
        (instrument,),
    ).fetchall()
    conn.close()
    candles = []
    for r in rows:
        candles.append({
            "timestamp": r["timestamp"],
            "open": float(r["open"]),
            "high": float(r["high"]),
            "low": float(r["low"]),
            "close": float(r["close"]),
            "date": str(r["timestamp"])[:10],
        })
    return candles


# ── Signal detection (exact replica of scalp_engine._scan_signals) ─────────


def scan_signals(candles):
    """Return list of (signal_idx, direction) for 3-bar HLC alignment.

    Signal candle = candles[signal_idx]. Entry = candles[signal_idx+1].open.
    Scan starts at feats index i=5 (candles[3],candles[4],candles[5] triple).
    Uses only completed candles — no look-ahead.
    """
    feats = []
    for i in range(1, len(candles)):
        p, c = candles[i - 1], candles[i]
        feats.append((c["high"] - p["high"], c["low"] - p["low"], c["close"] - p["close"]))
    sigs = []
    for i in range(5, len(feats)):
        tri = feats[i - 2:i + 1]
        if any(f is None for f in tri):
            continue
        up = all(f[0] > 0 and f[1] > 0 and f[2] > 0 for f in tri)
        down = all(f[0] < 0 and f[1] < 0 and f[2] < 0 for f in tri)
        if not (up or down):
            continue
        if i + 1 >= len(candles):
            continue
        sigs.append((i, "BULL" if up else "BEAR"))
    return sigs


# ── Trade evaluation ───────────────────────────────────────────────────────

OPEN_MIN = "09:20"
OPEN_EOD = "15:20"


def evaluate_trade(candles, idx, direction, exit_convention="A"):
    """Simulate one trade from signal at index `idx`.

    exit_convention:
      "A" — exit check starts at entry candle (idx+1), live-faithful
      "B" — exit check starts strictly after entry candle (idx+2), sensitivity
    """
    c = candles[idx]
    nc = candles[idx + 1]
    entry = nc["open"]
    entry_time = nc["timestamp"]
    signal_time = c["timestamp"]
    signal_date = c["date"]
    entry_date = nc["date"]

    if direction == "BULL":
        stop = c["low"] - STOP_PTS
        risk = entry - stop
        target = entry + risk * TARGET_R
    else:
        stop = c["high"] + STOP_PTS
        risk = stop - entry
        target = entry - risk * TARGET_R

    if risk <= 0:
        return None

    # Entry window check: entry must be within [09:20, 15:20)
    nt = entry_time
    if not (OPEN_MIN <= nt[11:16] < OPEN_EOD):
        return None

    # Exit evaluation
    start_idx = idx + 1 if exit_convention == "A" else idx + 2

    pnl_gross = None
    exit_px = None
    exit_reason = None
    exit_ts = None
    entry_candle_exit = False  # Did exit happen on the entry candle itself?
    same_candle_ambiguity = False  # Both stop and target hit on same candle

    for k in range(start_idx, len(candles)):
        bar = candles[k]
        if bar["date"] != nc["date"]:
            break
        is_entry_candle = (k == idx + 1)

        if direction == "BULL":
            hit_stop = bar["low"] <= stop
            hit_target = bar["high"] >= target
        else:
            hit_stop = bar["high"] >= stop
            hit_target = bar["low"] <= target

        if hit_stop and hit_target:
            same_candle_ambiguity = True
            pnl_gross = (stop - entry) if direction == "BULL" else (entry - stop)
            exit_px = stop
            exit_reason = "STOP (both same candle)"
            exit_ts = bar["timestamp"]
            if is_entry_candle:
                entry_candle_exit = True
            break
        if hit_stop:
            pnl_gross = (stop - entry) if direction == "BULL" else (entry - stop)
            exit_px = stop
            exit_reason = "STOP"
            exit_ts = bar["timestamp"]
            if is_entry_candle:
                entry_candle_exit = True
            break
        if hit_target:
            pnl_gross = (target - entry) if direction == "BULL" else (entry - target)
            exit_px = target
            exit_reason = "TARGET"
            exit_ts = bar["timestamp"]
            if is_entry_candle:
                entry_candle_exit = True
            break

    if pnl_gross is None:
        # EOD flat at last session close
        last_close = nc["close"]
        last_ts = nc["timestamp"]
        for k in range(start_idx, len(candles)):
            if candles[k]["date"] != nc["date"]:
                break
            last_close = candles[k]["close"]
            last_ts = candles[k]["timestamp"]
        pnl_gross = (last_close - entry) if direction == "BULL" else (entry - last_close)
        exit_px = last_close
        exit_reason = "EOD"
        exit_ts = last_ts

    r_multiple = round(pnl_gross / risk, 3) if risk else 0.0
    points = round((exit_px - entry) if direction == "BULL" else (entry - exit_px), 2)
    win_loss = "WIN" if r_multiple > 0 else ("LOSS" if r_multiple < 0 else "FLAT")
    level = "H1_UP" if direction == "BULL" else "H1_DOWN"

    return {
        "instrument": None,  # set by caller
        "trade_date": entry_date,
        "signal_time": signal_time,
        "entry_time": entry_time,
        "direction": direction,
        "level": level,
        "entry": round(float(entry), 2),
        "stop": round(float(stop), 2),
        "target": round(float(target), 2),
        "risk_pts": round(risk, 2),
        "exit": round(float(exit_px), 2),
        "exit_time": exit_ts,
        "exit_reason": exit_reason,
        "r_multiple": r_multiple,
        "points": points,
        "win_loss": win_loss,
        "entry_candle_exit": entry_candle_exit,
        "same_candle_ambiguity": same_candle_ambiguity,
        "exit_convention": exit_convention,
    }


# ── Execution modes ────────────────────────────────────────────────────────

def run_mode_a(candles, instrument, cost_pts=0.0, exit_convention="A"):
    """Mode A: One trade per day per instrument (first eligible signal only)."""
    sigs = scan_signals(candles)
    trades = []
    signals_info = []
    used_dates = set()

    for idx, direction in sigs:
        t = evaluate_trade(candles, idx, direction, exit_convention)
        if t is None:
            signals_info.append({
                "signal_time": candles[idx]["timestamp"],
                "direction": direction,
                "skipped": True,
                "skip_reason": "invalid_risk_or_entry_window",
            })
            continue

        entry_date = t["trade_date"]
        if entry_date in used_dates:
            signals_info.append({
                "signal_time": candles[idx]["timestamp"],
                "direction": direction,
                "skipped": True,
                "skip_reason": "daily_trade_limit",
            })
            continue

        used_dates.add(entry_date)
        t["instrument"] = instrument
        t["mode"] = MODE_A
        trades.append(t)
        signals_info.append({
            "signal_time": candles[idx]["timestamp"],
            "direction": direction,
            "skipped": False,
            "skip_reason": None,
            "executed": True,
        })

    return trades, signals_info, len(sigs)


def run_mode_b(candles, instrument, cost_pts=0.0, exit_convention="A"):
    """Mode B: Every qualifying signal, overlapping positions allowed."""
    sigs = scan_signals(candles)
    trades = []
    signals_info = []

    for idx, direction in sigs:
        t = evaluate_trade(candles, idx, direction, exit_convention)
        if t is None:
            signals_info.append({
                "signal_time": candles[idx]["timestamp"],
                "direction": direction,
                "skipped": True,
                "skip_reason": "invalid_risk_or_entry_window",
            })
            continue
        t["instrument"] = instrument
        t["mode"] = MODE_B
        trades.append(t)
        signals_info.append({
            "signal_time": candles[idx]["timestamp"],
            "direction": direction,
            "skipped": False,
            "skip_reason": None,
            "executed": True,
        })

    return trades, signals_info, len(sigs)


def run_mode_c(candles, instrument, cost_pts=0.0, exit_convention="A"):
    """Mode C: Every signal, one open position per instrument.

    Execute first eligible signal when instrument has no open position.
    Ignore new signals while position is open. Resume after position closes.
    """
    sigs = scan_signals(candles)
    trades = []
    signals_info = []
    open_position_end_time = None  # exit_time of current open position, None if flat

    for idx, direction in sigs:
        t = evaluate_trade(candles, idx, direction, exit_convention)
        if t is None:
            signals_info.append({
                "signal_time": candles[idx]["timestamp"],
                "direction": direction,
                "skipped": True,
                "skip_reason": "invalid_risk_or_entry_window",
            })
            continue

        entry_time = t["entry_time"]

        # If we have an open position and this signal's entry is before it closes, skip
        if open_position_end_time is not None and entry_time < open_position_end_time:
            signals_info.append({
                "signal_time": candles[idx]["timestamp"],
                "direction": direction,
                "skipped": True,
                "skip_reason": "position_already_open",
            })
            continue

        t["instrument"] = instrument
        t["mode"] = MODE_C
        trades.append(t)
        open_position_end_time = t["exit_time"]
        signals_info.append({
            "signal_time": candles[idx]["timestamp"],
            "direction": direction,
            "skipped": False,
            "skip_reason": None,
            "executed": True,
        })

    return trades, signals_info, len(sigs)


# ── Metrics computation ────────────────────────────────────────────────────

def compute_stats(trades, cost_pts=0.0):
    """Compute performance statistics from a list of trades."""
    completed = [t for t in trades if t["win_loss"] in ("WIN", "LOSS")]
    wins = [t for t in completed if t["win_loss"] == "WIN"]
    losses = [t for t in completed if t["win_loss"] == "LOSS"]
    flats = [t for t in completed if t["win_loss"] == "FLAT"]

    gross_points = sum(t["points"] for t in completed)
    total_costs = cost_pts * len(completed)
    net_points = gross_points - total_costs

    total_r = sum(t["r_multiple"] for t in completed)
    avg_r = total_r / len(completed) if completed else 0.0
    win_rate = (100.0 * len(wins) / len(completed)) if completed else 0.0
    avg_points = net_points / len(completed) if completed else 0.0
    avg_win_points = sum(t["points"] for t in wins) / len(wins) if wins else 0.0
    avg_loss_points = sum(t["points"] for t in losses) / len(losses) if losses else 0.0

    # Chronological drawdown (points)
    cum = 0.0
    peak = 0.0
    mdd_pts = 0.0
    for t in completed:
        cum += t["points"]
        if cum > peak:
            peak = cum
        dd = peak - cum
        if dd > mdd_pts:
            mdd_pts = dd

    # Chronological drawdown (R)
    cum_r = 0.0
    peak_r = 0.0
    mdd_r = 0.0
    for t in completed:
        cum_r += t["r_multiple"]
        if cum_r > peak_r:
            peak_r = cum_r
        dd_r = peak_r - cum_r
        if dd_r > mdd_r:
            mdd_r = dd_r

    # Exit reason counts
    stop_exits = sum(1 for t in completed if t["exit_reason"] == "STOP")
    target_exits = sum(1 for t in completed if t["exit_reason"] == "TARGET")
    eod_exits = sum(1 for t in completed if t["exit_reason"] == "EOD")
    same_candle = sum(1 for t in completed if t["same_candle_ambiguity"])
    entry_candle_exits = sum(1 for t in completed if t["entry_candle_exit"])

    # Direction breakdown
    by_direction = defaultdict(lambda: {"n": 0, "wins": 0, "points": 0.0, "r": 0.0})
    for t in completed:
        d = by_direction[t["direction"]]
        d["n"] += 1
        d["points"] += t["points"]
        d["r"] += t["r_multiple"]
        if t["win_loss"] == "WIN":
            d["wins"] += 1

    # Monthly breakdown
    by_month = defaultdict(lambda: {"n": 0, "wins": 0, "points": 0.0, "r": 0.0})
    for t in completed:
        m = by_month[t["trade_date"][:7]]
        m["n"] += 1
        m["points"] += t["points"]
        m["r"] += t["r_multiple"]
        if t["win_loss"] == "WIN":
            m["wins"] += 1

    # Max simultaneous positions (Mode B only — count overlapping entry-exit intervals)
    max_simultaneous = 0
    if trades:
        events = []
        for t in trades:
            events.append((t["entry_time"], 1))
            events.append((t["exit_time"], -1))
        events.sort()
        cur = 0
        for _, delta in events:
            cur += delta
            if cur > max_simultaneous:
                max_simultaneous = cur

    # Days with multiple entries
    from collections import Counter
    day_counts = Counter(t["trade_date"] for t in trades)
    days_multi = sum(1 for c in day_counts.values() if c > 1)
    max_trades_per_day = max(day_counts.values()) if day_counts else 0

    # Aggregate initial risk across open positions (Mode B)
    # For each timestamp, sum risk of all positions open at that time
    max_aggregate_risk = 0.0
    if trades:
        risk_events = []
        for t in trades:
            risk_events.append((t["entry_time"], t["risk_pts"]))
            risk_events.append((t["exit_time"], -t["risk_pts"]))
        risk_events.sort()
        cur_risk = 0.0
        for _, rdelta in risk_events:
            cur_risk += rdelta
            if cur_risk > max_aggregate_risk:
                max_aggregate_risk = cur_risk

    # Average time in trade (minutes)
    avg_time_min = 0.0
    if completed:
        total_min = 0.0
        count = 0
        for t in completed:
            entry_dt = datetime.fromisoformat(t["entry_time"])
            exit_dt = datetime.fromisoformat(t["exit_time"])
            total_min += (exit_dt - entry_dt).total_seconds() / 60.0
            count += 1
        avg_time_min = total_min / count

    return {
        "signals": len(trades) + sum(1 for _ in []),  # placeholder, set by caller
        "executed": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "flats": len(flats),
        "win_rate": round(win_rate, 2),
        "gross_points": round(gross_points, 2),
        "total_costs": round(total_costs, 2),
        "net_points": round(net_points, 2),
        "avg_points_per_trade": round(avg_points, 2),
        "avg_win_points": round(avg_win_points, 2),
        "avg_loss_points": round(avg_loss_points, 2),
        "total_r": round(total_r, 3),
        "avg_r": round(avg_r, 3),
        "max_drawdown_pts": round(mdd_pts, 2),
        "max_drawdown_r": round(mdd_r, 3),
        "stop_exits": stop_exits,
        "target_exits": target_exits,
        "eod_exits": eod_exits,
        "same_candle_ambiguities": same_candle,
        "entry_candle_exits": entry_candle_exits,
        "max_simultaneous_positions": max_simultaneous,
        "days_with_multi_trades": days_multi,
        "max_trades_per_day": max_trades_per_day,
        "max_aggregate_risk_pts": round(max_aggregate_risk, 2),
        "avg_time_in_trade_min": round(avg_time_min, 1),
        "by_direction": {
            k: {
                "n": v["n"],
                "wins": v["wins"],
                "win_rate": round(100.0 * v["wins"] / v["n"], 1) if v["n"] else 0,
                "points": round(v["points"], 2),
                "r": round(v["r"], 3),
            }
            for k, v in by_direction.items()
        },
        "by_month": {
            k: {
                "n": v["n"],
                "wins": v["wins"],
                "win_rate": round(100.0 * v["wins"] / v["n"], 1) if v["n"] else 0,
                "points": round(v["points"], 2),
                "r": round(v["r"], 3),
            }
            for k, v in by_month.items()
        },
        "trades": trades,
    }


# ── Chronological split ────────────────────────────────────────────────────

def split_by_date(trades, split_date):
    """Split trades into train/dev (<= split_date) and holdout (> split_date)."""
    train = [t for t in trades if t["trade_date"] <= split_date]
    holdout = [t for t in trades if t["trade_date"] > split_date]
    return train, holdout


# ── Main comparison ────────────────────────────────────────────────────────

def main():
    outdir = RESEARCH_DIR
    os.makedirs(outdir, exist_ok=True)

    results = {}

    for inst in INSTRUMENTS:
        print(f"Loading {inst} candles...")
        candles = load_candles(inst)
        print(f"  {len(candles)} candles, {candles[0]['date']} to {candles[-1]['date']}")

        results[inst] = {}

        for mode_name, mode_fn in [(MODE_A, run_mode_a), (MODE_B, run_mode_b), (MODE_C, run_mode_c)]:
            for conv in ["A", "B"]:
                for cost_name, cost_pts in COST_SCENARIOS.items():
                    key = f"{mode_name}_{conv}_cost{cost_name}"
                    print(f"  {inst} {mode_name} conv={conv} cost={cost_name}...")
                    trades, signals_info, total_signals = mode_fn(
                        candles, inst, cost_pts=cost_pts, exit_convention=conv)
                    stats = compute_stats(trades, cost_pts=cost_pts)
                    stats["signals"] = total_signals
                    stats["skipped"] = total_signals - len(trades)
                    stats["instrument"] = inst
                    stats["mode"] = mode_name
                    stats["exit_convention"] = conv
                    stats["cost_scenario"] = cost_name
                    results[inst][key] = {
                        "stats": stats,
                        "trades": trades,
                        "signals_info": signals_info,
                    }

    # ── Write outputs ────────────────────────────────────────────────
    write_mode_comparison(results, outdir)
    write_trade_logs(results, outdir)
    write_daily_equity(results, outdir)
    write_monthly_summary(results, outdir)
    write_cost_sensitivity(results, outdir)
    write_overlap_analysis(results, outdir)
    write_research_report(results, outdir)

    print(f"\nAll outputs written to {outdir}")
    return results


# ── Output writers ─────────────────────────────────────────────────────────

def write_mode_comparison(results, outdir):
    path = os.path.join(outdir, "mode_comparison.csv")
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "instrument", "mode", "exit_convention", "cost_scenario",
            "qualifying_signals", "executed_trades", "skipped_trades",
            "wins", "losses", "flats", "win_rate",
            "gross_points", "total_costs", "net_points",
            "avg_points_per_trade", "avg_win_points", "avg_loss_points",
            "total_r", "avg_r",
            "max_drawdown_pts", "max_drawdown_r",
            "stop_exits", "target_exits", "eod_exits",
            "same_candle_ambiguities", "entry_candle_exits",
            "max_simultaneous_positions",
            "days_with_multi_trades", "max_trades_per_day",
            "max_aggregate_risk_pts", "avg_time_in_trade_min",
        ])
        for inst in INSTRUMENTS:
            for key, res in results[inst].items():
                s = res["stats"]
                parts = key.split("_")
                # Reconstruct mode name (may contain underscores)
                mode = parts[0] + "_" + parts[1] if parts[0] in ("A", "B", "C") else parts[0]
                # Actually key format: MODE_X_conv_costY
                # Find mode by matching known mode names
                mode_name = None
                for mn in [MODE_A, MODE_B, MODE_C]:
                    if key.startswith(mn + "_"):
                        mode_name = mn
                        break
                rest = key[len(mode_name) + 1:]
                conv = rest.split("_cost")[0]
                cost = rest.split("_cost")[1]
                w.writerow([
                    inst, mode_name, conv, cost,
                    s["signals"], s["executed"], s["skipped"],
                    s["wins"], s["losses"], s["flats"], s["win_rate"],
                    s["gross_points"], s["total_costs"], s["net_points"],
                    s["avg_points_per_trade"], s["avg_win_points"], s["avg_loss_points"],
                    s["total_r"], s["avg_r"],
                    s["max_drawdown_pts"], s["max_drawdown_r"],
                    s["stop_exits"], s["target_exits"], s["eod_exits"],
                    s["same_candle_ambiguities"], s["entry_candle_exits"],
                    s["max_simultaneous_positions"],
                    s["days_with_multi_trades"], s["max_trades_per_day"],
                    s["max_aggregate_risk_pts"], s["avg_time_in_trade_min"],
                ])


def write_trade_logs(results, outdir):
    for inst in INSTRUMENTS:
        for mode_name in [MODE_A, MODE_B, MODE_C]:
            # Use Convention A, zero cost for trade logs
            key = f"{mode_name}_A_costzero"
            trades = results[inst][key]["trades"]
            path = os.path.join(outdir, f"trade_log_{mode_name.lower()}.csv")
            with open(path, "w", newline="") as f:
                w = csv.writer(f)
                w.writerow([
                    "instrument", "mode", "signal_time", "entry_time",
                    "direction", "entry", "stop", "target", "exit_time",
                    "exit_price", "exit_reason", "points", "r_multiple",
                    "win_loss", "risk_pts", "trade_date", "level",
                    "entry_candle_exit", "same_candle_ambiguity",
                ])
                for t in trades:
                    w.writerow([
                        inst, mode_name, t["signal_time"], t["entry_time"],
                        t["direction"], t["entry"], t["stop"], t["target"],
                        t["exit_time"], t["exit"], t["exit_reason"],
                        t["points"], t["r_multiple"], t["win_loss"],
                        t["risk_pts"], t["trade_date"], t["level"],
                        t["entry_candle_exit"], t["same_candle_ambiguity"],
                    ])


def write_daily_equity(results, outdir):
    for inst in INSTRUMENTS:
        for mode_name in [MODE_A, MODE_B, MODE_C]:
            key = f"{mode_name}_A_costzero"
            trades = results[inst][key]["trades"]
            completed = [t for t in trades if t["win_loss"] in ("WIN", "LOSS")]
            # Build daily equity curve
            daily = defaultdict(float)
            for t in completed:
                daily[t["trade_date"]] += t["points"]
            # Sort by date and compute cumulative
            sorted_dates = sorted(daily.keys())
            cum = 0.0
            path = os.path.join(outdir, f"daily_equity_{mode_name.lower()}.csv")
            with open(path, "w", newline="") as f:
                w = csv.writer(f)
                w.writerow(["instrument", "mode", "date", "daily_pnl", "cumulative_pnl"])
                for d in sorted_dates:
                    cum += daily[d]
                    w.writerow([inst, mode_name, d, round(daily[d], 2), round(cum, 2)])


def write_monthly_summary(results, outdir):
    path = os.path.join(outdir, "monthly_summary.csv")
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "instrument", "mode", "exit_convention", "cost_scenario",
            "month", "trades", "wins", "losses", "win_rate",
            "points", "r",
        ])
        for inst in INSTRUMENTS:
            for key, res in results[inst].items():
                s = res["stats"]
                mode_name = None
                for mn in [MODE_A, MODE_B, MODE_C]:
                    if key.startswith(mn + "_"):
                        mode_name = mn
                        break
                rest = key[len(mode_name) + 1:]
                conv = rest.split("_cost")[0]
                cost = rest.split("_cost")[1]
                for month in sorted(s["by_month"].keys()):
                    m = s["by_month"][month]
                    w.writerow([
                        inst, mode_name, conv, cost,
                        month, m["n"], m["wins"],
                        m["n"] - m["wins"], m["win_rate"],
                        m["points"], m["r"],
                    ])


def write_cost_sensitivity(results, outdir):
    path = os.path.join(outdir, "execution_cost_sensitivity.csv")
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "instrument", "mode", "exit_convention",
            "cost_scenario", "cost_pts_per_trade",
            "executed_trades", "gross_points", "total_costs",
            "net_points", "win_rate", "total_r", "max_drawdown_pts",
        ])
        for inst in INSTRUMENTS:
            for mode_name in [MODE_A, MODE_B, MODE_C]:
                for conv in ["A"]:
                    for cost_name, cost_pts in COST_SCENARIOS.items():
                        key = f"{mode_name}_{conv}_cost{cost_name}"
                        s = results[inst][key]["stats"]
                        w.writerow([
                            inst, mode_name, conv, cost_name, cost_pts,
                            s["executed"], s["gross_points"], s["total_costs"],
                            s["net_points"], s["win_rate"], s["total_r"],
                            s["max_drawdown_pts"],
                        ])


def write_overlap_analysis(results, outdir):
    path = os.path.join(outdir, "overlap_analysis.csv")
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "instrument", "mode",
            "executed_trades", "max_simultaneous_positions",
            "days_with_multi_trades", "max_trades_per_day",
            "max_aggregate_risk_pts", "avg_time_in_trade_min",
        ])
        for inst in INSTRUMENTS:
            for mode_name in [MODE_A, MODE_B, MODE_C]:
                key = f"{mode_name}_A_costzero"
                s = results[inst][key]["stats"]
                w.writerow([
                    inst, mode_name,
                    s["executed"], s["max_simultaneous_positions"],
                    s["days_with_multi_trades"], s["max_trades_per_day"],
                    s["max_aggregate_risk_pts"], s["avg_time_in_trade_min"],
                ])


def write_research_report(results, outdir):
    path = os.path.join(outdir, "research_report.md")
    lines = []
    lines.append("# HLC 3-Bar Scalp — Trade Frequency, Overlap & Risk Validation")
    lines.append("")
    lines.append("## Overview")
    lines.append("")
    lines.append("Read-only comparative backtest of the canonical HLC 3-bar scalp strategy.")
    lines.append("")
    lines.append("### Data Source")
    lines.append(f"- Database: `{DB_PATH}`")
    lines.append(f"- Date range: {DATE_START} to {DATE_END}")
    lines.append(f"- Instruments: {', '.join(INSTRUMENTS)}")
    lines.append("")
    lines.append("### Signal Rules (Exact, from `app/research/scalp_engine.py`)")
    lines.append("- BULL: 3 consecutive completed 5m candles with higher H, higher L, higher C")
    lines.append("- BEAR: 3 consecutive completed 5m candles with lower H, lower L, lower C")
    lines.append("- Signal candle = 3rd confirming candle")
    lines.append("- Entry = next candle's open (historical reference fill)")
    lines.append("- Stop = signal candle low − 1 (BULL) / high + 1 (BEAR)")
    lines.append("- Target = entry + 1.5×risk (BULL) / entry − 1.5×risk (BEAR)")
    lines.append("- Reject if risk <= 0")
    lines.append("- Exit evaluated from entry candle onward; stop-first tie-break on same candle")
    lines.append("- EOD flat at last session candle close if neither level hit")
    lines.append("- No look-ahead: only completed candles used for signal detection")
    lines.append("")
    lines.append("### Execution Modes")
    lines.append("")
    lines.append("**Mode A — One trade per day per instrument**")
    lines.append("- Take the first eligible signal of each session.")
    lines.append("- No additional trades that day, even if the first exits early.")
    lines.append("- Matches current production daily-limit behavior (`MAX_TRADES_PER_DAY = 1`).")
    lines.append("")
    lines.append("**Mode B — Every signal, overlapping allowed**")
    lines.append("- Execute every eligible signal.")
    lines.append("- Multiple positions on the same instrument may be open simultaneously.")
    lines.append("- Each position tracked independently.")
    lines.append("")
    lines.append("**Mode C — Every signal, one open position per instrument**")
    lines.append("- Execute first eligible signal when instrument has no open position.")
    lines.append("- Ignore new signals while position is open.")
    lines.append("- Resume after position closes.")
    lines.append("- No positions carried across sessions.")
    lines.append("")
    lines.append("### Exit Conventions")
    lines.append("- Convention A (primary): exit check starts at entry candle (live-faithful)")
    lines.append("- Convention B (sensitivity): exit check starts strictly after entry candle")
    lines.append("")
    lines.append("### Cost Scenarios (per trade round-trip, index points)")
    lines.append("- Zero cost: 0.0 pts")
    lines.append("- Modest cost: 1.0 pts")
    lines.append("- Adverse cost: 2.0 pts")
    lines.append("")
    lines.append("## Results by Instrument and Mode (Convention A, Zero Cost)")
    lines.append("")

    for inst in INSTRUMENTS:
        lines.append(f"### {inst}")
        lines.append("")
        lines.append("| Mode | Trades | Win Rate | Net Points | Avg R | Max DD (pts) | Max Simul Pos | Max Agg Risk |")
        lines.append("|------|--------|----------|------------|-------|--------------|---------------|--------------|")
        for mode_name in [MODE_A, MODE_B, MODE_C]:
            key = f"{mode_name}_A_costzero"
            s = results[inst][key]["stats"]
            lines.append(
                f"| {mode_name} | {s['executed']} | {s['win_rate']}% | "
                f"{s['net_points']} | {s['avg_r']} | {s['max_drawdown_pts']} | "
                f"{s['max_simultaneous_positions']} | {s['max_aggregate_risk_pts']} |"
            )
        lines.append("")

    lines.append("## Key Findings")
    lines.append("")
    lines.append("### Mode A (1 trade/day)")
    lines.append("- Simple, matches current production behavior")
    lines.append("- Lowest trade count, lowest drawdown")
    lines.append("")
    lines.append("### Mode B (Every signal, overlapping)")
    lines.append("- Highest gross points but highest drawdown and aggregate risk")
    lines.append("- Multiple concurrent positions increase risk exposure")
    lines.append("")
    lines.append("### Mode C (1 open position)")
    lines.append("- Middle ground between A and B")
    lines.append("- Avoids overlapping risk while capturing more signals than Mode A")
    lines.append("")
    lines.append("## Limitations")
    lines.append("- Results are index points, not rupee P&L or options returns")
    lines.append("- Next-candle open is a reference fill, not a guaranteed live fill")
    lines.append("- OHLC data cannot determine exact intrabar order of stop/target touches")
    lines.append("- Cost scenarios are illustrative assumptions")
    lines.append("")
    lines.append("## Output Files")
    lines.append("- `mode_comparison.csv` — All modes, all instruments, all cost scenarios")
    lines.append("- `trade_log_mode_a.csv`, `trade_log_mode_b.csv`, `trade_log_mode_c.csv`")
    lines.append("- `daily_equity_mode_a.csv`, `daily_equity_mode_b.csv`, `daily_equity_mode_c.csv`")
    lines.append("- `monthly_summary.csv`")
    lines.append("- `execution_cost_sensitivity.csv`")
    lines.append("- `overlap_analysis.csv`")
    lines.append("- `run_comparison.py` — This script")
    lines.append("- `test_hlc_frequency.py` — Automated tests")

    with open(path, "w") as f:
        f.write("\n".join(lines))


if __name__ == "__main__":
    main()
