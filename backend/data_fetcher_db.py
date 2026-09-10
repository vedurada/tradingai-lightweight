from __future__ import annotations

import json
import os
import sys
import logging
import sqlite3
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db_schema import init_database, DB_PATH, SCHEMA

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("tradingai.fetcher")

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config", "instruments.json")
SETTINGS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config", "settings.json")

YF_INDICES = {"^NSEI": "NIFTY", "^NSEBANK": "BANKNIFTY", "^BSESN": "SENSEX"}
YF_VIX = "^VIX"
YF_ETFS = {"^NIFTYBEES": "NIFTYBEES", "^BANKBEES": "BANKBEES", "^JUNIORBEES": "JUNIORBEES"}

ALL_SYMBOLS = ["NIFTY", "BANKNIFTY", "SENSEX", "FINNIFTY", "VIX", "NIFTYBEES", "BANKBEES", "JUNIORBEES"]

STOCK_SYMBOLS = [
    ("RELIANCE", "RELIANCE.NS"), ("HDFCBANK", "HDFCBANK.NS"), ("ICICIBANK", "ICICIBANK.NS"),
    ("SBIN", "SBIN.NS"), ("INFY", "INFY.NS"), ("TCS", "TCS.NS"), ("LT", "LT.NS"),
    ("AXISBANK", "AXISBANK.NS"), ("ADANIENT", "ADANIENT.NS"), ("BHARTIARTL", "BHARTIARTL.NS"),
    ("WIPRO", "WIPRO.NS"), ("HCLTECH", "HCLTECH.NS"), ("TECHM", "TECHM.NS"), ("MARUTI", "MARUTI.NS"),
]

SECTORS = ["BANK", "IT", "AUTO", "PHARMA", "ENERGY", "FMCG", "METAL", "REALTY", "FINANCIAL"]


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return json.load(f)


def load_settings() -> dict:
    with open(SETTINGS_PATH) as f:
        return json.load(f)


def get_db() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_symbols(conn: sqlite3.Connection, config: dict) -> None:
    c = conn.execute("SELECT COUNT(*) FROM symbols")
    if c.fetchone()[0] == 0:
        for inst in config["indices"]:
            conn.execute("INSERT OR IGNORE INTO symbols (symbol, name, yfinance_symbol, type, category, active, created_at) VALUES (?, ?, ?, 'index', 'INDEX', 1, datetime('now'))", (inst["symbol"], inst["name"], inst["yfinance_symbol"]))
        for inst in config["stocks"]:
            conn.execute("INSERT OR IGNORE INTO symbols (symbol, name, yfinance_symbol, type, category, active, created_at) VALUES (?, ?, ?, 'stock', ?, 1, datetime('now'))", (inst["symbol"], inst["name"], inst["yfinance_symbol"], inst.get("sector", "FINANCIAL")))
        for sym, yf_sym in YF_ETFS.items():
            conn.execute("INSERT OR IGNORE INTO symbols (symbol, name, yfinance_symbol, type, category, active, created_at) VALUES (?, ?, ?, 'etf', 'ETF', 1, datetime('now'))", (sym, sym, yf_sym))
        conn.execute("INSERT OR IGNORE INTO symbols (symbol, name, yfinance_symbol, type, category, active, created_at) VALUES (?, ?, ?, 'vix', 'VOLATILITY', 1, datetime('now'))", ("VIX", "India VIX", YF_VIX))
        conn.commit()
        logger.info(f"Initialized {config['indices'].__len__() + config['stocks'].__len__() + len(YF_ETFS) + 1} symbols")


def fetch_yf_ohlcv(yf_symbol: str, interval: str = "1m", period: str = "2d") -> list[dict]:
    try:
        import yfinance as yf
        ticker = yf.Ticker(yf_symbol)
        hist = ticker.history(period=period, interval=interval)
        if hist.empty:
            return []
        data = []
        for idx, row in hist.iterrows():
            data.append({
                "timestamp": idx.strftime("%Y-%m-%d %H:%M:%S"),
                "open": float(row["Open"]),
                "high": float(row["High"]),
                "low": float(row["Low"]),
                "close": float(row["Close"]),
                "volume": int(row["Volume"]),
            })
        return data
    except Exception as e:
        logger.error(f"OHLCV error for {yf_symbol}: {e}")
        return []


