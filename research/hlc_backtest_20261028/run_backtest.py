"""
HLC Scalp 3-Bar Backtest — Read-Only, No-Look-Ahead
====================================================

Replicates the exact rules from /opt/tradingai/app/research/scalp_engine.py
(_scan_signals + _trade_for) and the deployed live engine
(/opt/tradingai/app/live/engine.py, _hlc_book_signal).

Convention A (primary, live-faithful): Exit evaluation starts at the ENTRY
candle (idx+1), so stop/target protection begins immediately after entry fill.
If both stop and target touch on the same candle, STOP wins. EOD flat at last
session close.

Convention B (comparison, research): Exit evaluation starts STRICTLY AFTER the
entry candle (idx+2 onward). All other rules identical.

Signal rules (exact from implementation):
- Scan starts at feats index i=5 (candles[3],candles[4],candles[5] triple)
- BULL: 3 consecutive candles with higher H, higher L, higher C
- BEAR: 3 consecutive candles with lower H, lower L, lower C
- Signal candle = candles[i]
- Entry = candles[i+1].open (next candle open)
- Entry must be on same date as signal candle
- Entry must be within [09:20, 15:20) window (live engine constraint)
- Risk = |entry - stop|; reject if risk <= 0
- BULL stop = signal_candle.low - 1.0, target = entry + 1.5*risk
- BEAR stop = signal_candle.high + 1.0, target = entry - 1.5*risk

NO DAILY TRADE LIMIT: every qualifying signal is executed.
"""

import csv
import os
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = "/opt/tradingai/database/tradingai.db"


def load_candles(instrument):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT timestamp, open, high, low, close "
        "FROM market_candles_5m "
        "WHERE instrument_id=? "
        "ORDER BY timestamp",
        (instrument,),
    ).fetchall()
    conn.close()
    return [
        {
            "timestamp": r["timestamp"],
            "open": float(r["open"]),
            "high": float(r["high"]),
            "low": float(r["low"]),
            "close": float(r["close"]),
            "date": r["timestamp"][:10],
        }
        for r in rows
    ]


def scan_signals(candles):
    feats = []
    for i in range(1, len(candles)):
        p, c = candles[i - 1], candles[i]
        feats.append((c["high"] - p["high"], c["low"] - p["low"], c["close"] - p["close"]))
    sigs = []
    for i in range(5, len(feats)):
        tri = feats[i - 2 : i + 1]
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


OPEN_MIN = "09:20"
OPEN_EOD = "15:20"


def evaluate_trade_A(candles, idx, direction):
    c = candles[idx]
    nc = candles[idx + 1]
    entry = nc["open"]
    entry_time = nc["timestamp"]
    signal_time = c["timestamp"]

    if direction == "BULL":
        stop = c["low"] - 1.0
        risk = entry - stop
        target = entry + risk * 1.5
    else:
        stop = c["high"] + 1.0
        risk = stop - entry
        target = entry - risk * 1.5

    if risk <= 0:
        return None

    entry_px = round(entry, 2)
    stop_px = round(stop, 2)
    target_px = round(target, 2)

    nt = entry_time
    if not (OPEN_MIN <= nt[11:16] < OPEN_EOD):
        return None

    pnl_gross = None
    exit_px = None
    exit_reason = None
    exit_ts = None

    for k in range(idx + 1, len(candles)):
        bar = candles[k]
        if bar["date"] != nc["date"]:
            break
        if direction == "BULL":
            hit_stop = bar["low"] <= stop
            hit_target = bar["high"] >= target
        else:
            hit_stop = bar["high"] >= stop
            hit_target = bar["low"] <= target

        if hit_stop and hit_target:
            pnl_gross = (stop - entry) if direction == "BULL" else (entry - stop)
            exit_px = stop
            exit_reason = "STOP (both same candle)"
            exit_ts = bar["timestamp"]
            break
        if hit_stop:
            pnl_gross = (stop - entry) if direction == "BULL" else (entry - stop)
            exit_px = stop
            exit_reason = "STOP"
            exit_ts = bar["timestamp"]
            break
        if hit_target:
            pnl_gross = (target - entry) if direction == "BULL" else (entry - target)
            exit_px = target
            exit_reason = "TARGET"
            exit_ts = bar["timestamp"]
            break

    if pnl_gross is None:
        last_close = nc["close"]
        last_ts = nc["timestamp"]
        for k in range(idx + 1, len(candles)):
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
        "trade_date": nc["date"],
        "direction": direction,
        "level": level,
        "entry": entry_px,
        "stop": stop_px,
        "target": target_px,
        "entry_time": entry_time,
        "exit": round(exit_px, 2),
        "exit_time": exit_ts,
        "exit_reason": exit_reason,
        "r_multiple": r_multiple,
        "points": points,
        "win_loss": win_loss,
        "signal_time": signal_time,
        "risk_pts": round(risk, 2),
    }


