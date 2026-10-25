"""Thin wrapper exposing the isolated previous-day price-action research as a backtest engine."""
import os
import sys

RESEARCH_DIR = "/opt/tradingai/research/nifty_prevday_price_action"
if RESEARCH_DIR not in sys.path:
    sys.path.insert(0, RESEARCH_DIR)

import run_research as _rr


def run_prevday_pa_range(instrument, date_start, date_end):
    inst = (instrument or "").upper()
    if inst != "NIFTY":
        return {"error": "UNKNOWN_INSTRUMENT"}
    import sqlite3
    from collections import OrderedDict
    # load candles for range
    conn = sqlite3.connect(_rr.DB_PATH if hasattr(_rr, "DB_PATH") else "/opt/tradingai/database/tradingai.db")
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT timestamp, open, high, low, close FROM market_candles_5m "
        "WHERE instrument_id=? AND substr(timestamp,1,10) BETWEEN ? AND ? ORDER BY timestamp",
        (inst, date_start, date_end),
    ).fetchall()
    conn.close()
    candles = []
    for r in rows:
        ts = r["timestamp"]
        dt = __import__("datetime").datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=__import__("zoneinfo").ZoneInfo("Asia/Kolkata"))
        candles.append({"timestamp": ts, "dt": dt, "date": ts[:10], "time": ts[11:16],
                        "open": float(r["open"]), "high": float(r["high"]),
                        "low": float(r["low"]), "close": float(r["close"])})

    sessions = OrderedDict()
    for c in candles:
        sessions.setdefault(c["date"], []).append(c)

    session_list = list(sessions.keys())
    ctxs = {}
    for i, d in enumerate(session_list):
        if i == 0:
            ctxs[d] = None
        else:
            ctxs[d] = _rr.prev_context(sessions[session_list[i - 1]])

    signal_log, all_setups, trades = _rr.simulate_trades(sessions, ctxs)

    wins = sum(1 for t in trades if t["points"] > 0)
    by_level = {}
    for t in trades:
        key = t.get("trigger") or "UNKNOWN"
        g = by_level.setdefault(key, {"n": 0, "wins": 0, "open": 0, "R": 0.0})
        g["n"] += 1
        if t["points"] > 0:
            g["wins"] += 1
        g["R"] = round(g["R"] + t["r_multiple"], 2)
    return {
        "instrument": inst,
        "variant": "prevday_pa",
        "date_start": date_start,
        "date_end": date_end,
        "days": len(sessions),
        "signals": len(trades),
        "wins": wins,
        "losses": sum(1 for t in trades if t["points"] < 0),
        "win_rate": round(100.0 * wins / len(trades), 1) if trades else 0,
        "total_R": round(sum(t["r_multiple"] for t in trades), 2),
        "avg_R": round(sum(t["r_multiple"] for t in trades) / len(trades), 3) if trades else 0,
        "total_points": round(sum(t["points"] for t in trades), 2),
        "trades": trades,
        "by_level": by_level,
        "execution_note": "Previous-day price action strategy; entry at touched setup level; one trade per day; EOD exit 15:20 open.",
    }


def run_price_action_target_range(instrument, date_start, date_end):
    """Price Action Target: same setups as prevday PA, but exits at first rejection."""
    inst = (instrument or "").upper()
    if inst != "NIFTY":
        return {"error": "UNKNOWN_INSTRUMENT"}
    import sys, os, sqlite3
    from collections import OrderedDict
    from datetime import datetime
    import zoneinfo
    IST = zoneinfo.ZoneInfo("Asia/Kolkata")
    DB_PATH = os.environ.get("TRADINGAI_DB_PATH", os.path.join("/opt/tradingai", "database", "tradingai.db"))
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT timestamp, open, high, low, close FROM market_candles_5m "
        "WHERE instrument_id=? AND substr(timestamp,1,10) BETWEEN ? AND ? ORDER BY timestamp",
        (inst, date_start, date_end),
    ).fetchall()
    conn.close()
    candles = []
    for r in rows:
        ts = r["timestamp"]
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=IST)
        candles.append({"timestamp": ts, "dt": dt, "date": ts[:10], "time": ts[11:16],
                        "open": float(r["open"]), "high": float(r["high"]),
                        "low": float(r["low"]), "close": float(r["close"])})
    sessions = OrderedDict()
    for c in candles:
        sessions.setdefault(c["date"], []).append(c)
    session_list = list(sessions.keys())
    ctxs = {}
    for i, d in enumerate(session_list):
        ctxs[d] = None if i == 0 else _rr.prev_context(sessions[session_list[i - 1]])
    _, all_setups, trades = _rr.simulate_trades(sessions, ctxs, exit_mode="rejection")
    wins = sum(1 for t in trades if t["points"] > 0)
    by_level = {}
    for t in trades:
        key = t.get("trigger") or "UNKNOWN"
        g = by_level.setdefault(key, {"n": 0, "wins": 0, "open": 0, "R": 0.0})
        g["n"] += 1
        if t["points"] > 0:
            g["wins"] += 1
        g["R"] = round(g["R"] + t["r_multiple"], 2)
    return {
        "instrument": inst, "variant": "price_action_target",
        "date_start": date_start, "date_end": date_end,
        "days": len(sessions), "signals": len(trades),
        "wins": wins, "losses": sum(1 for t in trades if t["points"] < 0),
        "win_rate": round(100.0 * wins / len(trades), 1) if trades else 0,
        "total_R": round(sum(t["r_multiple"] for t in trades), 2),
        "avg_R": round(sum(t["r_multiple"] for t in trades) / len(trades), 3) if trades else 0,
        "total_points": round(sum(t["points"] for t in trades), 2),
        "trades": trades, "by_level": by_level,
        "execution_note": "Price Action Target: entry at touched level; exit at first rejection; one trade per day.",
    }