def fetch_yf_info(yf_symbol: str) -> dict:
    try:
        import yfinance as yf
        ticker = yf.Ticker(yf_symbol)
        info = ticker.info or {}
        numeric = {k: v for k, v in info.items() if isinstance(v, (int, float)) and v is not None}
        return numeric
    except Exception as e:
        logger.error(f"Info error for {yf_symbol}: {e}")
        return {}


def fetch_yf_options(yf_symbol: str) -> dict:
    try:
        import yfinance as yf
        ticker = yf.Ticker(yf_symbol)
        expirations = ticker.options
        if not expirations:
            return {}
        result = {"expirations": [], "chains": []}
        for exp in expirations[:3]:
            try:
                opt = ticker.option_chain(exp)
                expiry_data = {"expiry": exp, "calls": [], "puts": []}
                for _, row in opt.calls.iterrows():
                    expiry_data["calls"].append({
                        "strike": float(row["strike"]), "last_price": float(row["lastPrice"]) if not row["lastPrice"] is None else 0,
                        "bid": float(row["bid"]) if not row["bid"] is None else 0,
                        "ask": float(row["ask"]) if not row["ask"] is None else 0,
                        "volume": int(row["volume"]) if not row["volume"] is None else 0,
                        "open_interest": int(row["openInterest"]) if not row["openInterest"] is None else 0,
                        "implied_volatility": float(row["impliedVolatility"]) if not row["impliedVolatility"] is None else 0,
                    })
                for _, row in opt.puts.iterrows():
                    expiry_data["puts"].append({
                        "strike": float(row["strike"]), "last_price": float(row["lastPrice"]) if not row["lastPrice"] is None else 0,
                        "bid": float(row["bid"]) if not row["bid"] is None else 0,
                        "ask": float(row["ask"]) if not row["ask"] is None else 0,
                        "volume": int(row["volume"]) if not row["volume"] is None else 0,
                        "open_interest": int(row["openInterest"]) if not row["openInterest"] is None else 0,
                        "implied_volatility": float(row["impliedVolatility"]) if not row["impliedVolatility"] is None else 0,
                    })
                result["expirations"].append(exp)
                result["chains"].append(expiry_data)
            except Exception as e:
                logger.error(f"Option chain error for {yf_symbol} exp={exp}: {e}")
        return result
    except Exception as e:
        logger.error(f"Options error for {yf_symbol}: {e}")
        return {}


def fetch_yf_financials(yf_symbol: str) -> dict:
    try:
        import yfinance as yf
        ticker = yf.Ticker(yf_symbol)
        financials = ticker.financials
        if financials is not None and not financials.empty:
            data = {}
            for col in financials.columns[:4]:
                for idx in financials.index:
                    val = financials.loc[idx, col]
                    if isinstance(val, (int, float)) and not __import__("math").isnan(val):
                        key = f"{idx}_{col.strftime('%Y-%m-%d') if hasattr(col, 'strftime') else str(col)}"
                        data[key] = float(val)
            return data
        return {}
    except Exception as e:
        logger.error(f"Financials error for {yf_symbol}: {e}")
        return {}


def store_price_data(conn: sqlite3.Connection, symbol: str, data: list[dict], interval_table: str) -> None:
    if not data:
        return
    for d in data:
        try:
            conn.execute(
                f"INSERT OR IGNORE INTO {interval_table} (symbol, timestamp, open, high, low, close, volume) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (symbol, d["timestamp"], d["open"], d["high"], d["low"], d["close"], d["volume"])
            )
        except Exception as e:
            logger.error(f"Store {interval_table} error for {symbol}: {e}")
    conn.commit()


def store_vix_data(conn: sqlite3.Connection, timestamp: str, data: dict) -> None:
    conn.execute("INSERT OR REPLACE INTO vix_data (timestamp, open, high, low, close, change, change_pct) VALUES (?, ?, ?, ?, ?, ?, ?)",
                 (timestamp, data.get("open", 0), data.get("high", 0), data.get("low", 0), data.get("close", 0), data.get("change", 0), data.get("change_pct", 0)))
    conn.commit()


