from __future__ import annotations

"""Free NSE FO data for higher-OI strikes (exhaustive free-source attempts).

Yahoo has no NSE OI; NSE's live chain endpoint is currently dead (404).
The only remaining free source is the daily FO bhavcopy. Its URL has shifted
recently — this module tries every historically-valid pattern with proper
cookies/headers (curl_cffi) and parses whatever it gets, so any future
restoration is picked up automatically with zero code change.

Today, market-hours OI stays unavailable honestly; after-close, the FO bhav
fills OI for the strategy engine's next-day outlook.
"""

import io
import csv
import zipfile
import logging
from datetime import date, timedelta
from typing import Optional

logger = logging.getLogger("tradingai.nse_fo")

ARCHIVE_TEMPLATES = [
    "https://nsearchives.nseindia.com/content/historical/DERIVATIVES/{YYYY}/{MMM}/fo{DD}{MMM}{YYYY}bhav.csv.zip",
    "https://archives.nseindia.com/content/historical/DERIVATIVES/{YYYY}/{MMM}/fo{DD}{MMM}{YYYY}bhav.csv.zip",
    "https://www.nseindia.com/content/historical/DERIVATIVES/{YYYY}/{MMM}/fo{DD}{MMM}{YYYY}bhav.csv.zip",
    "https://nsearchives.nseindia.com/content/historical/DERIVATIVES/{YYYY}/{MMM}/fo{DD}{MMM}{YYYY}bhav.csv",
    "https://nsearchives.nseindia.com/content/derivatives/fo{DD}{MMM}{YYYY}bhav.csv.zip",
    "https://nsearchives.nseindia.com/archives/nse_historical/fo/{YYYY}/{MM}/fo{DD}{MMM}{YYYY}bhav.csv.zip",
]

VARIANTS = [
    ("NIFTY", "OPTIDX"),
    ("BANKNIFTY", "OPTIDX"),
    ("FINNIFTY", "OPTIDX"),
]


def _session():
    try:
        from curl_cffi import requests as cr
        s = cr.Session(impersonate="chrome124")
        s.get("https://www.nseindia.com", timeout=20)
        return s
    except Exception as e:
        logger.warning(f"nse_fo session skip: {e}")
        return None


def fetch_fo_day(day: date) -> list[dict]:
    """Try every free archive pattern for one day; return CSV rows or []."""
    s = _session()
    if not s:
        return []
    y, m, d = str(day.year), f"{day.month:02d}", f"{day.day:02d}"
    MMM = day.strftime("%b").upper()
    yyyy = str(day.year)
    for tmpl in ARCHIVE_TEMPLATES:
        url = tmpl.format(YYYY=yyyy, MMM=MMM, DD=d, MM=m)
        try:
            r = s.get(url, timeout=25, headers={"Referer": "https://www.nseindia.com/"})
            if r.status_code != 200 or len(r.content) < 200:
                continue
            body = r.content
            # Zip or plain CSV; try both
            try:
                z = zipfile.ZipFile(io.BytesIO(body))
                name = z.namelist()[0]
                body = z.read(name)
            except Exception:
                pass
            text = body.decode("utf-8", errors="ignore")
            if "SYMBOL" not in text[:200]:
                continue
            rows = list(csv.DictReader(io.StringIO(text)))
            if rows:
                logger.info(f"FO bhav {day}: {len(rows)} rows from {url.split('/')[-1]}")
                return rows
        except Exception as e:
            logger.debug(f"FO bhav skip {url}: {e}")
            continue
    logger.info(f"FO bhav {day}: no free source produced rows (market holiday or URL rotated)")
    return []


def top_oi_strikes(rows: list[dict], symbol: str, expiry: str | None = None, top: int = 3) -> dict:
    """{expiry, calls: [{strike, oi}], puts: [...] } for the nearest expiry if not specified."""
    filt = [r for r in rows if r.get("SYMBOL") == symbol and r.get("INSTRUMENT") == "OPTIDX"]
    if not filt:
        return {}
    exps = sorted(set(r.get("EXPIRY_DT", "") for r in filt if r.get("EXPIRY_DT")))
    if not exps:
        return {}
    target = expiry or exps[0]
    filt = [r for r in filt if r.get("EXPIRY_DT") == target]
    calls = sorted([r for r in filt if r.get("OPTION_TYP") == "CE"], key=lambda x: float(x.get("OPEN_INT") or 0), reverse=True)[:top]
    puts = sorted([r for r in filt if r.get("OPTION_TYP") == "PE"], key=lambda x: float(x.get("OPEN_INT") or 0), reverse=True)[:top]
    return {
        "expiry": target, "expiries": exps,
        "calls": [{"strike": c.get("STRIKE_PR"), "oi": c.get("OPEN_INT"), "close": c.get("CLOSE")} for c in calls],
        "puts": [{"strike": p.get("STRIKE_PR"), "oi": p.get("OPEN_INT"), "close": p.get("CLOSE")} for p in puts],
    }


def yf_fallback_top_oi(yf_symbol: str, top: int = 3) -> dict:
    """Second free source: yfinance option chain (often empty for NSE, but try)."""
    try:
        import yfinance as yf
        t = yf.Ticker(yf_symbol)
        exps = (t.options or [])[:1]
        if not exps:
            return {}
        chain = t.option_chain(exps[0])
        calls = chain.calls.sort_values("openInterest", ascending=False).head(top)
        puts = chain.puts.sort_values("openInterest", ascending=False).head(top)
        return {
            "expiry": exps[0],
            "calls": [{"strike": str(r.strike), "oi": str(r.openInterest)} for _, r in calls.iterrows()],
            "puts": [{"strike": str(r.strike), "oi": str(r.openInterest)} for _, r in puts.iterrows()],
        }
    except Exception as e:
        logger.debug(f"yfinance OI fallback skip {yf_symbol}: {e}")
        return {}
