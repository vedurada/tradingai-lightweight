from __future__ import annotations

"""NSE F&O EOD bhavcopy → option_chain + oi_top_strikes + PCR/max-pain.

URL: BhavCopy_NSE_FO_0_0_0_YYYYMMDD_F_0000.csv.zip
Columns: TckrSymb, XpryDt, StrkPric, OptnTp (CE/PE), OpnIntrst, ChngInOpnIntrst, TtlTradgVol, LastPric, etc.

Usage:
    python3 fo_fetcher.py daily          # latest session (cron 18:40)
    python3 fo_fetcher.py backfill [d]   # last d days (default 5)
"""

import csv
import io
import logging
import os
import sqlite3
import sys
import urllib.request
import zipfile
from datetime import date, datetime, timedelta, timezone

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "database", "tradingai.db")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0"}
INDEX_SYMBOLS = {"NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX"}
# NSE FO bhavcopy URL (works for all dates since ~2020)
BHAV_URL = "https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_{ymd}_F_0000.csv.zip"
TOP_N = 10  # top OI strikes per side per symbol/expiry

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("tradingai.fo")


def _get(url: str, timeout: int = 30) -> bytes | None:
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except Exception as e:
        log.warning("download skip %s: %s", url.split("/")[-1], e)
        return None


def _num(v) -> float | None:
    try:
        s = str(v).strip().replace(",", "")
        if s in ("", "-", "--"):
            return None
        return float(s)
    except Exception:
        return None


def _conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def fetch_fo_day(day: date) -> list[dict]:
    ymd = day.strftime("%Y%m%d")
    raw = _get(BHAV_URL.format(ymd=ymd))
    if not raw:
        return []
    try:
        z = zipfile.ZipFile(io.BytesIO(raw))
        text = z.read(z.namelist()[0]).decode("utf-8", errors="ignore")
    except Exception as e:
        log.warning("zip parse skip %s: %s", day, e)
        return []
    rows = []
    for row in csv.DictReader(text.splitlines()):
        opt = row.get("OptnTp", "")
        if opt not in ("CE", "PE"):
            continue
        oi = _num(row.get("OpnIntrst"))
        if oi is None or oi <= 0:
            continue
        rows.append({
            "symbol": (row.get("TckrSymb") or "").strip(),
            "expiry": (row.get("XpryDt") or "").strip(),
            "strike": _num(row.get("StrkPric")),
            "option_type": opt,
            "last_price": _num(row.get("LastPric")),
            "volume": int(_num(row.get("TtlTradgVol")) or 0),
            "open_interest": int(oi),
            "change_in_oi": int(_num(row.get("ChngInOpnIntrst")) or 0),
            "underlying": _num(row.get("UndrlygPric")),
            "close": _num(row.get("ClsPric")),
            "iv": None,
        })
    return rows


def store_option_chain(conn: sqlite3.Connection, day: date, rows: list[dict]) -> int:
    now = datetime.now(timezone.utc).isoformat()
    n = 0
    for r in rows:
        conn.execute(
            "INSERT OR REPLACE INTO option_chain"
            " (symbol, expiry, strike, option_type, last_price, bid, ask, volume, open_interest,"
            "  change_in_oi, implied_volatility, bid_size, ask_size, fetched_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (r["symbol"], r["expiry"], r["strike"], r["option_type"], r["last_price"],
             None, None, r["volume"], r["open_interest"], r["change_in_oi"],
             None, None, None, now))
        n += 1
    conn.commit()
    return n


def compute_oi_top_strikes(conn: sqlite3.Connection) -> int:
    """For each (symbol, expiry, side), rank strikes by OI and store top N."""
    conn.execute("DELETE FROM oi_top_strikes")
    now = datetime.now(timezone.utc).isoformat()
    n = 0
    groups = conn.execute(
        "SELECT symbol, expiry, option_type FROM option_chain"
        " GROUP BY symbol, expiry, option_type"
    ).fetchall()
    for g in groups:
        rows = conn.execute(
            "SELECT strike, open_interest FROM option_chain"
            " WHERE symbol=? AND expiry=? AND option_type=?"
            " ORDER BY open_interest DESC LIMIT ?",
            (g["symbol"], g["expiry"], g["option_type"], TOP_N)
        ).fetchall()
        for rank, r in enumerate(rows, 1):
            conn.execute(
                "INSERT INTO oi_top_strikes (symbol, expiry, side, rank, strike, open_interest, fetched_at)"
                " VALUES (?,?,?,?,?,?,?)",
                (g["symbol"], g["expiry"], g["option_type"], rank, r["strike"], r["open_interest"], now))
            n += 1
    conn.commit()
    return n