def evaluate_trade_B(candles, idx, direction):
    c = candles[idx]
    nc = candles[idx + 1]
    entry = nc["open"]
    entry_time = nc["timestamp"]
    signal_time = c["timestamp"]

    if direction == "BULL":
        stop = c["low"] - 1.0
        risk = entry - stop
        target = entry + risk * 1.5
    else:
        stop = c["high"] + 1.0
        risk = stop - entry
        target = entry - risk * 1.5

    if risk <= 0:
        return None

    entry_px = round(entry, 2)
    stop_px = round(stop, 2)
    target_px = round(target, 2)

    nt = entry_time
    if not (OPEN_MIN <= nt[11:16] < OPEN_EOD):
        return None

    pnl_gross = None
    exit_px = None
    exit_reason = None
    exit_ts = None

    for k in range(idx + 2, len(candles)):
        bar = candles[k]
        if bar["date"] != nc["date"]:
            break
        if direction == "BULL":
            hit_stop = bar["low"] <= stop
            hit_target = bar["high"] >= target
        else:
            hit_stop = bar["high"] >= stop
            hit_target = bar["low"] <= target

        if hit_stop and hit_target:
            pnl_gross = (stop - entry) if direction == "BULL" else (entry - stop)
            exit_px = stop
            exit_reason = "STOP (both same candle)"
            exit_ts = bar["timestamp"]
            break
        if hit_stop:
            pnl_gross = (stop - entry) if direction == "BULL" else (entry - stop)
            exit_px = stop
            exit_reason = "STOP"
            exit_ts = bar["timestamp"]
            break
        if hit_target:
            pnl_gross = (target - entry) if direction == "BULL" else (entry - target)
            exit_px = target
            exit_reason = "TARGET"
            exit_ts = bar["timestamp"]
            break

    if pnl_gross is None:
        last_close = nc["close"]
        last_ts = nc["timestamp"]
        for k in range(idx + 2, len(candles)):
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
        "trade_date": nc["date"],
        "direction": direction,
        "level": level,
        "entry": entry_px,
        "stop": stop_px,
        "target": target_px,
        "entry_time": entry_time,
        "exit": round(exit_px, 2),
        "exit_time": exit_ts,
        "exit_reason": exit_reason,
        "r_multiple": r_multiple,
        "points": points,
        "win_loss": win_loss,
        "signal_time": signal_time,
        "risk_pts": round(risk, 2),
    }