def store_option_chains(conn: sqlite3.Connection, symbol: str, options_data: dict) -> None:
    if not options_data or "chains" not in options_data:
        return
    for chain in options_data["chains"]:
        expiry = chain["expiry"]
        conn.execute("INSERT OR REPLACE INTO option_expiries (symbol, expiry, fetched_at) VALUES (?, ?, ?)", (symbol, expiry, datetime.now(timezone.utc).isoformat()))
        for call in chain["calls"]:
            conn.execute("INSERT OR REPLACE INTO option_chain (symbol, expiry, strike, option_type, last_price, bid, ask, volume, open_interest, change_in_oi, implied_volatility, bid_size, ask_size, fetched_at) VALUES (?, ?, ?, 'CE', ?, ?, ?, ?, ?, 0, ?, 0, 0, ?)",
                         (symbol, expiry, call["strike"], call["last_price"], call["bid"], call["ask"], call["volume"], call["open_interest"], call["implied_volatility"], datetime.now(timezone.utc).isoformat()))
        for put in chain["puts"]:
            conn.execute("INSERT OR REPLACE INTO option_chain (symbol, expiry, strike, option_type, last_price, bid, ask, volume, open_interest, change_in_oi, implied_volatility, bid_size, ask_size, fetched_at) VALUES (?, ?, ?, 'PE', ?, ?, ?, ?, ?, 0, ?, 0, 0, ?)",
                         (symbol, expiry, put["strike"], put["last_price"], put["bid"], put["ask"], put["volume"], put["open_interest"], put["implied_volatility"], datetime.now(timezone.utc).isoformat()))
    conn.commit()


def store_fundamentals(conn: sqlite3.Connection, symbol: str, data: dict) -> None:
    if not data:
        return
    conn.execute("INSERT OR REPLACE INTO fundamentals (symbol, timestamp, data) VALUES (?, ?, ?)",
                 (symbol, datetime.now(timezone.utc).isoformat(), json.dumps(data)))
    conn.commit()


