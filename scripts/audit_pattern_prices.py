#!/usr/bin/env python3
"""Audit pattern-scanner entry/exit prices against Kite 1-minute candles."""
from __future__ import annotations

import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from kiteconnect import KiteConnect

IST = timezone(timedelta(hours=5, minutes=30))
DB = "/opt/tradingai/database/tradingai.db"
VM_ROOT = "/opt/tradingai"


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


def main():
    day = sys.argv[1] if len(sys.argv) > 1 else "2026-11-18"
    kite = kite_client()

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM pattern_scanner_positions "
        "WHERE session_date=? AND status='closed' ORDER BY entry_ts",
        (day,)).fetchall()
    conn.close()

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
        try:
            data = kite.historical_data(
                tok, f"{day} 09:15:00", f"{day} 15:30:00", "minute")
        except Exception as e:
            print("hist error", sym, e)
            continue
        candles[sym] = {c["date"].strftime("%H:%M"): c for c in data}

    def minute(iso):
        dt = datetime.fromisoformat(iso)
        return dt.strftime("%H:%M")

    def check(sym, iso, price, label, window=1):
        dt = datetime.fromisoformat(iso)
        for delta in range(-window, window + 1):
            m = (dt + timedelta(minutes=delta)).strftime("%H:%M")
            c = candles.get(sym, {}).get(m)
            if c and c["low"] <= price <= c["high"]:
                return "ok"
        return "OUTSIDE"

    bad_entry = 0
    bad_exit = 0
    bad_exit_rows = []
    bad_entry_rows = []
    for r in rows:
        # actual entry time = created_at (UTC) converted to IST
        created = datetime.fromisoformat(r["created_at"]).replace(tzinfo=timezone.utc)
        actual_entry = created.astimezone(IST)
        e = check(r["instrument"], actual_entry.isoformat(), r["entry_price"], "entry")
        x = check(r["instrument"], r["exit_ts"], r["exit_price"], "exit")
        if e != "ok":
            bad_entry += 1
            bad_entry_rows.append((actual_entry.strftime("%H:%M:%S"), r["instrument"],
                                   r["entry_price"], e, r["entry_ts"][11:19]))
        if x != "ok":
            bad_exit += 1
            bad_exit_rows.append((r["exit_ts"][11:19], r["instrument"], r["entry_price"],
                                  r["exit_price"], r["exit_reason"], x))

    print(f"day={day} closed={len(rows)} symbols={len(symbols)}")
    print(f"entry price outside actual minute range: {bad_entry}")
    print(f"exit  price outside actual minute range: {bad_exit}")
    print("\n-- bad exits (first 25) --")
    for row in bad_exit_rows[:25]:
        print(row)
    print("\n-- bad entries (first 15) --")
    for row in bad_entry_rows[:15]:
        print(row)


if __name__ == "__main__":
    main()
