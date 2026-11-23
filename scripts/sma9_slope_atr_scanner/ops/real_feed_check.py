#!/usr/bin/env python3
"""Read-only real-feed check for the deployed sma9_slope_atr scanner.

Exercises the live Kite path the scanner will use from 09:00 tomorrow (09:15 exchange open):
instrument dump -> nearest expiry -> ATM CE/PE contracts -> quotes ->
5-minute candles -> SMA9 evaluation -> ATR stop preview.

Writes nothing (no DB, no orders).
"""

import sys

sys.path.insert(0, "/opt/tradingai/sma9_slope_atr_scanner")

from app.live_sma9_slope_atr_scanner import (  # noqa: E402
    ATR_PERIOD,
    KiteFeed,
    compute_stop,
    evaluate_option,
    premium_atr,
)

FAILS = []


def check(label, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    if not cond:
        FAILS.append(label)


def main():
    feed = KiteFeed()
    feed.refresh_instruments()
    n = len(feed._instruments)
    check("NFO NIFTY option instruments loaded", n > 0, n)

    expiry = feed.nearest_expiry()
    check("nearest expiry resolved", expiry is not None, expiry)

    quotes = feed.quote(["NSE:NIFTY 50"])
    spot = float(quotes["NSE:NIFTY 50"]["last_price"])
    atm = float(round(spot / 50) * 50)
    check("NIFTY spot quoted", spot > 0, spot)
    check("ATM strike derived", atm > 0, atm)

    contracts = {}
    for opt in ("CE", "PE"):
        c = feed.find_contract(atm, expiry, opt)
        contracts[opt] = c
        check(f"ATM {opt} contract exists for {expiry}", c is not None,
              (c or {}).get("tradingsymbol"))

    symbols = [f"NFO:{c['tradingsymbol']}" for c in contracts.values() if c]
    opt_quotes = feed.quote(symbols) if symbols else {}

    for opt, c in contracts.items():
        if not c:
            continue
        sym = f"NFO:{c['tradingsymbol']}"
        ltp = opt_quotes.get(sym, {}).get("last_price")
        check(f"{opt} LTP quoted", ltp is not None, ltp)

        rows = feed.candles(int(c["instrument_token"]), force=True)
        check(f"{opt} 5m candles available", len(rows) >= 15, len(rows))
        if len(rows) < 15:
            continue
        atr = premium_atr(rows, ATR_PERIOD)
        check(f"{opt} premium ATR(14) computable", atr is not None, atr)

        ev = evaluate_option(rows, opt, ltp)
        check(f"{opt} SMA9 evaluated", ev.sma9 is not None, ev.sma9)
        check(f"{opt} prior SMA9 available for slope filter",
              ev.prev_sma9 is not None, ev.prev_sma9)

        if ltp and atr:
            stop, dist, pct, src = compute_stop(float(ltp), atr)
            check(f"{opt} ATR stop preview valid",
                  stop < float(ltp) and 0.05 - 1e-9 <= pct <= 0.30 + 1e-9,
                  f"ltp={ltp} stop={stop} dist={round(pct*100,2)}% src={src}")
        print(f"        {opt}: ltp={ltp} sma9={ev.sma9} prev_sma9={ev.prev_sma9} "
              f"A={ev.condition_a} B={ev.condition_b} C={ev.condition_c} "
              f"signal={ev.signal} reason={ev.reason}")

    print("\n" + "=" * 68)
    if FAILS:
        print(f"REAL-FEED CHECK FAILED: {FAILS}")
        return 1
    print(f"REAL-FEED CHECK PASSED (spot={spot}, ATM={atm}, expiry={expiry})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
