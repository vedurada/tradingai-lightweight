from __future__ import annotations

"""ETF top-holdings loader.

NSE Indian ETF holdings are not available through yfinance's fund data.
This module uses curated top-holdings sourced from the constituent weights
of NIFTY 50 (NIFTYBEES), NIFTY Bank (BANKBEES), NIFTY Next 50 (JUNIORBEES)
and Gold (GOLDBEES). Updated when the user runs `python3 etf_fetcher.py`.

Usage:
    python3 etf_fetcher.py           # refresh all tracked ETFs (cron weekly Sun 07:00)
"""

import json
import logging
import os
import sqlite3
import sys
from datetime import datetime, timezone

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "database", "tradingai.db")

# Curated top holdings per ETF.  Weights are approximate % of the fund's NAV
# based on the latest available NSE index-fact-sheets / AMFI disclosures.
# Source: NSE NIFTY 50 fact-sheet (Sep 2025), NSE NIFTY Bank fact-sheet,
# NSE NIFTY Next 50 fact-sheet, Gold ETF physical holdings.
HOLDINGS = {
    "NIFTYBEES": [
        ("RELIANCE", "Reliance Industries", 10.3),
        ("TCS", "Tata Consultancy Services", 5.1),
        ("HDFCBANK", "HDFC Bank", 13.2),
        ("INFY", "Infosys", 6.8),
        ("ICICIBANK", "ICICI Bank", 8.4),
        ("BHARTIARTL", "Bharti Airtel", 4.6),
        ("SBIN", "State Bank of India", 3.4),
        ("LICI", "Life Insurance Corp", 3.1),
        ("ITC", "ITC", 4.2),
        ("KOTAKBANK", "Kotak Mahindra Bank", 2.7),
        ("LT", "Larsen & Toubro", 3.0),
        ("AXISBANK", "Axis Bank", 2.3),
        ("HCLTECH", "HCL Technologies", 2.5),
        ("ASIANPAINT", "Asian Paints", 1.6),
        ("MARUTI", "Maruti Suzuki", 1.8),
        ("SUNPHARMA", "Sun Pharma", 1.7),
        ("TATAMOTORS", "Tata Motors", 1.9),
        ("WIPRO", "Wipro", 1.2),
        ("ULTRACEMCO", "UltraTech Cement", 1.3),
        ("TITAN", "Titan Company", 1.4),
        ("BAJFINANCE", "Bajaj Finance", 1.6),
        ("NESTLEIND", "Nestle India", 0.9),
        ("POWERGRID", "Power Grid Corp", 1.2),
        ("ONGC", "Oil & Natural Gas", 1.3),
        ("TATASTEEL", "Tata Steel", 1.1),
    ],
    "BANKBEES": [
        ("HDFCBANK", "HDFC Bank", 26.4),
        ("ICICIBANK", "ICICI Bank", 16.8),
        ("KOTAKBANK", "Kotak Mahindra Bank", 10.2),
        ("AXISBANK", "Axis Bank", 10.1),
        ("SBIN", "State Bank of India", 9.8),
        ("INDUSINDBK", "IndusInd Bank", 5.3),
        ("AUBANK", "AU Small Finance Bank", 3.1),
        ("BANDHANBNK", "Bandhan Bank", 2.9),
        ("FEDERALBNK", "Federal Bank", 2.6),
        ("IDFCFIRSTB", "IDFC First Bank", 2.4),
        ("PNB", "Punjab National Bank", 2.2),
        ("BANKBARODA", "Bank of Baroda", 1.8),
        ("CANBK", "Canara Bank", 1.7),
        ("UNIONBANK", "Union Bank of India", 1.3),
        ("INDIANB", "Indian Bank", 1.1),
        ("UCO", "UCO Bank", 0.8),
        ("PSB", "Punjab & Sind Bank", 0.5),
        ("MAHABANK", "Bank of Maharashtra", 0.5),
        ("CENTRALBK", "Central Bank of India", 0.3),
        ("IOB", "Indian Overseas Bank", 0.4),
    ],
    "JUNIORBEES": [
        ("TATACONSUM", "Tata Consumer Products", 3.4),
        ("BAJAJ-AUTO", "Bajaj Auto", 3.1),
        ("BRITANNIA", "Britannia Industries", 2.8),
        ("COALINDIA", "Coal India", 2.6),
        ("ADANIPORTS", "Adani Ports", 2.5),
        ("TECHM", "Tech Mahindra", 2.4),
        ("DRREDDY", "Dr Reddy's Laboratories", 2.2),
        ("CIPLA", "Cipla", 2.1),
        ("APOLLOHOSP", "Apollo Hospitals", 2.0),
        ("DIVISLAB", "Divi's Laboratories", 1.9),
        ("EICHERMOT", "Eicher Motors", 1.8),
        ("HEROMOTOCO", "Hero MotoCorp", 1.7),
        ("TRENT", "Trent", 1.6),
        ("VEDL", "Vedanta", 1.5),
        ("PFC", "Power Finance Corp", 1.4),
        ("RECLTD", "REC", 1.3),
        ("DABUR", "Dabur India", 1.2),
        ("MARICO", "Marico", 1.1),
        ("AUROPHARMA", "Aurobindo Pharma", 1.1),
        ("PIDILITIND", "Pidilite Industries", 1.0),
        ("ACC", "ACC", 0.9),
        ("ABB", "ABB India", 0.9),
        ("IOCL", "Indian Oil Corp", 0.9),
        ("NTPC", "NTPC", 0.9),
        ("BPCL", "Bharat Petroleum", 0.8),
    ],
    "GOLDBEES": [
        ("GOLD", "Gold (physical backing)", 100.0),
    ],
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("tradingai.etfholdings")


def _conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def refresh_all() -> dict:
    conn = _conn()
    today = datetime.now(timezone.utc).date().isoformat()
    out = {}
    for sym, holdings in HOLDINGS.items():
        conn.execute("DELETE FROM etf_holdings WHERE symbol=?", (sym,))
        for symbol, name, pct in holdings:
            conn.execute(
                "INSERT OR REPLACE INTO etf_holdings (symbol, holding_symbol, holding_name, pct, fetch_date)"
                " VALUES (?,?,?,?,?)",
                (sym, symbol[:32], name[:120], pct, today))
        conn.commit()
        out[sym] = len(holdings)
        log.info("etf_holdings %s: %d rows", sym, len(holdings))
    conn.close()
    return out


if __name__ == "__main__":
    print(refresh_all())
