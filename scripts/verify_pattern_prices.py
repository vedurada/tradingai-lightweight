#!/usr/bin/env python3
"""One-off verification: compare recorded pattern trades with Kite 1m candles."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone

from kiteconnect import KiteConnect

IST = timezone(timedelta(hours=5, minutes=30))
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


def main():
    c = creds()
    kite = KiteConnect(api_key=c["KITE_API_KEY"])
    kite.set_access_token(c["KITE_ACCESS_TOKEN"])

    day = sys.argv[1] if len(sys.argv) > 1 else "2026-11-18"
    start = f"{day} 09:15:00"
    end = f"{day} 15:30:00"

    # Spot 5m
    print("=== NIFTY spot 5m ===")
    try:
        rows = kite.historical_data(256265, start, end, "5minute")
        for r in rows:
            print(r["date"].strftime("%H:%M"), f'{r["open"]:.2f}',
                  f'{r["high"]:.2f}', f'{r["low"]:.2f}', f'{r["close"]:.2f}')
    except Exception as e:
        print("spot error:", e)

    # Option instruments
    wanted = sys.argv[2:] or ["NIFTY26NOV25250CE", "NIFTY26NOV25250PE"]
    inst = {}
    for i in kite.instruments("NFO"):
        if i.get("tradingsymbol") in wanted:
            inst[i["tradingsymbol"]] = i
    print("\n=== instruments ===")
    for s in wanted:
        print(s, inst.get(s, {}).get("instrument_token"))

    for sym in wanted:
        i = inst.get(sym)
        if not i:
            continue
        print(f"\n=== {sym} 1m ===")
        try:
            rows = kite.historical_data(i["instrument_token"], start, end, "minute")
        except Exception as e:
            print("error:", e)
            continue
        for r in rows:
            print(r["date"].strftime("%H:%M"), f'{r["open"]:.2f}',
                  f'{r["high"]:.2f}', f'{r["low"]:.2f}', f'{r["close"]:.2f}')


if __name__ == "__main__":
    main()
