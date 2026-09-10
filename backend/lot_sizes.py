from __future__ import annotations

"""Real lot sizes for index (and stock) derivatives.

Primary source: NSE's official market-lot file
    https://nsearchives.nseindia.com/content/fo/fo_mktlots.csv
fetched with a browser User-Agent (NSE blocks bare clients).
SENSEX is a BSE contract and is NOT in the NSE file — it keeps the
configured default, flagged source='config' so the UI can say
"verify with broker" instead of presenting it as exchange-confirmed.
"""

import csv
import io
import logging
import os
import sqlite3
import tempfile
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("tradingai.lots")

NSE_LOTS_URL = "https://nsearchives.nseindia.com/content/fo/fo_mktlots.csv"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"

# Fallbacks when the exchange file is unreachable. SENSEX has no stable
# machine-readable BSE source, so it always stays 'config' until one is found.
FALLBACK_LOTS: dict[str, int] = {
    "NIFTY": 65,
    "BANKNIFTY": 30,
    "FINNIFTY": 60,
    "SENSEX": 20,
}


def _http_get(url: str, timeout: int = 25) -> Optional[bytes]:
    try:
        import urllib.request
        jar = os.path.join(tempfile.gettempdir(), "tradingai_nse_cookies.txt")
        # Warm cookies first; NSE rejects cookie-less clients.
        try:
            req0 = urllib.request.Request("https://www.nseindia.com", headers={"User-Agent": UA})
            opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor())
            opener.open(req0, timeout=timeout).read(1024)
        except Exception:
            opener = urllib.request.build_opener()
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/csv,*/*", "Referer": "https://www.nseindia.com/"})
        with opener.open(req, timeout=timeout) as resp:
            return resp.read()
    except Exception as e:
        logger.warning(f"NSE lots download failed: {e}")
        return None


def fetch_nse_lots() -> dict[str, dict]:
    """{SYMBOL: {'lot': int, 'source': 'NSE'}} from the official file."""
    raw = _http_get(NSE_LOTS_URL)
    if not raw:
        return {}
    try:
        text = raw.decode("utf-8", errors="ignore")
    except Exception:
        return {}
    out: dict[str, dict] = {}
    try:
        reader = csv.reader(io.StringIO(text))
        header = next(reader, None)
        if not header:
            return {}
        # Columns after SYMBOL are per-expiry lots; use the nearest (first) expiry column.
        for row in reader:
            if len(row) < 3:
                continue
            symbol = (row[1] or "").strip().upper()
            if not symbol:
                continue
            for cell in row[2:]:
                cell = (cell or "").strip()
                if cell.isdigit() and int(cell) > 0:
                    out[symbol] = {"lot": int(cell), "source": "NSE"}
                    break
    except Exception as e:
        logger.warning(f"NSE lots parse failed: {e}")
        return {}
    logger.info(f"NSE lots file: {len(out)} symbols")
    return out


def refresh_lot_sizes(conn: sqlite3.Connection, symbols: list[dict] | None = None) -> dict:
    """Write live lots into symbols(lot_size, lot_source, lot_as_of). Returns summary."""
    nse = fetch_nse_lots()
    now = datetime.now(timezone.utc).isoformat()
    updated, fallback = 0, 0
    targets = symbols or []
    if not targets:
        try:
            rows = conn.execute("SELECT symbol, yfinance_symbol FROM symbols WHERE active=1").fetchall()
            targets = [{"symbol": r["symbol"], "yfinance_symbol": r["yfinance_symbol"]} for r in rows]
        except Exception:
            targets = []
    for inst in targets:
        sym = (inst.get("symbol") or "").upper()
        if not sym:
            continue
        # Map yfinance/stock names to NSE F&O symbols (NSE file uses bare names).
        nse_key = sym
        if sym in nse:
            lot, source = nse[sym]["lot"], "NSE"
        elif FALLBACK_LOTS.get(sym):
            lot, source = FALLBACK_LOTS[sym], ("NSE" if sym in ("NIFTY", "BANKNIFTY", "FINNIFTY") and sym in nse else "config")
            if sym in nse:
                lot, source = nse[sym]["lot"], "NSE"
            fallback += 1
        else:
            continue
        try:
            conn.execute("UPDATE symbols SET lot_size=?, lot_source=?, lot_as_of=? WHERE symbol=?", (lot, source, now, sym))
            updated += 1
        except Exception as e:
            logger.warning(f"lot update skip {sym}: {e}")
    try:
        conn.commit()
    except Exception:
        pass
    logger.info(f"lots refreshed: {updated} updated ({fallback} fallback), {len(nse)} in NSE file")
    return {"updated": updated, "fallback": fallback, "nse_count": len(nse)}


if __name__ == "__main__":
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from db_schema import DB_PATH
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    print(refresh_lot_sizes(conn))
    conn.close()
