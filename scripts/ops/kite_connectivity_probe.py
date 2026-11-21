#!/usr/bin/env python3
"""Read-only Zerodha connectivity probe for the live paper scanners.

Proves that the shared access token and the per-service-user file access both
work, without writing any DB row and without placing an order.

Run on the VM:

    # full path: auth -> instruments -> spot/option quotes -> 5m candles
    sudo runuser -u ubuntu -g ubuntu -- python3 /opt/tradingai/scripts/ops/kite_connectivity_probe.py

    # per-scanner user: credentials readable + token accepted
    for u in sma9 sma95min sma9high sma91m sma95satr sma9trail sma9trailhigh; do
      sudo runuser -u "$u" -g ubuntu -- \
        python3 /opt/tradingai/scripts/ops/kite_connectivity_probe.py --light
    done

`--light` only calls `profile()` (no instrument dump), so the loop stays well
inside the Kite rate limits.

The access token is read once at process start by every scanner, so a token
refresh must be followed by a restart. `/opt/tradingai/refresh_token.sh` does
that for the 8 paper scanners, the API and `pattern-scanner-live`.
"""
import os
import sys
from datetime import datetime, timedelta, timezone

from kiteconnect import KiteConnect

ENV_PATH = "/opt/tradingai/.env.zerodha"
IST = timezone(timedelta(hours=5, minutes=30))
fails = []


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    if not ok:
        fails.append(label)


def load_env(path=ENV_PATH):
    creds = {}
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            creds[k.strip()] = v.strip().strip('"').strip("'")
    return creds


def main():
    light = "--light" in sys.argv
    print(f"user={os.environ.get('USER', '?')} uid={os.getuid()} gid={os.getgid()} "
          f"mode={'light' if light else 'full'}")

    creds = load_env()
    check("credentials file readable",
          "KITE_API_KEY" in creds and "KITE_ACCESS_TOKEN" in creds)

    kite = KiteConnect(api_key=creds["KITE_API_KEY"])
    kite.set_access_token(creds["KITE_ACCESS_TOKEN"])

    try:
        prof = kite.profile()
        check("authenticated (profile)", True,
              f"user_id={prof.get('user_id')} name={prof.get('user_name')}")
    except Exception as exc:
        check("authenticated (profile)", False, repr(exc)[:160])
        print("PROBE FAILED")
        return 1

    if light:
        print("PROBE PASSED (light)")
        return 0

    try:
        inst = [i for i in kite.instruments("NFO")
                if i.get("name") == "NIFTY" and i.get("instrument_type") in ("CE", "PE")]
        check("instrument dump (NFO NIFTY options)", len(inst) > 0, len(inst))
    except Exception as exc:
        check("instrument dump (NFO NIFTY options)", False, repr(exc)[:160])
        print("PROBE FAILED")
        return 1

    now = datetime.now(IST)
    today = now.date()
    expiries = sorted({i["expiry"] for i in inst if i["expiry"] >= today})
    expiry = expiries[0] if expiries else None
    check("nearest expiry", expiry is not None, expiry)

    try:
        spot = float(kite.quote(["NSE:NIFTY 50"])["NSE:NIFTY 50"]["last_price"])
        check("spot quote", spot > 0, spot)
    except Exception as exc:
        check("spot quote", False, repr(exc)[:160])
        print("PROBE FAILED")
        return 1

    atm = round(spot / 50.0) * 50.0
    contracts = {}
    for opt in ("CE", "PE"):
        matches = [i for i in inst if i["strike"] == atm and i["expiry"] == expiry
                   and i["instrument_type"] == opt]
        contracts[opt] = matches[0] if matches else None
        check(f"ATM {opt} contract", contracts[opt] is not None,
              contracts[opt]["tradingsymbol"] if contracts[opt] else None)

    syms = ["NSE:NIFTY 50"] + [f"NFO:{c['tradingsymbol']}"
                               for c in contracts.values() if c]
    try:
        quotes = kite.quote(syms)
        for sym in syms[1:]:
            check(f"quote {sym.split(':')[1]}",
                  sym in quotes and quotes[sym].get("last_price") is not None,
                  quotes.get(sym, {}).get("last_price"))
    except Exception as exc:
        check("option quotes", False, repr(exc)[:160])

    ce = contracts.get("CE")
    if ce:
        try:
            rows = kite.historical_data(int(ce["instrument_token"]),
                                        now - timedelta(days=3), now, "5minute")
            check("5m candles (CE)", len(rows) > 0, len(rows))
        except Exception as exc:
            check("5m candles (CE)", False, repr(exc)[:160])

    print("PROBE PASSED" if not fails else f"PROBE FAILED: {fails}")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
