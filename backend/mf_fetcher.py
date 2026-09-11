from __future__ import annotations

"""Indian Mutual Fund feed: AMFI daily snapshot + mfapi.in NAV history for rankings.

Cron:
  35 19 * * * cd /opt/tradingai/backend && /usr/bin/python3 mf_fetcher.py            # nightly NAV snapshot
  30 7 * * 0  cd /opt/tradingai/backend && /usr/bin/python3 mf_fetcher.py --returns  # weekly returns refresh

Usage: python3 mf_fetcher.py [--returns]
"""

import os
import sqlite3
import urllib.request
from datetime import date, datetime, timedelta, timezone

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "database", "tradingai.db")
AMFI_URL = "https://portal.amfiindia.com/spages/NAVAll.txt"
MFAPI_SCHEME = "https://api.mfapi.in/mf/{code}"
MF_RETURNS_REFRESH_DAYS = 6
HTTP_TIMEOUT = 40
UA = "tradingai-mf-fetcher/1.0 (market intel)"

CATEGORY_ORDER = ["Large Cap", "Flexi Cap", "Mid Cap", "Small Cap", "Multi Cap", "ELSS", "Index", "Value", "Balanced Advantage", "Liquid"]

# watchlist: fund-name substrings per bucket (case-insensitive LIKE). Direct Growth preferred.
WATCHLIST = {
    "Large Cap": ["HDFC Top 100", "SBI Blue Chip", "Mirae Asset Large Cap", "ICICI Prudential Bluechip",
                  "Axis Bluechip", "Nippon India Large Cap", "Kotak Bluechip", "UTI Equity Fund",
                  "Canara Robeco Bluechip"],
    "Flexi Cap": ["Parag Parikh Flexi Cap", "Quant Flexi Cap", "HDFC Flexi Cap", "UTI Flexi Cap",
                  "Axis Flexi Cap", "JM Flexicap"],
    "Mid Cap": ["Kotak Emerging Equity", "HDFC Mid-Cap Opportunities", "DSP Midcap", "Quant Mid Cap",
                "Nippon India Growth Fund", "Sundaram Mid Cap"],
    "Small Cap": ["Quant Small Cap", "HDFC Small Cap Fund", "Nippon India Small Cap", "SBI Small Cap",
                  "Kotak Small Cap"],
    "ELSS": ["HDFC ELSS Tax", "Mirae Asset ELSS", "Axis ELSS Tax", "DSP Tax Saver",
             "Canara Robeco Equity Tax Saver", "SBI Long Term Equity", "Quant ELSS Tax"],
    "Index": ["UTI Nifty 50 Index", "SBI Nifty 50 Index Fund", "HDFC Index Fund - Nifty 50",
              "ICICI Prudential Nifty 50 Index", "Tata Nifty 50 Index", "Nippon India Index Fund - Nifty 50"],
    "Value": ["UTI Value Opportunities", "HDFC Capital Builder Value", "ICICI Prudential Value Discovery",
              "SBI Magnum Value Fund", "Tata Equity PE"],
    "Balanced Advantage": ["ICICI Prudential Balanced Advantage", "HDFC Balanced Advantage",
                           "SBI Balanced Advantage Fund", "UTI Balanced Advantage", "Axis Balanced Advantage"],
    "Liquid": ["HDFC Liquid Fund", "SBI Liquid Fund", "ICICI Prudential Liquid Fund", "Axis Liquid Fund",
               "Kotak Liquid Fund", "Parag Parikh Liquid Fund"],
}

AMC_PREFIXES = [
    "SBI Mutual", "HDFC Mutual", "ICICI Prudential", "Axis Mutual", "Kotak Mahindra", "Mirae Asset",
    "Nippon India", "UTI", "Quant", "DSP", "Parag Parikh", "Canara Robeco", "Sundaram", "Tata",
    "Aditya Birla Sun Life", "Franklin", "Motilal Oswal", "Mahindra Manulife", "Invesco", "Edelweiss",
    "Baroda", "White Oak", "360 One", "Bank of India",
]


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as r:
        return r.read()


def _to_float(v):
    if v is None:
        return None
    try:
        v = str(v).replace(",", "").strip()
        return float(v) if v else None
    except Exception:
        return None


def fund_house(name: str) -> str:
    low = (name or "").lower()
    for amc in AMC_PREFIXES:
        if low.startswith(amc.lower()):
            return name[: len(amc)]
    return name.split(" ")[0] if name else ""


def classify(amfi_type: str, name: str) -> str:
    t = amfi_type or ""
    if "ELSS" in t:
        return "ELSS"
    if "Flexi Cap" in t:
        return "Flexi Cap"
    if "Large Cap" in t:
        return "Large Cap"
    if "Mid Cap" in t:
        return "Mid Cap"
    if "Small Cap" in t:
        return "Small Cap"
    if "Multi Cap" in t:
        return "Multi Cap"
    if "Value" in t:
        return "Value"
    if "Balanced Advantage" in t:
        return "Balanced Advantage"
    if "Index" in t:
        return "Index"
    if "Liquid" in t:
        return "Liquid"
    return t.split(":")[-1].strip().replace(" Fund", "") if t else "Other"


def fetch_amfi() -> list[dict]:
    text = _get(AMFI_URL).decode("utf-8", errors="replace")
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line or ";" not in line:
            continue
        p = [x.strip() for x in line.split(";")]
        if len(p) < 9 or not (p[0] or "").isdigit():
            continue
        nav = _to_float(p[5])
        if nav is None:
            continue
        out.append({"code": p[0], "name": p[4], "nav": nav, "nav_date": p[6], "setting": p[7], "amfi_type": p[8]})
    return out