def compute_pcr_maxpain(conn: sqlite3.Connection) -> dict:
    """Compute PCR and max-pain per symbol per expiry for index options."""
    out = {}
    for sym in INDEX_SYMBOLS:
        expiries = conn.execute(
            "SELECT DISTINCT expiry FROM option_chain WHERE symbol=? ORDER BY expiry", (sym,)
        ).fetchall()
        sym_data = []
        for exp_row in expiries:
            expiry = exp_row["expiry"]
            chain = conn.execute(
                "SELECT strike, option_type, open_interest FROM option_chain"
                " WHERE symbol=? AND expiry=?",
                (sym, expiry)
            ).fetchall()
            pe_oi = sum(r["open_interest"] for r in chain if r["option_type"] == "PE")
            ce_oi = sum(r["open_interest"] for r in chain if r["option_type"] == "CE")
            pcr = round(pe_oi / ce_oi, 3) if ce_oi > 0 else None
            # Max pain: strike where total PE+CE OI at expiry is minimized
            strike_oi = {}
            for r in chain:
                strike_oi[r["strike"]] = strike_oi.get(r["strike"], 0) + r["open_interest"]
            max_pain = min(strike_oi, key=strike_oi.get) if strike_oi else None
            sym_data.append({
                "expiry": expiry,
                "pcr": pcr,
                "pe_oi": pe_oi,
                "ce_oi": ce_oi,
                "max_pain": max_pain,
                "total_oi": pe_oi + ce_oi,
                "strikes": len(strike_oi),
            })
        out[sym] = sym_data
    return out


def prune_expired(conn: sqlite3.Connection, today: date) -> int:
    """Remove rows whose expiry has already passed (settled contracts)."""
    n = conn.execute(
        "DELETE FROM option_chain WHERE expiry < ?", (today.isoformat(),)
    ).rowcount
    if n:
        conn.commit()
        log.info("pruned %d expired option rows", n)
    return n


def daily() -> None:
    conn = _conn()
    today = datetime.now(timezone.utc).date()
    prune_expired(conn, today)
    for back in range(5):
        day = today - timedelta(days=back)
        if day.weekday() >= 5:
            continue
        rows = fetch_fo_day(day)
        if rows:
            n = store_option_chain(conn, day, rows)
            oi_n = compute_oi_top_strikes(conn)
            pcr = compute_pcr_maxpain(conn)
            log.info("daily fo %s: %d chain rows, %d top-strikes", day, n, oi_n)
            for sym, exps in pcr.items():
                for e in exps[:2]:
                    log.info("  %s %s: PCR=%.3f maxpain=%s", sym, e["expiry"], e["pcr"] or 0, e["max_pain"])
            conn.close()
            return
        log.info("fo %s: not published yet", day)
    conn.close()


def backfill(days: int = 5) -> None:
    conn = _conn()
    today = datetime.now(timezone.utc).date()
    prune_expired(conn, today)
    done = 0
    for i in range(days):
        day = today - timedelta(days=i)
        if day.weekday() >= 5:
            continue
        have = conn.execute(
            "SELECT COUNT(*) FROM option_chain WHERE symbol='NIFTY' AND expiry LIKE ?",
            (day.isoformat() + "%",)
        ).fetchone()[0]
        if have > 10:
            continue
        rows = fetch_fo_day(day)
        if not rows:
            continue
        n = store_option_chain(conn, day, rows)
        done += n
        log.info("backfill %s: %d rows", day, n)
    compute_oi_top_strikes(conn)
    pcr = compute_pcr_maxpain(conn)
    for sym, exps in pcr.items():
        for e in exps[:2]:
            log.info("  %s %s: PCR=%.3f maxpain=%s", sym, e["expiry"], e["pcr"] or 0, e["max_pain"])
    conn.close()
    log.info("backfill done: %d rows", done)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "daily"
    if cmd == "backfill":
        backfill(int(sys.argv[2]) if len(sys.argv) > 2 else 5)
    else:
        daily()
