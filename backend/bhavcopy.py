from __future__ import annotations

"""NSE official EOD data: index bhavcopy + trading holidays.

- Index close file (verified working):
    https://nsearchives.nseindia.com/content/indices/ind_close_all_DDMMYYYY.csv
  gives official O/H/L/C, volume, turnover, P/E, P/B, Div Yield for
  NIFTY 50, Nifty Bank, Nifty Fin Service 25/50 (= our FINNIFTY ^CNXFIN),
  India VIX, Midcap 50. SENSEX is BSE — not covered.
- Holidays: https://www.nseindia.com/api/holiday-master?type=trading
  feeds the expiry engine (replaces the hardcoded list over time).

Usage:
    python3 bhavcopy.py backfill [days]   # index EOD into price_1d (default 30)
    python3 bhavcopy.py daily             # latest session only (cron 18:35 IST)
    python3 bhavcopy.py holidays          # refresh nse_holidays table (cron weekly)
"""

import csv
import io
import json
import logging
import os
import sqlite3
import sys
import urllib.request
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("tradingai.bhav")

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "database", "tradingai.db")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0"}

INDEX_MAP = {
    "NIFTY": "Nifty 50",
    "BANKNIFTY": "Nifty Bank",
    "FINNIFTY": "Nifty Financial Services 25/50",
    "VIX": "India VIX",
}


def _get(url: str, timeout: int = 25) -> bytes | None:
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except Exception as e:
        logger.warning(f"download skip {url}: {e}")
        return None


def _conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _num(v) -> float | None:
    try:
        s = str(v).strip().replace(",", "")
        if s in ("", "-", "--"):
            return None
        return float(s)
    except Exception:
        return None


def fetch_ind_day(day: date) -> list[dict]:
    raw = _get(f"https://nsearchives.nseindia.com/content/indices/ind_close_all_{day.strftime('%d%m%Y')}.csv")
    if not raw:
        return []
    try:
        text = raw.decode("utf-8", errors="ignore")
    except Exception:
        return []
    rows = []
    try:
        for row in csv.DictReader(io.StringIO(text)):
            rows.append({k.strip(): (v or "").strip() for k, v in row.items()})
    except Exception as e:
        logger.warning(f"ind_close parse skip {day}: {e}")
    return rows


def store_ind_day(conn: sqlite3.Connection, day: date, rows: list[dict]) -> int:
    by_name = {r.get("Index Name", ""): r for r in rows}
    n = 0
    for symbol, nse_name in INDEX_MAP.items():
        r = by_name.get(nse_name)
        if not r:
            continue
        o, h, l, c = _num(r.get("Open Index Value")), _num(r.get("High Index Value")), _num(r.get("Low Index Value")), _num(r.get("Closing Index Value"))
        if c is None:
            continue
        vol = _num(r.get("Volume"))
        conn.execute(
            "INSERT OR IGNORE INTO price_1d (symbol, timestamp, open, high, low, close, volume) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (symbol, day.isoformat(), o or c, h or c, l or c, c, int(vol) if vol else 0))
        fund = {k: _num(r.get(col)) for k, col in
                (("index_pe", "P/E"), ("index_pb", "P/B"), ("index_div_yield", "Div Yield"), ("turnover_cr", "Turnover (Rs. Cr.)"))}
        fund = {k: v for k, v in fund.items() if v is not None}
        if fund:
            conn.execute("INSERT OR REPLACE INTO fundamentals (symbol, timestamp, data) VALUES (?, ?, ?)",
                         (symbol, datetime.now(timezone.utc).isoformat(), json.dumps({"nse_index_facts": fund, "as_of": day.isoformat()})))
        n += 1
    conn.commit()
    return n


def backfill(days: int = 30) -> None:
    conn = _conn()
    today = datetime.now(timezone.utc).date()
    done = skipped = 0
    for i in range(days):
        day = today - timedelta(days=i)
        if day.weekday() >= 5:
            continue
        have = conn.execute("SELECT COUNT(*) FROM price_1d WHERE symbol='NIFTY' AND timestamp=?", (day.isoformat(),)).fetchone()[0]
        if have:
            continue
        rows = fetch_ind_day(day)
        if not rows:
            skipped += 1
            continue
        done += store_ind_day(conn, day, rows)
        logger.info(f"bhav {day}: stored")
    conn.close()
    logger.info(f"backfill complete: {done} index-days stored, {skipped} days unavailable")


def daily() -> None:
    conn = _conn()
    today = datetime.now(timezone.utc).date()
    for back in range(5):
        day = today - timedelta(days=back)
        if day.weekday() >= 5:
            continue
        rows = fetch_ind_day(day)
        if rows and any(r.get("Index Name") == "Nifty 50" for r in rows):
            n = store_ind_day(conn, day, rows)
            logger.info(f"daily bhav {day}: {n} indices")
            break
        logger.info(f"daily bhav {day}: not published yet")
    conn.close()


def holidays() -> None:
    """Refresh nse_holidays table from NSE holiday-master (curl_cffi, Chrome impersonation)."""
    try:
        from curl_cffi import requests as cr
    except Exception:
        logger.warning("curl_cffi missing, holidays skipped")
        return
    try:
        s = cr.Session(impersonate="chrome124")
        s.get("https://www.nseindia.com", timeout=20)
        r = s.get("https://www.nseindia.com/api/holiday-master?type=trading", timeout=20,
                  headers={"Accept": "*/*", "Referer": "https://www.nseindia.com/"})
        data = r.json()
    except Exception as e:
        logger.warning(f"holiday-master skip: {e}")
        return
    conn = _conn()
    conn.execute("""CREATE TABLE IF NOT EXISTS nse_holidays (
        date TEXT PRIMARY KEY, description TEXT, segment TEXT, fetched_at TEXT)""")
    n = 0
    for seg, lst in (data or {}).items():
        if not isinstance(lst, list):
            continue
        for h in lst:
            try:
                d = datetime.strptime(h.get("tradingDate", ""), "%d-%b-%Y").strftime("%Y-%m-%d")
            except Exception:
                continue
            conn.execute("INSERT OR REPLACE INTO nse_holidays (date, description, segment, fetched_at) VALUES (?, ?, ?, ?)",
                         (d, h.get("description", ""), seg, datetime.now(timezone.utc).isoformat()))
            n += 1
    conn.commit()
    conn.close()
    logger.info(f"holidays refreshed: {n} rows")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "daily"
    if cmd == "backfill":
        backfill(int(sys.argv[2]) if len(sys.argv) > 2 else 30)
    elif cmd == "holidays":
        holidays()
    else:
        daily()