def import_amfi(conn: sqlite3.Connection, rows: list[dict]) -> int:
    now = datetime.now(timezone.utc).isoformat()
    n = 0
    for r in rows:
        name = r["name"]
        direct = 1 if ("direct" in name.lower()) else 0
        cat = classify(r["amfi_type"], name)
        conn.execute(
            "INSERT OR REPLACE INTO mf_schemes (scheme_code, scheme_name, fund_house, scheme_type, scheme_setting,"
            " is_direct, category, amfi_category, nav, nav_date, imported_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (r["code"], name, fund_house(name), r["amfi_type"], r["setting"], direct, cat, r["amfi_type"],
             r["nav"], r["nav_date"], now),
        )
        n += 1
    conn.commit()
    return n


def pick_watchlist(conn: sqlite3.Connection) -> list[tuple[str, str]]:
    import json as _json
    picked = []
    for cat, subs in WATCHLIST.items():
        seen = set()
        for sub in subs:
            rows = conn.execute(
                "SELECT scheme_code, scheme_name, scheme_setting FROM mf_schemes WHERE lower(scheme_name) LIKE ? AND category=?",
                (f"%{sub.lower()}%", cat),
            ).fetchall()
            best = None
            for r in rows:
                setting = (r["scheme_setting"] or "").lower()
                if "growth" in setting and "direct" in setting:
                    best = r
                    break
            if best is None:
                for r in rows:
                    if "growth" in (r["scheme_setting"] or "").lower():
                        best = r
                        break
            if best is None and rows:
                best = rows[0]
            if best is not None and best["scheme_code"] not in seen:
                seen.add(best["scheme_code"])
                picked.append((best["scheme_code"], best["scheme_name"]))
    return picked


def _nav_at(hist, days_back: int):
    """Return (date, nav) closest to target date within tolerance."""
    target = date.today() - timedelta(days=days_back)
    best = None
    for item in hist:
        try:
            d = datetime.strptime(item["date"], "%d-%m-%Y").date()
        except Exception:
            continue
        diff = (d - target).days
        if diff <= 3 and diff >= -60:
            nav = _to_float(item["nav"])
            if nav and nav > 0:
                return d, nav
        if d < target - timedelta(days=days_back + 400):
            break
    return None


def compute_returns(hist: list[dict], nav_now: float) -> dict:
    out = {}
    for key, days in (("ret_1y", 365), ("ret_3y", 1095), ("ret_5y", 1825)):
        res = _nav_at(hist, days)
        if res is None or not nav_now or nav_now <= 0:
            out[key] = None
            out[key + "_from"] = None
            continue
        d0, nav0 = res
        span = max((date.today() - d0).days, 1)
        growth = (nav_now / nav0) ** (365.0 / span) - 1
        out[key] = round(growth * 100, 2)
        out[key + "_from"] = d0.isoformat()
    return out


def refresh_returns(conn: sqlite3.Connection) -> int:
    import json as _json
    picked = pick_watchlist(conn)
    now = datetime.now(timezone.utc).isoformat()
    done = 0
    for code, name in picked:
        try:
            raw = _get(MFAPI_SCHEME.format(code=code))
            d = _json.loads(raw)
            hist = d.get("data") or []
            meta = d.get("meta") or {}
            if not hist:
                continue
            nav_now = _to_float(hist[0]["nav"])
            rets = compute_returns(hist, nav_now)
            conn.execute(
                "INSERT OR REPLACE INTO mf_returns (scheme_code, scheme_name, fund_house, category, nav, nav_date,"
                " ret_1y, ret_3y, ret_5y, ret_days_1y, expected_from, computed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (str(code), meta.get("scheme_name") or name, fund_house(meta.get("scheme_name") or name),
                 meta.get("scheme_category") or "", nav_now, hist[0]["date"],
                 rets.get("ret_1y"), rets.get("ret_3y"), rets.get("ret_5y"),
                 (date.today() - date.fromisoformat(rets.get("ret_1y_from") or date.today().isoformat())).days,
                 rets.get("ret_1y_from"), now),
            )
            conn.commit()
            done += 1
            print(f"  ok {code} {meta.get('scheme_name') or name} 1Y={rets.get('ret_1y')}")
        except Exception as e:
            print(f"  ERR {code} {name}: {e}")
    return done


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--returns", action="store_true", help="refresh returns via mfapi.in")
    args = ap.parse_args()

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row

    try:
        print("fetching AMFI NAV snapshot...")
        rows = fetch_amfi()
        n = import_amfi(conn, rows)
        print(f"imported {n} schemes (rev {date.today().isoformat()})")

        do_returns = args.returns
        if not do_returns:
            last = conn.execute("SELECT MAX(computed_at) m FROM mf_returns").fetchone()
            last_dt = None
            if last and last["m"]:
                try:
                    last_dt = datetime.fromisoformat(str(last["m"]).replace("Z", "+00:00"))
                except Exception:
                    last_dt = None
            age_days = (datetime.now(timezone.utc) - last_dt).days if last_dt else 999
            do_returns = age_days > MF_RETURNS_REFRESH_DAYS
            print(f"returns age={age_days}d refresh={'yes' if do_returns else 'no'}")

        if do_returns:
            print("refreshing watchlist returns via mfapi.in...")
            done = refresh_returns(conn)
            print(f"returns computed for {done} schemes")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
