from __future__ import annotations

"""Fetch ETF top-holdings via yfinance and store into etf_holdings.

Usage:
    python3 etf_fetcher.py           # refresh all tracked ETFs (cron weekly Sun 07:00)

Symbols mirrored: NIFTYBEES, BANKBEES, JUNIORBEES (same set as price tracking).
"""

import logging
import os
import sqlite3
import sys
import warnings
from datetime import datetime, timezone

warnings.filterwarnings("ignore")

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "database", "tradingai.db")
YF_ETFS = {
    "NIFTYBEES": "NIFTYBEES.NS",
    "BANKBEES": "BANKBEES.NS",
    "JUNIORBEES": "JUNIORBEES.NS",
    "GOLDBEES": "GOLDBEES.NS",
}
TOP_N = 25

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("tradingai.etfholdings")


def _fetch_holdings(yf_sym: str) -> list[dict]:
    import yfinance as yf
    t = yf.Ticker(yf_sym)
    holdings: list[dict] = []
    try:
        df = t.top_holdings
        if df is not None and not df.empty:
            for _, row in df.iterrows():
                if row.get("Symbol") is None and len(row) < 2:
                    continue
                symbol = row.get("Symbol")
                name = row.get("Name")
                pct = row.get("% of Total Shares")
                if pct is None:
                    pct = row.get("% Held")
                if symbol is None and name is None:
                    continue
                try:
                    pct = float(pct) if pct is not None else None
                except (TypeError, ValueError):
                    pct = None
                if pct is not None:
                    holdings.append({"symbol": str(symbol), "name": str(name), "pct": pct})
    except Exception as e:
        log.info("top_holdings %s unavailable: %s", yf_sym, e)
    if holdings:
        return holdings[:TOP_N]
    try:
        got = t.get_holdings()
        if got:
            for sym, pct in got.items():
                try:
                    pct = float(pct)
                except (TypeError, ValueError):
                    continue
                holdings.append({"symbol": str(sym), "name": str(sym), "pct": pct})
    except Exception as e:
        log.info("get_holdings %s unavailable: %s", yf_sym, e)
    return holdings[:TOP_N]


def _conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def refresh_all() -> dict:
    conn = _conn()
    today = datetime.now(timezone.utc).date().isoformat()
    out = {}
    for sym, yf_sym in YF_ETFS.items():
        holdings = _fetch_holdings(yf_sym)
        if not holdings:
            out[sym] = 0
            continue
        conn.execute("DELETE FROM etf_holdings WHERE symbol=?", (sym,))
        for h in holdings:
            conn.execute(
                "INSERT OR REPLACE INTO etf_holdings (symbol, holding_symbol, holding_name, pct, fetch_date)"
                " VALUES (?,?,?,?,?)",
                (sym, (h["symbol"] or "?")[:32], (h["name"] or h["symbol"] or "?")[:120], h["pct"], today))
        conn.commit()
        out[sym] = len(holdings)
        log.info("etf_holdings %s: %d rows", sym, len(holdings))
    conn.close()
    return out


if __name__ == "__main__":
    print(refresh_all())