def run_backtest(instrument, candles, convention="A"):
    sigs = scan_signals(candles)

    all_signals = []
    for idx, direction in sigs:
        if convention == "A":
            trade = evaluate_trade_A(candles, idx, direction)
        else:
            trade = evaluate_trade_B(candles, idx, direction)

        signal_row = {
            "instrument": instrument,
            "signal_time": candles[idx]["timestamp"],
            "signal_candle_idx": idx,
            "direction": direction,
            "level": "H1_UP" if direction == "BULL" else "H1_DOWN",
            "entry_candle_time": candles[idx + 1]["timestamp"],
            "entry_date": candles[idx + 1]["date"],
            "skipped": False,
            "skip_reason": None,
        }

        if trade is None:
            signal_row["skipped"] = True
            signal_row["skip_reason"] = "invalid_risk_or_entry_window"
        all_signals.append(signal_row)

    # NO DAILY TRADE LIMIT — every qualifying signal is executed
    all_signals.sort(key=lambda s: s["signal_time"])

    executed_trades = []
    for sig in all_signals:
        if sig["skipped"]:
            continue
        idx = sig["signal_candle_idx"]
        direction = sig["direction"]
        if convention == "A":
            trade = evaluate_trade_A(candles, idx, direction)
        else:
            trade = evaluate_trade_B(candles, idx, direction)
        if trade is None:
            sig["skipped"] = True
            sig["skip_reason"] = "invalid_risk_or_entry_window"
            continue
        trade["signal_index"] = idx
        trade["instrument"] = instrument
        executed_trades.append(trade)

    skipped_signals = [s for s in all_signals if s["skipped"]]

    completed = [t for t in executed_trades if t["win_loss"] in ("WIN", "LOSS")]
    wins = [t for t in completed if t["win_loss"] == "WIN"]
    losses = [t for t in completed if t["win_loss"] == "LOSS"]
    flats = [t for t in completed if t["win_loss"] == "FLAT"]

    total_points = sum(t["points"] for t in completed)
    total_r = sum(t["r_multiple"] for t in completed)
    gross_win_points = sum(t["points"] for t in wins)
    gross_loss_points = sum(t["points"] for t in losses)
    avg_win = gross_win_points / len(wins) if wins else 0.0
    avg_loss = gross_loss_points / len(losses) if losses else 0.0
    expectancy = total_points / len(completed) if completed else 0.0
    win_rate = (len(wins) / len(completed) * 100) if completed else 0.0
    avg_r = total_r / len(completed) if completed else 0.0

    cumulative = 0.0
    running_max = 0.0
    max_drawdown_pts = 0.0
    for t in completed:
        cumulative += t["points"]
        running_max = max(running_max, cumulative)
        max_drawdown_pts = max(max_drawdown_pts, running_max - cumulative)

    cumulative_r = 0.0
    running_max_r = 0.0
    max_drawdown_r = 0.0
    for t in completed:
        cumulative_r += t["r_multiple"]
        running_max_r = max(running_max_r, cumulative_r)
        max_drawdown_r = max(max_drawdown_r, running_max_r - cumulative_r)

    from collections import Counter
    max_per_day = max(Counter(t["trade_date"] for t in executed_trades).values()) if executed_trades else 0
    multi_days = sum(1 for c in Counter(t["trade_date"] for t in executed_trades).values() if c > 1) if executed_trades else 0

    stats = {
        "instrument": instrument,
        "convention": convention,
        "total_signals": len(all_signals),
        "qualifying_signals": len([s for s in all_signals if not s["skipped"]]),
        "executed_trades": len(executed_trades),
        "skipped_invalid_risk": len([s for s in skipped_signals if s["skip_reason"] == "invalid_risk_or_entry_window"]),
        "skipped_daily_limit": 0,
        "wins": len(wins),
        "losses": len(losses),
        "flats": len(flats),
        "win_rate": round(win_rate, 2),
        "gross_win_points": round(gross_win_points, 2),
        "gross_loss_points": round(gross_loss_points, 2),
        "net_points": round(total_points, 2),
        "avg_points_per_trade": round(expectancy, 2),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "avg_r": round(avg_r, 3),
        "total_r": round(total_r, 3),
        "max_drawdown_pts": round(max_drawdown_pts, 2),
        "max_drawdown_r": round(max_drawdown_r, 3),
        "stop_exits": len([t for t in completed if t["exit_reason"] == "STOP"]),
        "target_exits": len([t for t in completed if t["exit_reason"] == "TARGET"]),
        "eod_exits": len([t for t in completed if t["exit_reason"] == "EOD"]),
        "same_candle_ambiguities": len([t for t in completed if t["exit_reason"] == "STOP (both same candle)"]),
        "entry_candle_exits": len([t for t in completed if t["exit_time"] == t["entry_time"]]),
        "max_trades_per_day": max_per_day,
        "days_with_multi_trades": multi_days,
    }

    return executed_trades, all_signals, skipped_signals, stats


def monthly_summary(trades):
    by_month = defaultdict(lambda: {"trades": 0, "wins": 0, "losses": 0, "points": 0.0, "r": 0.0})
    for t in trades:
        if t["win_loss"] not in ("WIN", "LOSS"):
            continue
        month = t["trade_date"][:7]
        m = by_month[month]
        m["trades"] += 1
        if t["win_loss"] == "WIN":
            m["wins"] += 1
        else:
            m["losses"] += 1
        m["points"] += t["points"]
        m["r"] += t["r_multiple"]
    result = []
    for month in sorted(by_month.keys()):
        m = by_month[month]
        result.append({
            "month": month,
            "trades": m["trades"],
            "wins": m["wins"],
            "losses": m["losses"],
            "win_rate": round(100 * m["wins"] / m["trades"], 1) if m["trades"] else 0,
            "points": round(m["points"], 2),
            "r": round(m["r"], 3),
        })
    return result