def update_data_status(conn: sqlite3.Connection, symbol: str, interval_type: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn.execute("INSERT OR REPLACE INTO data_status (symbol, last_fetch, last_1m_fetch, last_5m_fetch, last_15m_fetch, last_options_fetch, last_vix_fetch, status, error_count) VALUES (?, ?, ?, ?, ?, ?, ?, 'OK', 0)",
                 (symbol, now, now if interval_type == "1m" else "", now if interval_type == "5m" else "", now if interval_type == "15m" else "", now if interval_type == "options" else "", now if interval_type == "vix" else ""))
    conn.commit()


def fetch_market_snapshot(conn: sqlite3.Connection) -> dict:
    snapshot = {"timestamp": datetime.now(timezone.utc).isoformat()}
    for sym in ["NIFTY", "BANKNIFTY", "SENSEX", "VIX"]:
        c = conn.execute(f"SELECT close FROM price_1m WHERE symbol=? ORDER BY timestamp DESC LIMIT 1", (sym,))
        row = c.fetchone()
        if row:
            snapshot[sym.lower()] = row["close"]
    c = conn.execute("SELECT change_pct FROM vix_data ORDER BY timestamp DESC LIMIT 1")
    row = c.fetchone()
    if row:
        snapshot["vix_change_pct"] = row["change_pct"]
    conn.execute("INSERT OR REPLACE INTO market_snapshots (timestamp, nifty, banknifty, finnifty, sensex, vix, vix_change_pct) VALUES (?, ?, ?, ?, ?, ?, ?)",
                 (snapshot["timestamp"], snapshot.get("nifty", 0), snapshot.get("banknifty", 0), snapshot.get("finnifty", 0), snapshot.get("sensex", 0), snapshot.get("vix", 0), snapshot.get("vix_change_pct", 0)))
    conn.commit()
    return snapshot


def fetch_all() -> None:
    config = load_config()
    settings = load_settings()
    init_database()
    conn = get_db()
    init_symbols(conn, config)

    now = datetime.now(timezone.utc)
    is_market_hours = now.weekday() < 5 and 9 <= now.hour <= 15

    logger.info(f"Fetching data... market_hours={is_market_hours}")

    all_symbols = list(YF_INDICES.keys()) + list(YF_ETFS.keys()) + [YF_VIX]

    for yf_sym in all_symbols:
        symbol = YF_INDICES.get(yf_sym, YF_ETFS.get(yf_sym, "VIX"))
        logger.info(f"Fetching {symbol} ({yf_sym})")
        data = fetch_yf_ohlcv(yf_sym, interval="1m", period="1d")
        if data:
            store_price_data(conn, symbol, data, "price_1m")
            update_data_status(conn, symbol, "1m")
        info = fetch_yf_info(yf_sym)
        if info:
            store_fundamentals(conn, symbol, info)
        update_data_status(conn, symbol, "info")
        logger.info(f"  {symbol}: {len(data)} candles, {len(info)} fundamental fields")

    vix_info = fetch_yf_info(YF_VIX)
    if vix_info:
        vix_data = {
            "timestamp": now.isoformat(),
            "open": vix_info.get("open", 0),
            "high": vix_info.get("dayHigh", 0),
            "low": vix_info.get("dayLow", 0),
            "close": vix_info.get("regularMarketPrice", vix_info.get("currentPrice", 0)),
            "change": vix_info.get("regularMarketChange", 0),
            "change_pct": vix_info.get("regularMarketChangePercent", 0),
        }
        store_vix_data(conn, vix_data["timestamp"], vix_data)
        update_data_status(conn, "VIX", "vix")
        logger.info(f"  VIX: close={vix_data['close']}, change_pct={vix_data['change_pct']:.2f}%")

    for yf_sym, symbol in [("^NSEI", "NIFTY"), ("^NSEBANK", "BANKNIFTY")]:
        logger.info(f"Fetching options for {symbol}")
        options_data = fetch_yf_options(yf_sym)
        if options_data:
            store_option_chains(conn, symbol, options_data)
            update_data_status(conn, symbol, "options")
            call_oi = sum(c["open_interest"] for ch in options_data["chains"] for c in ch["calls"])
            put_oi = sum(p["open_interest"] for ch in options_data["chains"] for p in ch["puts"])
            pcr = put_oi / call_oi if call_oi > 0 else 0
            logger.info(f"  {symbol}: PCR={pcr:.2f}, calls={len(options_data['chains'])}, total OI: CALL={call_oi}, PUT={put_oi}")

    for sym_name, yf_sym in STOCK_SYMBOLS:
        logger.info(f"Fetching {sym_name} ({yf_sym})")
        data = fetch_yf_ohlcv(yf_sym, interval="1m", period="1d")
        if data:
            store_price_data(conn, sym_name, data, "price_1m")
            update_data_status(conn, sym_name, "1m")
        info = fetch_yf_info(yf_sym)
        if info:
            store_fundamentals(conn, sym_name, info)
        update_data_status(conn, sym_name, "info")

    snapshot = fetch_market_snapshot(conn)
    logger.info(f"Market snapshot: NIFTY={snapshot.get('nifty')}, BANKNIFTY={snapshot.get('banknifty')}, VIX={snapshot.get('vix')}")

    conn.execute("DELETE FROM price_1m WHERE timestamp < datetime('now', '-1 day')")
    conn.execute("DELETE FROM price_5m WHERE timestamp < datetime('now', '-7 days')")
    conn.execute("DELETE FROM price_15m WHERE timestamp < datetime('now', '-30 days')")
    conn.execute("DELETE FROM price_1d WHERE timestamp < datetime('now', '-5 years')")
    conn.execute("DELETE FROM option_chain WHERE fetched_at < datetime('now', '-3 days')")
    conn.execute("DELETE FROM fundamentals WHERE timestamp < datetime('now', '-7 days')")
    conn.commit()
    conn.close()

    logger.info("Fetch complete!")


if __name__ == "__main__":
    fetch_all()
