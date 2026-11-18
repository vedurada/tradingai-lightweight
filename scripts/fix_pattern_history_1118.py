#!/usr/bin/env python3
"""Correct 2026-11-18 pattern-scanner history (dry-run by default).

Bugs being repaired:
  * entry_ts stored the signal candle's start, 5 minutes before the trade was
    actually placed. The real entry time is created_at (UTC) + 5:30.
  * after the ATM strike moved, some exits were priced off the opposite leg
    (or a stale quote). Those prices fall outside the position's own option
    candle range. Re-price only those rows from the option's own 1m candle.

Prices that already sit inside the position's own 1m candle range are left
alone. Pass --apply to write; otherwise only prints the plan.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime, timedelta, timezone

from kiteconnect import KiteConnect

IST = timezone(timedelta(hours=5, minutes=30))
DB = "/opt/tradingai/database/tradingai.db"
VM_ROOT = "/opt/tradingai"
DAY = "2026-11-18"


def creds():
    out = {}
    with open(f"{VM_ROOT}/.env.zerodha") as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip()
    return out


def kite_client():
    c = creds()
    k = KiteConnect(api_key=c["KITE_API_KEY"])
    k.set_access_token(c["KITE_ACCESS_TOKEN"])
    return k


def candle_for(candles, dt):
    """Candle for dt's minute, else the nearest within +/-2 minutes."""
    for delta in (0, -1, 1, -2, 2):
        m = (dt + timedelta(minutes=delta)).strftime("%H:%M")
        c = candles.get(m)
        if c:
            return c
    return None


def inside(candle, price):
    return candle is not None and candle["low"] <= price <= candle["high"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    kite = kite_client()
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM pattern_scanner_positions "
        "WHERE session_date=? AND status='closed' ORDER BY entry_ts",
        (DAY,)).fetchall()

    symbols = sorted({r["instrument"] for r in rows})
    tokens = {}
    for i in kite.instruments("NFO"):
        if i.get("tradingsymbol") in symbols:
            tokens[i["tradingsymbol"]] = i["instrument_token"]

    candles = {}
    for sym in symbols:
        tok = tokens.get(sym)
        if not tok:
            print("no token", sym)
            continue
        data = kite.historical_data(
            tok, f"{DAY} 09:15:00", f"{DAY} 15:30:00", "minute")
        candles[sym] = {c["date"].strftime("%H:%M"): c for c in data}

    fixes = []
    for r in rows:
        created = datetime.fromisoformat(r["created_at"]).replace(
            tzinfo=timezone.utc)
        entry_dt = created.astimezone(IST)
        new_entry_ts = entry_dt.isoformat()

        exit_dt = datetime.fromisoformat(r["exit_ts"])
        own = candles.get(r["instrument"], {})
        exit_price = r["exit_price"]
        repriced = False
        if not inside(candle_for(own, exit_dt), exit_price):
            c = candle_for(own, exit_dt)
            if c is not None:
                exit_price = round(float(c["close"]), 2)
                repriced = True

        pnl = round(float(exit_price) - float(r["entry_price"]), 2)
        secs = (exit_dt - entry_dt).total_seconds()
        holding = max(1, int(round(secs / 60.0))) if secs > 0 else 0

        changed = (new_entry_ts != r["entry_ts"]
                   or exit_price != r["exit_price"]
                   or pnl != r["pnl_points"]
                   or holding != r["holding_minutes"])
        if changed:
            fixes.append({
                "trade_id": r["trade_id"],
                "instrument": r["instrument"],
                "pattern": r["pattern_name"],
                "old_entry_ts": r["entry_ts"],
                "new_entry_ts": new_entry_ts,
                "old_exit": r["exit_price"],
                "new_exit": exit_price,
                "repriced": repriced,
                "old_pnl": r["pnl_points"],
                "new_pnl": pnl,
                "old_hold": r["holding_minutes"],
                "new_hold": holding,
            })

    repriced = sum(1 for f in fixes if f["repriced"])
    print(f"day={DAY} closed={len(rows)} rows_to_fix={len(fixes)} "
          f"repriced_exits={repriced}")
    for f in fixes:
        flag = "REPRICE" if f["repriced"] else "time-only"
        print(f"{flag} {f['instrument']} {f['pattern'][:28]:28} "
              f"entry {f['old_entry_ts'][11:19]}->{f['new_entry_ts'][11:19]} "
              f"exit {f['old_exit']}->{f['new_exit']} "
              f"pnl {f['old_pnl']}->{f['new_pnl']} "
              f"hold {f['old_hold']}->{f['new_hold']}")

    if not args.apply:
        print("\ndry run; re-run with --apply to write")
        conn.close()
        return

    conn.execute("BEGIN")
    for f in fixes:
        conn.execute(
            "UPDATE pattern_scanner_positions SET entry_ts=?, exit_price=?, "
            "pnl_points=?, gross_pnl_points=?, holding_minutes=?, "
            "updated_at=datetime('now') WHERE trade_id=?",
            (f["new_entry_ts"], f["new_exit"], f["new_pnl"], f["new_pnl"],
             f["new_hold"], f["trade_id"]))
    conn.commit()
    total = conn.execute(
        "SELECT COUNT(*), ROUND(SUM(pnl_points),2) FROM pattern_scanner_positions "
        "WHERE session_date=? AND status='closed'", (DAY,)).fetchone()
    conn.close()
    print(f"\napplied {len(fixes)} updates; day totals now trades={total[0]} "
          f"pnl={total[1]}")


if __name__ == "__main__":
    sys.exit(main())