def direction_summary(trades):
    by_dir = defaultdict(lambda: {"trades": 0, "wins": 0, "losses": 0, "points": 0.0})
    for t in trades:
        if t["win_loss"] not in ("WIN", "LOSS"):
            continue
        d = by_dir[t["direction"]]
        d["trades"] += 1
        if t["win_loss"] == "WIN":
            d["wins"] += 1
        else:
            d["losses"] += 1
        d["points"] += t["points"]
    result = []
    for direction in sorted(by_dir.keys()):
        d = by_dir[direction]
        result.append({
            "direction": direction,
            "trades": d["trades"],
            "wins": d["wins"],
            "losses": d["losses"],
            "win_rate": round(100 * d["wins"] / d["trades"], 1) if d["trades"] else 0,
            "points": round(d["points"], 2),
        })
    return result


def main():
    outdir = BASE_DIR
    os.makedirs(outdir, exist_ok=True)

    instruments = ["NIFTY", "BANKNIFTY"]
    all_results = {}

    for inst in instruments:
        print(f"Loading {inst} candles...")
        candles = load_candles(inst)
        print(f"  {len(candles)} candles, {candles[0]['date']} to {candles[-1]['date']}")

        for convention in ["A", "B"]:
            label = "live_faithful" if convention == "A" else "research"
            print(f"\n=== {inst} Convention {convention} ({label}) ===")
            trades, all_signals, skipped, stats = run_backtest(inst, candles, convention)
            all_results[(inst, convention)] = {
                "trades": trades,
                "signals": all_signals,
                "skipped": skipped,
                "stats": stats,
            }
            print(f"  Signals: {stats['total_signals']}, Executed: {stats['executed_trades']}")
            print(f"  Wins: {stats['wins']}, Losses: {stats['losses']}, Win rate: {stats['win_rate']}%")
            print(f"  Net points: {stats['net_points']}, Total R: {stats['total_r']}")
            print(f"  Max DD pts: {stats['max_drawdown_pts']}, Max DD R: {stats['max_drawdown_r']}")

    write_outputs(all_results, instruments, outdir)
    print(f"\nAll outputs written to {outdir}")


