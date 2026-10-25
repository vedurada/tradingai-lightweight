"""Read-only CPR replay using live-paper holding and outcome semantics."""
import json
from app.core.db import get_conn
from app.paper_trade.engine import LOT_SIZES, BROKERAGE_RS, SLIPPAGE_PTS
from app.research.cpr_trigger_engine import (
    OPEN_STOP_PCT, OPEN_TARGET_PCT, exits_opens, run_opens_range,
)

def _signed_points(direction, entry, exit_price):
    move = float(exit_price) - float(entry)
    return move if direction == "BULL" else -move


def _asof_entry_iso(trade):
    return f"{trade['trade_date']}T{trade['entry_time'][11:16]}:00+05:30"


def _row_outcome(row):
    if row.get("status") == "OPEN" or row.get("paper_pnl") is None:
        row["win_loss"] = None
        return row
    pnl = float(row["paper_pnl"])
    row["win_loss"] = "WIN" if pnl > 0 else ("LOSS" if pnl < 0 else "FLAT")
    return row


def run_live_paper_range(instrument, date_start, date_end):
    """Replay CPR entries with live-paper holding and outcomes.

    Signal selection comes from the canonical CPR trigger engine. Trades carry
    across sessions until the shared next-open STOP-first evaluator exits them.
    Recorded live-watch entries/exits override reconstructed trades by date.
    This function only reads the production database.
    """
    inst = (instrument or "").upper()
    base = run_opens_range(inst, date_start, date_end, "plain")
    if base.get("error"):
        return base

    conn = get_conn()
    try:
        cutoff = f"{base['date_end']}T23:59:59+05:30"
        candle_rows = conn.execute(
            "SELECT timestamp, open, close FROM market_candles_5m "
            "WHERE instrument_id=? AND timestamp BETWEEN ? AND ? ORDER BY timestamp",
            (inst, f"{base['date_start']}T00:00:00+05:30", cutoff),
        ).fetchall()
        candles = [dict(r) for r in candle_rows]
        candle_opens = [(r["timestamp"], r["open"]) for r in candle_rows]
        live_rows = conn.execute(
            "SELECT trade_id, scenario, direction, entry, stop, entry_time, exit_time, "
            "exit_price, exit_reason, paper_pnl, status, qualification_evidence "
            "FROM paper_trades WHERE instrument_id=? "
            "AND substr(entry_time,1,10) BETWEEN ? AND ? ORDER BY entry_time",
            (inst, base["date_start"], base["date_end"]),
        ).fetchall()
    finally:
        conn.close()

    by_date = {}
    allowed_live_levels = {'BEAR': {'SMA20_CLOSE_BELOW'},
                           'BULL': set()}
    asof_cutoff = f"{base['date_end']}T23:59:59.999999+05:30"
    for item in live_rows:
        live = dict(item)
        try:
            evidence = json.loads(live.get("qualification_evidence") or "{}")
        except (TypeError, ValueError):
            evidence = {}
        if evidence.get("origin") != "live-watch":
            continue
        day = live.get("entry_time", "")[:10]
        direction = "BULL" if str(live.get("direction", "")).upper() in ("BULL", "BULLISH", "LONG") else "BEAR"
        scenario = str(live.get("scenario") or "").upper()
        if scenario not in allowed_live_levels.get(direction, set()):
            continue
        entry = float(live.get("entry") or 0)
        stop = float(live.get("stop") or 0)
        cutoff_exit = live.get("exit_time")
        # Never include an exit recorded after the selected end date.
        closed_asof = bool(cutoff_exit and cutoff_exit <= asof_cutoff)
        if closed_asof and live.get("exit_price") is not None:
            exit_price = float(live["exit_price"])
            signed = _signed_points(direction, entry, exit_price)
            points = round(signed, 1)
            risk = abs(entry - stop)
            r_value = round(signed / risk, 3) if risk else None
            reason = live.get("exit_reason") or "CLOSED"
            exit_time = cutoff_exit
            pnl = float(live.get("paper_pnl") or 0)
            status = "CLOSED"
        else:
            marks = [r for r in candles if r["timestamp"] <= cutoff]
            mark = marks[-1] if marks else None
            exit_price = float(mark["close"]) if mark and mark.get("close") is not None else None
            points = round(_signed_points(direction, entry, exit_price), 1) if exit_price is not None else None
            risk = abs(entry - stop)
            r_value = round(_signed_points(direction, entry, exit_price) / risk, 3) if exit_price is not None and risk else None
            reason = "OPEN"
            exit_time = mark["timestamp"] if mark else None
            pnl = None
            status = "OPEN"
        row = {
            "trade_date": day, "direction": direction, "level": live.get("scenario") or "N/A",
            "entry_time": live.get("entry_time"), "entry": entry, "stop": stop,
            "exit_time": exit_time, "exit": exit_price, "points": points,
            "r_multiple": r_value, "exit_reason": reason, "paper_pnl": pnl,
            "status": status, "win_loss": None, "source": "LIVE PAPER",
            "trade_id": live.get("trade_id"),
        }
        by_date[day] = _row_outcome(row)

    # Reconstruct dates without a recorded live-watch trade, carrying through
    # all stored opens up to the selected end date.
    for trade in base.get("trades", []):
        day = trade["trade_date"]
        if day in by_date:
            continue
        entry = float(trade["entry"])
        direction = trade["direction"]
        entry_iso = _asof_entry_iso(trade)
        opens = [(ts, op) for ts, op in candle_opens if ts > entry_iso]
        hit = exits_opens(direction, entry, OPEN_STOP_PCT, OPEN_TARGET_PCT, opens)
        if hit:
            _hit_r, exit_price, reason, exit_time = hit
            exit_price = float(exit_price)
            signed = _signed_points(direction, entry, exit_price)
            points = round(signed, 1)
            risk_points = abs(entry * OPEN_STOP_PCT)
            r_value = round(signed / risk_points, 3) if risk_points else None
            lot = LOT_SIZES.get(inst, 65)
            pnl = round(signed * lot - BROKERAGE_RS - SLIPPAGE_PTS * lot, 2)
            status = "CLOSED"
        else:
            last = next((r for r in reversed(candles) if r["timestamp"] > entry_iso), None)
            exit_price = float(last["close"]) if last and last.get("close") is not None else None
            points = round(_signed_points(direction, entry, exit_price), 1) if exit_price is not None else None
            r_value, reason, exit_time, pnl, status = None, "OPEN", last["timestamp"] if last else None, None, "OPEN"
        stop = entry * (1 - OPEN_STOP_PCT if direction == "BULL" else 1 + OPEN_STOP_PCT)
        row = {
            **trade, "stop": stop, "exit": exit_price, "points": points,
            "r_multiple": r_value, "exit_reason": reason, "paper_pnl": pnl,
            "status": status, "source": "LIVE-PAPER REPLAY", "trade_id": None,
        }
        by_date[day] = _row_outcome(row)

    trades = sorted(by_date.values(), key=lambda t: (t["trade_date"], t["entry_time"] or ""))
    closed = [t for t in trades if t["status"] == "CLOSED"]
    wins = sum(t["win_loss"] == "WIN" for t in closed)
    losses = sum(t["win_loss"] == "LOSS" for t in closed)
    by_level = {}
    for t in trades:
        key = f"{t['direction']}/{t['level']}"
        group = by_level.setdefault(key, {"n": 0, "wins": 0, "R": 0.0, "open": 0})
        group["n"] += 1
        if t["status"] == "OPEN":
            group["open"] += 1
        else:
            group["wins"] += int(t["win_loss"] == "WIN")
            group["R"] = round(group["R"] + (t.get("r_multiple") or 0), 2)
    net_r_values = []
    for t in closed:
        risk_cash = abs(float(t.get("entry") or 0) - float(t.get("stop") or 0)) * LOT_SIZES.get(inst, 65)
        if risk_cash:
            net_r_values.append(float(t.get("paper_pnl") or 0) / risk_cash)
    net_r = round(sum(net_r_values), 2)
    base.update({
        "trades": trades, "signals": len(trades), "closed_trades": len(closed),
        "open_trades": len(trades) - len(closed), "wins": wins, "losses": losses,
        "win_rate": round(100 * wins / len(closed), 1) if closed else 0,
        "total_R": round(sum(t.get("r_multiple") or 0 for t in closed), 2),
        "avg_R": round(sum(t.get("r_multiple") or 0 for t in closed) / len(closed), 3) if closed else 0,
        "net_pnl_spot_proxy": round(sum(t.get("paper_pnl") or 0 for t in closed), 2),
        "net_R": net_r,
        "by_level": by_level,
        "execution_note": "Live-paper holding and net-P&L rules; source distinguishes recorded live trades from stored-candle replay. Underlying-price proxy, not option-premium P&L.",
    })
    return base
