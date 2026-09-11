from __future__ import annotations

"""Live NSE index option-chain poller (best-effort, auto-resuming).

NSE's public `option-chain-indices` endpoint has been unstable/disabled at
times (returns 404). This module polls it during market hours; when the
source is unavailable it logs once per day and silently no-ops, and
automatically resumes storing once NSE brings it back. Live rows land in
`option_chain` with a fresh `fetched_at`, so `/api/pcr`, `/api/maxpain`,
`/api/oi-top` and `/api/options/<symbol>` become intraday updates for free.

Usage:
    python3 nse_live_chain.py poll [symbols]
    python3 nse_live_chain.py status            # last successful fetch age
"""

import json
import logging
import os
import sqlite3
import sys
from datetime import datetime, timezone

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "database", "tradingai.db")
INDEX_SYMBOLS = ["NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX"]
CHAIN_URL = "https://www.nseindia.com/api/option-chain-indices?symbol={symbol}"
STATUS_FILE = os.path.expanduser("~/tradingai_live_chain_status.json")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("tradingai.livechain")

try:
    from curl_cffi import requests as cr
    _SESSION = cr.Session(impersonate="chrome124")
except Exception as e:  # pragma: no cover
    log.warning("curl_cffi unavailable (%s); live chain disabled", e)
    _SESSION = None


def _warned_today() -> bool:
    try:
        with open(STATUS_FILE) as f:
            state = json.load(f)
        return state.get("source_down_logged") == datetime.now(timezone.utc).date().isoformat()
    except Exception:
        return False


def _mark_down() -> None:
    try:
        with open(STATUS_FILE, "w") as f:
            json.dump({"source_down_logged": datetime.now(timezone.utc).date().isoformat()}, f)
    except Exception:
        pass


def fetch_chain(symbol: str) -> list[dict] | None:
    """Return flattened {symbol, expiry, strike, option_type, ..., open_interest}
    rows for one index symbol, or None if source was unavailable."""
    if _SESSION is None:
        return None
    try:
        s = _SESSION
        s.get("https://www.nseindia.com", timeout=15)
        r = s.get(CHAIN_URL.format(symbol=symbol), timeout=25, headers={
            "Accept": "*/*",
            "Referer": "https://www.nseindia.com/option-chain",
        })
        if r.status_code != 200:
            log.info("chain %s status %s", symbol, r.status_code)
            return None
        recs = (r.json() or {}).get("records") or {}
        now = datetime.now(timezone.utc).isoformat()
        rows = []
        for ent in recs.get("data") or []:
            expiry = ent.get("expiryDate") or ""
            strike = ent.get("strikePrice")
            for opt in ("CE", "PE"):
                side = ent.get(opt)
                if not side:
                    continue
                oi = side.get("openInterest")
                if oi is None:
                    continue
                rows.append({
                    "symbol": symbol,
                    "expiry": expiry,
                    "strike": strike,
                    "option_type": opt,
                    "last_price": side.get("lastPrice"),
                    "bid": side.get("bidprice"),
                    "ask": side.get("askprice"),
                    "volume": int(side.get("totalTradedVolume") or 0),
                    "open_interest": int(oi or 0),
                    "change_in_oi": int(side.get("changeinOpenInterest") or 0),
                    "implied_volatility": side.get("IV"),
                    "bid_size": side.get("bidQty"),
                    "ask_size": side.get("askQty"),
                    "fetched_at": now,
                    "underlying": side.get("underlyingValue"),
                })
        return rows
    except Exception as e:
        log.info("chain %s fetch error: %s", symbol, e)
        return None


def _conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def store_rows(conn: sqlite3.Connection, rows: list[dict]) -> int:
    now = datetime.now(timezone.utc).isoformat()
    n = 0
    for r in rows:
        conn.execute(
            "INSERT OR REPLACE INTO option_chain"
            " (symbol, expiry, strike, option_type, last_price, bid, ask, volume, open_interest,"
            "  change_in_oi, implied_volatility, bid_size, ask_size, fetched_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (r["symbol"], r["expiry"], r["strike"], r["option_type"], r["last_price"],
             r["bid"], r["ask"], r["volume"], r["open_interest"], r["change_in_oi"],
             r["implied_volatility"], r["bid_size"], r["ask_size"], r["fetched_at"]))
        n += 1
        if r["expiry"] and r["symbol"] not in ("SENSEX",):
            conn.execute(
                "INSERT OR IGNORE INTO option_expiries (symbol, expiry, fetched_at) VALUES (?,?,?)",
                (r["symbol"], r["expiry"], now))
    conn.commit()
    return n


def prune_expired(conn: sqlite3.Connection) -> int:
    today = datetime.now(timezone.utc).date().isoformat()
    n = conn.execute("DELETE FROM option_chain WHERE expiry < ?", (today,)).rowcount
    if n:
        conn.commit()
    return n


def poll(symbols: list[str] | None = None) -> dict:
    symbols = symbols or INDEX_SYMBOLS
    conn = _conn()
    prune_expired(conn)
    total = 0
    ok_sources = 0
    for sym in symbols:
        rows = fetch_chain(sym)
        if rows is None:
            continue
        ok_sources += 1
        total += store_rows(conn, rows)
        log.info("poll %s: %d chain rows", sym, len(rows))
    conn.close()
    if ok_sources == 0:
        if not _warned_today():
            log.warning("live NSE chain unavailable (all sources failed); EOD OI used")
            _mark_down()
        return {"ok": False, "stored": 0}
    try:
        with open(STATUS_FILE, "w") as f:
            json.dump({"last_ok": datetime.now(timezone.utc).isoformat()}, f)
    except Exception:
        pass
    return {"ok": True, "stored": total}


def status() -> dict:
    try:
        with open(STATUS_FILE) as f:
            return json.load(f)
    except Exception:
        return {"error": "no status file yet"}


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "poll"
    if cmd == "status":
        print(json.dumps(status(), default=str))
    else:
        echo = sys.argv[2:] or None
        print(json.dumps(poll(echo), default=str))