def write_outputs(all_results, instruments, outdir):
    with open(os.path.join(outdir, "trade_log.csv"), "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "instrument", "convention", "signal_time", "entry_time",
            "direction", "entry", "stop", "target", "exit_time",
            "exit_price", "exit_reason", "points", "r_multiple",
            "win_loss", "risk_pts", "trade_date", "level",
        ])
        for (inst, conv), res in all_results.items():
            label = "A" if conv == "A" else "B"
            for t in res["trades"]:
                writer.writerow([
                    inst, label, t["signal_time"], t["entry_time"],
                    t["direction"], t["entry"], t["stop"], t["target"],
                    t["exit_time"], t["exit"], t["exit_reason"],
                    t["points"], t["r_multiple"], t["win_loss"],
                    t["risk_pts"], t["trade_date"], t["level"],
                ])

    with open(os.path.join(outdir, "signal_log.csv"), "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "instrument", "signal_time", "signal_candle_idx", "direction",
            "level", "entry_candle_time", "entry_date", "skipped",
            "skip_reason",
        ])
        for (inst, conv), res in all_results.items():
            for s in res["signals"]:
                writer.writerow([
                    inst, s["signal_time"], s["signal_candle_idx"],
                    s["direction"], s["level"], s["entry_candle_time"],
                    s["entry_date"], s["skipped"], s["skip_reason"] or "",
                ])

    with open(os.path.join(outdir, "monthly_summary.csv"), "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "instrument", "convention", "month", "trades", "wins",
            "losses", "win_rate", "points", "r",
        ])
        for (inst, conv), res in all_results.items():
            label = "A" if conv == "A" else "B"
            for m in monthly_summary(res["trades"]):
                writer.writerow([inst, label, m["month"], m["trades"],
                                 m["wins"], m["losses"], m["win_rate"],
                                 m["points"], m["r"]])

    with open(os.path.join(outdir, "exit_convention_comparison.csv"), "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "instrument", "metric", "convention_A_live_faithful",
            "convention_B_research", "difference_A_minus_B",
        ])
        for inst in instruments:
            stats_a = all_results[(inst, "A")]["stats"]
            stats_b = all_results[(inst, "B")]["stats"]
            metrics = [
                "executed_trades", "wins", "losses", "win_rate",
                "net_points", "avg_points_per_trade", "avg_win",
                "avg_loss", "total_r", "avg_r", "max_drawdown_pts",
                "max_drawdown_r", "stop_exits", "target_exits",
                "eod_exits", "same_candle_ambiguities",
                "entry_candle_exits", "max_trades_per_day",
                "days_with_multi_trades",
            ]
            for metric_key in metrics:
                va = stats_a[metric_key]
                vb = stats_b[metric_key]
                diff = round(va - vb, 4) if isinstance(va, (int, float)) and isinstance(vb, (int, float)) else "N/A"
                writer.writerow([inst, metric_key, va, vb, diff])

    report_lines = []
    report_lines.append("# HLC Scalp 3-Bar Backtest — Research Report (NO Daily Trade Limit)")
    report_lines.append("")
    report_lines.append(f"Generated: {datetime.now(IST).isoformat()}")
    report_lines.append(f"Source DB: {DB_PATH}")
    report_lines.append("")
    report_lines.append("## Methodology")
    report_lines.append("- Strategy: 3-bar HLC alignment (BULL: higher H/L/C x3; BEAR: lower H/L/C x3)")
    report_lines.append("- Signal detection: exact replica of app/research/scalp_engine._scan_signals")
    report_lines.append("- Entry: next candle open (no look-ahead)")
    report_lines.append("- Stop: signal candle low - 1 (BULL) / high + 1 (BEAR)")
    report_lines.append("- Target: entry + 1.5x risk (BULL) / entry - 1.5x risk (BEAR)")
    report_lines.append("- NO DAILY TRADE LIMIT — every qualifying signal is executed")
    report_lines.append("- Convention A (primary): exit checked from entry candle onward (live-faithful)")
    report_lines.append("- Convention B (comparison): exit checked strictly after entry candle (research)")
    report_lines.append("- Results are index points, not rupee P&L or options returns")
    report_lines.append("")
    for inst in instruments:
        report_lines.append(f"## {inst}")
        report_lines.append("")
        stats_a = all_results[(inst, "A")]["stats"]
        report_lines.append("### Convention A (Live-Faithful, Primary)")
        report_lines.append(f"- Total signals: {stats_a['total_signals']}")
        report_lines.append(f"- Executed trades: {stats_a['executed_trades']}")
        report_lines.append(f"- Skipped (invalid risk/entry window): {stats_a['skipped_invalid_risk']}")
        report_lines.append(f"- Skipped (daily limit): {stats_a['skipped_daily_limit']} (NONE — no limit)")
        report_lines.append(f"- Wins: {stats_a['wins']} | Losses: {stats_a['losses']} | Flats: {stats_a['flats']}")
        report_lines.append(f"- Win rate: {stats_a['win_rate']}%")
        report_lines.append(f"- Net points: {stats_a['net_points']}")
        report_lines.append(f"- Avg points per trade: {stats_a['avg_points_per_trade']}")
        report_lines.append(f"- Avg win: {stats_a['avg_win']} pts | Avg loss: {stats_a['avg_loss']} pts")
        report_lines.append(f"- Total R: {stats_a['total_r']} | Avg R: {stats_a['avg_r']}")
        report_lines.append(f"- Max drawdown (pts): {stats_a['max_drawdown_pts']}")
        report_lines.append(f"- Max drawdown (R): {stats_a['max_drawdown_r']}")
        report_lines.append(f"- Stop exits: {stats_a['stop_exits']} | Target exits: {stats_a['target_exits']} | EOD exits: {stats_a['eod_exits']}")
        report_lines.append(f"- Entry-candle exits: {stats_a['entry_candle_exits']}")
        report_lines.append(f"- Same-candle ambiguities: {stats_a['same_candle_ambiguities']}")
        report_lines.append(f"- Max trades per day: {stats_a['max_trades_per_day']}")
        report_lines.append(f"- Days with multiple trades: {stats_a['days_with_multi_trades']}")
        report_lines.append("")
        report_lines.append("### Direction Breakdown (Convention A)")
        for d in direction_summary(all_results[(inst, "A")]["trades"]):
            report_lines.append(f"- {d['direction']}: {d['trades']} trades, {d['wins']} wins, {d['win_rate']}% WR, {d['points']} pts")
        report_lines.append("")
        report_lines.append("### Monthly Summary (Convention A)")
        for m in monthly_summary(all_results[(inst, "A")]["trades"]):
            report_lines.append(f"- {m['month']}: {m['trades']} trades, {m['win_rate']}% WR, {m['points']} pts, {m['r']} R")
        report_lines.append("")

    with open(os.path.join(outdir, "research_report.md"), "w") as f:
        f.write("\n".join(report_lines))

    print("Outputs written.")


if __name__ == "__main__":
    main()
