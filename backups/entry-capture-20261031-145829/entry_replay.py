#!/usr/bin/env python3
"""Historical replay of all evaluated signals against the shadow entry resolver.

Read-only: never writes to the trading database. Uses only price data that
would have been knowable before the entry deadline (1m candle availability).
Writes a JSON report under logs/entry_shadow/.
"""
import json
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import entry_capture as ec  # noqa: E402


def load_signals():
    conn = ec.db_connect()
    try:
        conn.row_factory = __import__("sqlite3").Row
        rows = conn.execute(
            "SELECT signal_id, instrument_id, trade_date, direction, source_candle_ts, "
            "status, reference_price, reference_stop, reference_target, paper_trade_id, "
            "last_error, updated_at FROM scalp_signals ORDER BY trade_date, instrument_id, source_candle_ts"
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def load_trade(trade_id):
    if not trade_id:
        return None
    conn = ec.db_connect()
    try:
        conn.row_factory = __import__("sqlite3").Row
        r = conn.execute(
            "SELECT trade_id, instrument_id, direction, entry, stop, target, entry_time, "
            "exit_time, exit_price, exit_reason, paper_pnl, max_risk, status "
            "FROM paper_trades WHERE trade_id=? LIMIT 1", (trade_id,)
        ).fetchone()
    finally:
        conn.close()
    return dict(r) if r else None


def main():
    signals = load_signals()
    bars_cache = {}

    def bars_for(inst, day):
        key = (inst, day)
        if key not in bars_cache:
            bars_cache[key] = ec.yf_candles(inst, "1m", "7d", ttl_seconds=86400, day=day)
        return bars_cache[key]

    results = []
    for s in signals:
        sig_dt = ec.parse_ts(s["source_candle_ts"])
        entry_time = sig_dt + timedelta(minutes=ec.CANDLE_MINUTES)
        deadline = entry_time + timedelta(minutes=ec.ENTRY_WINDOW_MINUTES)
        day = sig_dt.strftime("%Y-%m-%d")
        bars = bars_for(s["instrument_id"], day)
        direction = (s["direction"] or "").upper()

        trade = load_trade(s["paper_trade_id"])
        actual_entry = None
        actual_fill_ts = None
        actual_sim = None
        recorded = None
        if trade:
            try:
                actual_entry = float(trade["entry"])
            except Exception:
                actual_entry = None
            actual_fill_ts = ec.parse_ts(trade.get("entry_time")) or entry_time
            if actual_entry is not None and trade.get("stop") is not None:
                actual_sim = ec.simulate(direction, actual_entry, float(trade["stop"]),
                                         actual_fill_ts, bars)
            recorded = {
                "status": trade.get("status"),
                "exit_reason": trade.get("exit_reason"),
                "exit_price": trade.get("exit_price"),
                "paper_pnl": trade.get("paper_pnl"),
                "entry": trade.get("entry"),
                "stop": trade.get("stop"),
                "target": trade.get("target"),
                "entry_time": trade.get("entry_time"),
            }

        # Shadow resolution, restricted to data available before the deadline.
        res = ec.resolve(s["instrument_id"], entry_time, deadline,
                         now=deadline - timedelta(seconds=1), historical=True)
        recovered = bool(res["resolved"])
        recovered_sim = None
        price_diff = None
        if recovered:
            ref = actual_entry if actual_entry is not None else (
                float(s["reference_price"]) if s.get("reference_price") is not None else None)
            if ref is not None:
                price_diff = res["price"] - ref
            if s.get("reference_stop") is not None:
                fill_ts = ec.parse_ts(res["fill_ts"]) or entry_time
                recovered_sim = ec.simulate(direction, res["price"],
                                            float(s["reference_stop"]), fill_ts, bars)

        results.append({
            "signal_id": s["signal_id"],
            "instrument": s["instrument_id"],
            "trade_date": s["trade_date"],
            "direction": direction,
            "signal_ts": s["source_candle_ts"],
            "entry_time": ec.iso(entry_time),
            "deadline": ec.iso(deadline),
            "status": s["status"],
            "last_error": s.get("last_error"),
            "reference_entry": s.get("reference_price"),
            "reference_stop": s.get("reference_stop"),
            "actual_entry": actual_entry,
            "actual_fill_ts": ec.iso(actual_fill_ts) if actual_fill_ts else None,
            "actual_sim": actual_sim,
            "recorded_trade": recorded,
            "shadow_resolved": recovered,
            "shadow_source": res.get("source"),
            "shadow_price": res.get("price"),
            "shadow_fill_ts": res.get("fill_ts"),
            "shadow_latency_s": res.get("latency_s"),
            "shadow_price_diff_points": round(price_diff, 4) if price_diff is not None else None,
            "shadow_sim": recovered_sim,
            "shadow_attempts": res.get("attempts"),
        })

    traded = [r for r in results if r["status"] == "TRADED"]
    ignored = [r for r in results if r["status"] == "IGNORED"]
    expired = [r for r in results if r["status"] == "EXPIRED"]
    recovered = [r for r in expired if r["shadow_resolved"]]
    unrecovered = [r for r in expired if not r["shadow_resolved"]]

    orig_rows = [r["actual_sim"] for r in traded if r["actual_sim"]]
    recovered_rows = [r["shadow_sim"] for r in recovered if r["shadow_sim"]]
    combined_rows = orig_rows + recovered_rows

    diffs = [abs(r["shadow_price_diff_points"]) for r in results
             if r["shadow_price_diff_points"] is not None]
    sources = {}
    for r in recovered:
        sources[r["shadow_source"]] = sources.get(r["shadow_source"], 0) + 1

    report = {
        "generated_at": ec.iso(ec.now_ist()),
        "counts": {
            "total": len(results), "traded": len(traded), "ignored": len(ignored),
            "expired": len(expired), "non_expired": len(traded) + len(ignored),
            "recovered": len(recovered), "unrecovered": len(unrecovered),
            "recovery_rate_pct": round(100.0 * len(recovered) / len(expired), 1) if expired else 0.0,
        },
        "shadow_source_breakdown": sources,
        "entry_price_diff_points": {
            "n": len(diffs),
            "mean_abs": round(sum(diffs) / len(diffs), 4) if diffs else None,
            "max_abs": round(max(diffs), 4) if diffs else None,
        },
        "outcomes": {
            "original_traded": ec.summarize("original_traded", orig_rows),
            "recovered_missed": ec.summarize("recovered_missed", recovered_rows),
            "combined": ec.summarize("combined", combined_rows),
            "original_traded_by_instrument": {
                inst: ec.summarize(inst, [r["actual_sim"] for r in traded
                                          if r["instrument"] == inst and r["actual_sim"]])
                for inst in ("NIFTY", "BANKNIFTY")
            },
            "recovered_by_instrument": {
                inst: ec.summarize(inst, [r["shadow_sim"] for r in recovered
                                          if r["instrument"] == inst and r["shadow_sim"]])
                for inst in ("NIFTY", "BANKNIFTY")
            },
        },
        "details": results,
    }

    ec.ensure_dirs()
    out = os.path.join(ec.SHADOW_DIR, "replay_" + datetime.now().strftime("%Y%m%d-%H%M%S") + ".json")
    with open(out, "w") as fh:
        json.dump(report, fh, indent=2, default=str)

    print("REPLAY REPORT:", out)
    print(json.dumps({k: report[k] for k in
                      ("counts", "shadow_source_breakdown", "entry_price_diff_points",
                       "outcomes")}, indent=2, default=str))

    print("\nPER-SIGNAL RECOVERED (expired -> would-be entry)")
    for r in recovered:
        sim = r["shadow_sim"] or {}
        print(f"  {r['trade_date']} {r['instrument']:9} {r['direction']:4} "
              f"sig={r['signal_ts'][11:16]} ref={r['reference_entry']} "
              f"shadow={r['shadow_price']} src={r['shadow_source']} "
              f"lat={r['shadow_latency_s']}s -> {sim.get('reason')} "
              f"{sim.get('points'):+.2f}pts {sim.get('R'):+.2f}R")
    if unrecovered:
        print("\nUNRECOVERED:")
        for r in unrecovered:
            print("  ", r["trade_date"], r["instrument"], r["signal_ts"], r["status"])


if __name__ == "__main__":
    main()
