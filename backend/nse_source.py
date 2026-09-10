from __future__ import annotations

"""NSE as PRIMARY quote source, yfinance as fallback.

NSE's own site endpoints (verified live from our VM via Chrome-impersonated
sessions) give undelayed index quotes + official advances/declines:
- allIndices: every index quote + A/D (+ OHLC, prev close, 52w, P/E)
- marketStatus: open/closed state, Gift Nifty, indicative Nifty
- chart-databyindex: intraday series (in-hours only)

Limits (honest): no SENSEX (BSE product), no stock quotes (403), no
strike-level option chain, no tick feed. Stocks/ETFs stay yfinance-first.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("tradingai.nse")

# NSE indexSymbol -> our symbol
INDEX_MAP = {
    "NIFTY 50": "NIFTY",
    "NIFTY BANK": "BANKNIFTY",
    "NIFTY FIN SERVICE": "FINNIFTY",
    "NIFTY FINANCIAL SERVICES": "FINNIFTY",
    "INDIA VIX": "VIX",
}


def _session():
    from curl_cffi import requests as cr
    s = cr.Session(impersonate="chrome124")
    s.get("https://www.nseindia.com", timeout=20)
    return s


def _num(v, default: float = 0.0) -> float:
    try:
        f = float(str(v).replace(",", ""))
        return f if f == f else default
    except Exception:
        return default


def fetch_index_quotes() -> dict[str, dict]:
    """{SYMBOL: {price, open, high, low, prev_close, change, change_pct, advances, declines, unchanged}}"""
    out: dict[str, dict] = {}
    try:
        s = _session()
        r = s.get("https://www.nseindia.com/api/allIndices", timeout=25,
                  headers={"Accept": "*/*", "Referer": "https://www.nseindia.com/"})
        rows = r.json().get("data", [])
    except Exception as e:
        logger.warning(f"NSE allIndices skip: {e}")
        return {}
    for x in rows:
        name = str(x.get("indexSymbol") or x.get("index") or "").strip().upper()
        sym = INDEX_MAP.get(name)
        if not sym:
            continue
        price = _num(x.get("last"))
        prev = _num(x.get("previousClose"))
        change = _num(x.get("variation"), price - prev if prev else 0)
        out[sym] = {
            "price": price, "open": _num(x.get("open")), "high": _num(x.get("high")),
            "low": _num(x.get("low")), "previous_close": prev, "change": round(change, 2),
            "change_pct": round(_num(x.get("percentChange")), 2),
            "volume": 0,
            "advances": int(x.get("advances") or 0), "declines": int(x.get("declines") or 0),
            "unchanged": int(x.get("unchanged") or 0),
            "timestamp": datetime.now(timezone.utc).isoformat(), "stale": price == 0,
            "source": "NSE",
        }
    if out:
        logger.info(f"NSE quotes: {', '.join(f'{k}={v['price']}' for k, v in out.items())}")
    return out


def fetch_market_state() -> dict:
    """Open/closed state + Gift Nifty. Best-effort, never raises."""
    try:
        s = _session()
        r = s.get("https://www.nseindia.com/api/marketStatus", timeout=20,
                  headers={"Accept": "*/*", "Referer": "https://www.nseindia.com/"})
        d = r.json()
        states = {}
        if isinstance(d, dict):
            for m in d.get("marketState", []) or []:
                if m.get("market"):
                    states[m["market"]] = m.get("marketStatus", "")
        return {"states": states, "raw": d if isinstance(d, dict) else {}}
    except Exception as e:
        logger.warning(f"NSE marketStatus skip: {e}")
        return {}
