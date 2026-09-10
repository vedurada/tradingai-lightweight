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

YF_INDICES = {"^NSEI": "NIFTY", "^NSEBANK": "BANKNIFTY", "^CNXFIN": "FINNIFTY", "^BSESN": "SENSEX"}
YF_VIX = "^INDIAVIX"
YF_ETFS = {"NIFTYBEES": "NIFTYBEES.NS", "BANKBEES": "BANKBEES.NS", "JUNIORBEES": "JUNIORBEES.NS"}

ALL_SYMBOLS = ["NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX", "VIX", "NIFTYBEES", "BANKBEES", "JUNIORBEES"]

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
    for inst in config["indices"]:
        conn.execute("INSERT OR IGNORE INTO symbols (symbol, name, yfinance_symbol, type, category, active, created_at) VALUES (?, ?, ?, 'index', 'INDEX', 1, datetime('now'))", (inst["symbol"], inst["name"], inst["yfinance_symbol"]))
        conn.execute("UPDATE symbols SET name=?, yfinance_symbol=?, active=1 WHERE symbol=?", (inst["name"], inst["yfinance_symbol"], inst["symbol"]))
    for inst in config["stocks"]:
        cap = inst.get("cap", "LARGE")
        conn.execute("INSERT OR IGNORE INTO symbols (symbol, name, yfinance_symbol, type, category, active, created_at) VALUES (?, ?, ?, 'stock', ?, 1, datetime('now'))", (inst["symbol"], inst["name"], inst["yfinance_symbol"], cap))
        conn.execute("UPDATE symbols SET name=?, yfinance_symbol=?, category=?, active=1 WHERE symbol=?", (inst["name"], inst["yfinance_symbol"], cap, inst["symbol"]))
    for sym, yf_sym in YF_ETFS.items():
        conn.execute("INSERT OR IGNORE INTO symbols (symbol, name, yfinance_symbol, type, category, active, created_at) VALUES (?, ?, ?, 'etf', 'ETF', 1, datetime('now'))", (sym, sym, yf_sym))
    conn.execute("INSERT OR IGNORE INTO symbols (symbol, name, yfinance_symbol, type, category, active, created_at) VALUES (?, ?, ?, 'vix', 'VOLATILITY', 1, datetime('now'))", ("VIX", "India VIX", YF_VIX))
    conn.commit()
    logger.info(f"Initialized symbols from config: {len(config['indices'])} indices, {len(config['stocks'])} stocks")


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
    """Income statement + balance sheet + cashflow (latest 4 periods each). Cached weekly by caller."""
    try:
        import math
        import yfinance as yf
        ticker = yf.Ticker(yf_symbol)
        data: dict = {}
        for stmt_name in ("financials", "balance_sheet", "cashflow"):
            try:
                stmt = getattr(ticker, stmt_name, None)
                if stmt is None or stmt.empty:
                    continue
                for col in list(stmt.columns)[:4]:
                    suffix = col.strftime("%Y-%m-%d") if hasattr(col, "strftime") else str(col)
                    for idx in stmt.index:
                        try:
                            val = stmt.loc[idx, col]
                        except Exception:
                            continue
                        if isinstance(val, (int, float)) and not math.isnan(val):
                            data[f"{stmt_name}.{idx}.{suffix}"] = float(val)
            except Exception as e:
                logger.warning(f"{stmt_name} skip for {yf_symbol}: {e}")
        return data
    except Exception as e:
        logger.error(f"Financials error for {yf_symbol}: {e}")
        return {}


def _safe_float(v, default: float = 0.0) -> float:
    try:
        f = float(v)
        if f != f:  # NaN
            return default
        return f
    except Exception:
        return default


def fetch_yf_extras(yf_symbol: str) -> dict:
    """Everything else Yahoo exposes per ticker: news, dividends, splits,
    analyst recommendations / price targets, earnings dates. Light calls only."""
    out: dict = {"dividends": [], "splits": [], "news": [], "recommendations": {}, "price_targets": {}, "earnings_dates": []}
    try:
        import yfinance as yf
        ticker = yf.Ticker(yf_symbol)
        try:
            divs = ticker.dividends
            if divs is not None and len(divs):
                out["dividends"] = [{"date": idx.strftime("%Y-%m-%d"), "value": float(val)} for idx, val in divs.tail(8).items()]
        except Exception:
            pass
        try:
            splits = ticker.splits
            if splits is not None and len(splits):
                out["splits"] = [{"date": idx.strftime("%Y-%m-%d"), "value": float(val)} for idx, val in splits.tail(8).items()]
        except Exception:
            pass
        try:
            recs = ticker.recommendations
            if recs is not None and len(recs):
                last = recs.iloc[-1].to_dict()
                out["recommendations"] = {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in last.items()}
        except Exception:
            pass
        try:
            tgt = getattr(ticker, "analyst_price_targets", None)
            if isinstance(tgt, dict) and tgt:
                out["price_targets"] = {k: _safe_float(v) if isinstance(v, (int, float)) else v for k, v in tgt.items()}
        except Exception:
            pass
        try:
            ed = ticker.earnings_dates
            if ed is not None and len(ed):
                out["earnings_dates"] = [str(idx.date()) if hasattr(idx, "date") else str(idx) for idx in list(ed.index)[:4]]
        except Exception:
            pass
        try:
            news = ticker.news or []
            for n in news[:10]:
                content = n.get("content", n) if isinstance(n, dict) else {}
                title = content.get("title", "") if isinstance(content, dict) else str(n)
                if not title:
                    continue
                pub = ""
                try:
                    pub_ts = (content.get("pubDate") or content.get("providerPublishTime") or "")
                    pub = str(pub_ts)[:19]
                except Exception:
                    pass
                provider = content.get("provider", {}) if isinstance(content, dict) else {}
                out["news"].append({
                    "headline": str(title)[:300],
                    "publisher": str(provider.get("displayName", "") if isinstance(provider, dict) else "")[:80],
                    "url": str(content.get("clickThroughUrl", {}).get("url", "") if isinstance(content.get("clickThroughUrl"), dict) else content.get("link", ""))[:500] if isinstance(content, dict) else "",
                    "published": pub,
                })
        except Exception:
            pass
    except Exception as e:
        logger.warning(f"Extras skip for {yf_symbol}: {e}")
    return out


def store_extras(conn: sqlite3.Connection, symbol: str, extras: dict) -> dict:
    """Persist news + corporate actions; return mergeable fundamentals fragment."""
    if not extras:
        return {}
    now = datetime.now(timezone.utc).isoformat()
    for d in extras.get("dividends", []) or []:
        try:
            conn.execute("INSERT OR IGNORE INTO corporate_actions (symbol, timestamp, action_type, value) VALUES (?, ?, 'DIVIDEND', ?)",
                         (symbol, d.get("date", now[:10]), _safe_float(d.get("value"))))
        except Exception:
            pass
    for s in extras.get("splits", []) or []:
        try:
            conn.execute("INSERT OR IGNORE INTO corporate_actions (symbol, timestamp, action_type, value) VALUES (?, ?, 'SPLIT', ?)",
                         (symbol, s.get("date", now[:10]), _safe_float(s.get("value"))))
        except Exception:
            pass
    for n in extras.get("news", []) or []:
        try:
            if not n.get("headline"):
                continue
            conn.execute("INSERT OR IGNORE INTO news (timestamp, symbol, headline, publisher, url) VALUES (?, ?, ?, ?, ?)",
                         (n.get("published") or now, symbol, n["headline"], n.get("publisher", ""), n.get("url", "")))
        except Exception:
            pass
    try:
        conn.commit()
    except Exception:
        pass
    return {
        "analyst_recommendation": extras.get("recommendations", {}) or {},
        "analyst_price_targets": extras.get("price_targets", {}) or {},
        "earnings_dates": extras.get("earnings_dates", []) or [],
        "latest_dividend": (extras.get("dividends", []) or [{}])[-1],
        "latest_split": (extras.get("splits", []) or [{}])[-1],
    }


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


NSE_FNO_SYMBOLS = {"NIFTY": "NIFTY", "BANKNIFTY": "BANKNIFTY", "FINNIFTY": "FINNIFTY"}


def fetch_nse_expiries(nse_symbol: str) -> list:
    """Authoritative weekly/monthly expiry dates from NSE (contract-info endpoint)."""
    try:
        from curl_cffi import requests as cr
    except Exception:
        logger.warning("curl_cffi missing, NSE expiries skipped")
        return []
    try:
        s = cr.Session(impersonate="chrome124")
        s.get("https://www.nseindia.com", timeout=20)
        r = s.get(f"https://www.nseindia.com/api/option-chain-contract-info?symbol={nse_symbol}", timeout=20,
                  headers={"Accept": "*/*", "Referer": "https://www.nseindia.com/"})
        d = r.json()
        dates = d.get("expiryDates", []) or []
        logger.info(f"NSE expiries {nse_symbol}: {dates[:4]}")
        return dates
    except Exception as e:
        logger.warning(f"NSE expiries skip {nse_symbol}: {e}")
        return []


def store_nse_expiries(conn: sqlite3.Connection, symbol: str, dates: list) -> int:
    from datetime import datetime as _dt
    now = datetime.now(timezone.utc).isoformat()
    n = 0
    for ds in dates or []:
        try:
            iso = _dt.strptime(str(ds).strip(), "%d-%b-%Y").strftime("%Y-%m-%d")
        except Exception:
            continue
        conn.execute("INSERT OR REPLACE INTO option_expiries (symbol, expiry, fetched_at) VALUES (?, ?, ?)", (symbol, iso, now))
        n += 1
    conn.commit()
    return n


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


def get_daily_ohlcv(conn: sqlite3.Connection, fetcher, symbol: str, yf_symbol: str, limit: int = 60) -> list[dict]:
    """Daily candles from DB if fresh, else fetch once and cache in price_1d."""
    try:
        row = conn.execute("SELECT timestamp FROM price_1d WHERE symbol=? ORDER BY timestamp DESC LIMIT 1", (symbol,)).fetchone()
        fresh = False
        if row:
            try:
                ts = datetime.fromisoformat(str(row["timestamp"]).replace("Z", "+00:00"))
                if (datetime.now(timezone.utc) - ts).total_seconds() < 6 * 3600:
                    fresh = True
            except Exception:
                pass
        if fresh:
            rows = conn.execute("SELECT timestamp, open, high, low, close, volume FROM price_1d WHERE symbol=? ORDER BY timestamp DESC LIMIT ?", (symbol, limit)).fetchall()
            data = [{"timestamp": r["timestamp"], "open": r["open"], "high": r["high"], "low": r["low"], "close": r["close"], "volume": r["volume"] or 0} for r in reversed(rows)]
            if len(data) >= 15:
                return data
    except Exception:
        pass
    data = fetcher.fetch_ohlcv(symbol, yf_symbol, period="6mo", interval="1d", limit=limit) or []
    for d in data:
        try:
            conn.execute("INSERT OR IGNORE INTO price_1d (symbol, timestamp, open, high, low, close, volume) VALUES (?, ?, ?, ?, ?, ?, ?)", (symbol, d.get("timestamp"), d.get("open"), d.get("high"), d.get("low"), d.get("close"), d.get("volume", 0)))
        except Exception:
            pass
    try:
        conn.commit()
    except Exception:
        pass
    return data


def _quote_from_info(symbol: str, info: dict) -> Optional[dict]:
    if not info or not isinstance(info, dict):
        return None
    price = info.get("regularMarketPrice", info.get("currentPrice", 0)) or 0
    if not price:
        return None
    prev = info.get("previousClose", info.get("regularMarketPreviousClose", 0)) or 0
    change = (price - prev) if prev else 0
    return {
        "symbol": symbol, "price": round(price, 2), "change": round(change, 2),
        "change_pct": round(change / prev * 100, 2) if prev else 0,
        "open": round(info.get("open", 0) or 0, 2), "high": round(info.get("dayHigh", 0) or 0, 2),
        "low": round(info.get("dayLow", 0) or 0, 2), "previous_close": round(prev, 2),
        "volume": info.get("volume", 0) or 0, "timestamp": datetime.now(timezone.utc).isoformat(), "stale": False,
    }


def _quote_from_latest_1m(conn: sqlite3.Connection, symbol: str) -> Optional[dict]:
    try:
        row = conn.execute("SELECT * FROM price_1m WHERE symbol=? ORDER BY timestamp DESC LIMIT 1", (symbol,)).fetchone()
        if not row:
            return None
        d = dict(row)
        price = d.get("close", 0) or 0
        prev_rows = conn.execute("SELECT close FROM price_1m WHERE symbol=? ORDER BY timestamp DESC LIMIT 2", (symbol,)).fetchall()
        prev = prev_rows[1]["close"] if len(prev_rows) > 1 else price
        change = (price - prev) if prev else 0
        return {
            "symbol": symbol, "price": round(price, 2), "change": round(change, 2),
            "change_pct": round(change / prev * 100, 2) if prev else 0,
            "open": d.get("open", 0) or 0, "high": d.get("high", 0) or 0, "low": d.get("low", 0) or 0,
            "previous_close": round(prev, 2), "volume": d.get("volume", 0) or 0,
            "timestamp": datetime.now(timezone.utc).isoformat(), "stale": False,
        }
    except Exception:
        return None


def store_regime_and_strategies(conn: sqlite3.Connection, symbol: str, info: dict) -> None:
    try:
        from fetch_market import MarketFetcher
        from indicators import calculate_all_indicators, calculate_pivot, calculate_cpr
        from regime import RegimeEngine
        from scenarios import ScenarioEngine
        from strategies import StrategyEngine
        from ai_outlook import AIOutlookEngine

        fetcher = MarketFetcher()
        config = load_config()
        yf_symbol = ""
        for inst in config["indices"] + config["stocks"]:
            if inst["symbol"] == symbol:
                yf_symbol = inst["yfinance_symbol"]
                break
        if not yf_symbol:
            return
        ohlcv = get_daily_ohlcv(conn, fetcher, symbol, yf_symbol)
        quote = fetcher.fetch_quote(symbol, yf_symbol)
        if not quote or quote.get("price", 0) == 0:
            # Fallback: build quote from fundamentals info dict or latest 1m candle.
            quote = _quote_from_info(symbol, info) or _quote_from_latest_1m(conn, symbol)
        if not quote or quote.get("price", 0) == 0:
            return
        indicators = calculate_all_indicators(ohlcv, quote) if ohlcv else {}
        if not indicators:
            indicators = {}
        pivot_data = calculate_pivot(quote)
        cpr_data = calculate_cpr(pivot_data)
        options_analysis = {"data_unavailable": True, "message": "Options data unavailable"}
        timestamp = datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')

        regime_info = {"regime": "UNKNOWN", "confidence": 0, "trend": "", "momentum": "", "volatility": ""}
        try:
            regime_engine = RegimeEngine()
            regime_info = regime_engine.evaluate(
                price=quote["price"], vwap=indicators.get("vwap", 0), prev_close=quote["previous_close"],
                rsi=indicators.get("rsi"), macd=indicators.get("macd"), adx=indicators.get("adx"),
                vix_price=0, bollinger=indicators.get("bollinger_bands"), pivot=pivot_data,
                support_resistance=indicators.get("support_resistance"), pcr=options_analysis.get("pcr"),
                volume=quote.get("volume"), avg_volume=indicators.get("avg_volume"),
            )
        except Exception:
            pass

        conn.execute("INSERT OR REPLACE INTO market_regime (symbol, timestamp, regime, confidence, evidence, trend, momentum, volatility) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (symbol, timestamp, regime_info.get("regime","UNKNOWN"), regime_info.get("confidence",0), "", regime_info.get("trend",""), regime_info.get("momentum",""), regime_info.get("volatility","")))

        ind = indicators if indicators else {}
        bb = ind.get("bollinger_bands", {}) if isinstance(ind.get("bollinger_bands"), dict) else {}
        pivot_d = pivot_data if pivot_data else {}
        cpr_d = cpr_data if cpr_data else {}
        macd_d = ind.get("macd") if isinstance(ind.get("macd"), dict) else {}
        sr = ind.get("support_resistance", {}) if isinstance(ind.get("support_resistance"), dict) else {}
        ind_vals = [symbol, timestamp, ind.get("ema9",0) or 0, ind.get("ema20",0) or 0, ind.get("ema50",0) or 0, ind.get("ema100",0) or 0, ind.get("ema200",0) or 0, ind.get("sma20",0) or 0, ind.get("sma50",0) or 0, ind.get("sma200",0) or 0, ind.get("vwap",0) or 0, ind.get("rsi",0) or 0, macd_d.get("macd",0) or 0, macd_d.get("signal",0) or 0, macd_d.get("histogram",0) or 0, ind.get("atr",0) or 0, ind.get("adx",0) or 0, ind.get("di_plus",0) or 0, ind.get("di_minus",0) or 0, bb.get("upper",0) if isinstance(bb,dict) else 0, bb.get("middle",0) if isinstance(bb,dict) else 0, bb.get("lower",0) if isinstance(bb,dict) else 0, bb.get("width",0) if isinstance(bb,dict) else 0, pivot_d.get("pivot",0), pivot_d.get("r1",0), pivot_d.get("s1",0), pivot_d.get("r2",0), pivot_d.get("s2",0), pivot_d.get("r3",0), pivot_d.get("s3",0), cpr_d.get("classification",""), quote.get("high",0), quote.get("low",0), 0, 0, quote.get("previous_close",0), 0, 0, json.dumps(sr)]
        conn.execute("INSERT OR REPLACE INTO indicators (symbol, timestamp, ema9, ema20, ema50, ema100, ema200, sma20, sma50, sma200, vwap, rsi, macd, macd_signal, macd_histogram, atr, adx, di_plus, di_minus, bollinger_upper, bollinger_middle, bollinger_lower, bollinger_width, pivot, r1, s1, r2, s2, r3, s3, cpr_classification, day_high, day_low, prev_day_high, prev_day_low, prev_day_close, open_range_high, open_range_low, support_resistance) VALUES ({})".format(",".join(["?" for _ in ind_vals])), ind_vals)

        scenarios_d = {}
        strategy = {}
        ai_outlook = {}
        vix_now = 0
        try:
            vrow = conn.execute("SELECT close FROM vix_data ORDER BY timestamp DESC LIMIT 1").fetchone()
            if vrow:
                vix_now = vrow["close"] or 0
        except Exception:
            pass
        try:
            if ohlcv and indicators.get("rsi") is not None and indicators.get("adx") is not None:
                scenario_engine = ScenarioEngine()
                scenarios_d = scenario_engine.generate(regime_info.get("regime","UNKNOWN"), ind.get("support_resistance",{}).get("support",[]) if isinstance(ind.get("support_resistance"),dict) else [], ind.get("support_resistance",{}).get("resistance",[]) if isinstance(ind.get("support_resistance"),dict) else [], quote["price"], adx=indicators.get("adx"), vix_price=vix_now) or {}
                strategy_engine = StrategyEngine()
                # Indexes get option spreads; stocks/ETFs get BUY/HOLD/EXIT.
                sr = ind.get("support_resistance", {}) if isinstance(ind.get("support_resistance"), dict) else {}
                strategy = strategy_engine.select(regime_info.get("regime","UNKNOWN"), regime_info.get("confidence",0), "GOOD" if ohlcv else "PARTIAL", vix_price=vix_now, vix_change_pct=0, symbol=symbol, price=quote.get("price",0), vwap=indicators.get("vwap",0), rsi=indicators.get("rsi"), adx=indicators.get("adx"), support=sr.get("support", []), resistance=sr.get("resistance", []), atr=indicators.get("atr")) or {}
                ai_engine = AIOutlookEngine()
                ai_outlook = ai_engine.generate(symbol, {**quote, **ind, "regime": regime_info.get("regime","UNKNOWN"), "options_unavailable": options_analysis.get("data_unavailable", False)}) or {}
        except Exception as e:
            logger.warning(f"Scenario/strategy build skipped for {symbol}: {e}")

        if scenarios_d:
            b = scenarios_d.get("bullish", {}) or {}
            be = scenarios_d.get("bearish", {}) or {}
            r = scenarios_d.get("range", {}) or {}
            conn.execute("INSERT OR REPLACE INTO scenarios (symbol, timestamp, bullish_trigger, bullish_confirmation, bullish_target, bullish_invalidation, bearish_trigger, bearish_confirmation, bearish_target, bearish_invalidation, range_condition, range_strategy, range_invalidation) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (symbol, timestamp, b.get("trigger",""), b.get("confirmation",""), str(b.get("target","")), b.get("invalidation",""), be.get("trigger",""), be.get("confirmation",""), str(be.get("target","")), be.get("invalidation",""), r.get("condition",""), r.get("strategy_environment",""), r.get("invalidation","")))
        if strategy:
            strat_list = strategy.get("strategies", []) if isinstance(strategy, dict) else []
            primary = strat_list[0] if strat_list else {}
            if primary:
                conn.execute("INSERT OR REPLACE INTO strategies (symbol, timestamp, strategy, market_condition, expiry, legs, entry_trigger, maximum_profit, maximum_loss, breakeven, stop_loss, target, adjustment, exit, time_based_exit) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (symbol, timestamp, primary.get("strategy",""), primary.get("market_condition",""), primary.get("expiry",""), json.dumps({"legs": primary.get("legs",[]), "all_strategies": strat_list}), primary.get("entry_trigger",""), primary.get("maximum_profit",""), primary.get("maximum_loss",""), primary.get("breakeven",""), primary.get("stop_loss",""), primary.get("target",""), primary.get("adjustment",""), primary.get("exit",""), primary.get("time_based_exit","")))
        conn.execute("INSERT OR REPLACE INTO ai_outlooks (symbol, timestamp, outlook, data_quality) VALUES (?, ?, ?, ?)", (symbol, timestamp, json.dumps(ai_outlook) if ai_outlook else "{}", quote.get("stale",False) and "STALE" or "GOOD"))
        conn.commit()
    except Exception as e:
        logger.error(f"Regime/strategy error for {symbol}: {repr(e)}")
    finally:
        try:
            conn.commit()
        except Exception:
            pass


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


def _fetch_symbol_minute(conn: sqlite3.Connection, symbol: str, yf_symbol: str, with_regime: bool = True, with_investment: bool = False) -> None:
    """Fetch 1m candles + AI-assisted screen for one symbol."""
    data = fetch_yf_ohlcv(yf_symbol, interval="1m", period="1d")
    if data:
        store_price_data(conn, symbol, data, "price_1m")
        update_data_status(conn, symbol, "1m")
    if with_regime:
        try:
            store_regime_and_strategies(conn, symbol, {})
        except Exception as e:
            logger.error(f"Regime/strategy error for {symbol}: {repr(e)}")
    if with_investment:
        try:
            store_investment_views(conn, symbol)
        except Exception as e:
            logger.error(f"Investment view error for {symbol}: {repr(e)}")


def store_investment_views(conn: sqlite3.Connection, symbol: str) -> None:
    """SHORT (weeks) + LONG (months) investment views from daily candles + fundamentals."""
    from investment import short_term_view, long_term_view, swing_levels
    rows = conn.execute("SELECT close FROM price_1d WHERE symbol=? ORDER BY timestamp DESC LIMIT 250", (symbol,)).fetchall()
    closes = [r["close"] for r in reversed(rows) if r["close"]]
    if len(closes) < 20:
        return
    qrow = conn.execute("SELECT close FROM price_1m WHERE symbol=? ORDER BY timestamp DESC LIMIT 1", (symbol,)).fetchone()
    price = (qrow["close"] if qrow and qrow["close"] else closes[-1]) or 0
    if not price:
        return
    fundamentals: dict = {}
    try:
        frow = conn.execute("SELECT data FROM fundamentals WHERE symbol=? ORDER BY timestamp DESC LIMIT 1", (symbol,)).fetchone()
        if frow and frow["data"]:
            fundamentals = json.loads(frow["data"])
    except Exception:
        pass
    from datetime import date as _date
    try:
        from zoneinfo import ZoneInfo
        today = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%Y-%m-%d")
    except Exception:
        today = _date.today().isoformat()
    short = short_term_view(closes, price)
    long_v = long_term_view(closes, fundamentals, price)
    lv = swing_levels(closes, price)
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO investment_views (symbol, date, horizon, rating, target_price, stop_price, fair_value, reason, confidence, score, created_at)
           VALUES (?, ?, 'SHORT', ?, ?, ?, NULL, ?, ?, ?, ?)
           ON CONFLICT(symbol, date, horizon) DO UPDATE SET rating=excluded.rating, target_price=excluded.target_price,
                stop_price=excluded.stop_price, reason=excluded.reason, confidence=excluded.confidence, score=excluded.score, created_at=excluded.created_at""",
        (symbol, today, short["rating"], lv["target"], lv["stop"], short["reason"], short["confidence"], short["score"], now))
    conn.execute(
        """INSERT INTO investment_views (symbol, date, horizon, rating, target_price, stop_price, fair_value, reason, confidence, score, created_at)
           VALUES (?, ?, 'LONG', ?, NULL, NULL, ?, ?, ?, ?, ?)
           ON CONFLICT(symbol, date, horizon) DO UPDATE SET rating=excluded.rating, target_price=excluded.target_price,
                stop_price=excluded.stop_price, fair_value=excluded.fair_value, reason=excluded.reason, confidence=excluded.confidence, score=excluded.score, created_at=excluded.created_at""",
        (symbol, today, long_v["rating"], long_v.get("fair_value"), long_v["reason"], long_v["confidence"], long_v["score"], now))
    conn.commit()


def fetch_all() -> None:
    config = load_config()
    settings = load_settings()
    init_database()
    conn = get_db()
    init_symbols(conn, config)

    now = datetime.now(timezone.utc)
    is_market_hours = now.weekday() < 5 and 9 <= now.hour <= 15
    minute = now.minute

    logger.info(f"Fetching data... market_hours={is_market_hours}")

    indices = config.get("indices", [])
    stocks = config.get("stocks", [])
    large_caps = [s for s in stocks if s.get("cap", "LARGE") == "LARGE"]
    mid_caps = [s for s in stocks if s.get("cap") == "MID"]
    small_caps = [s for s in stocks if s.get("cap") == "SMALL"]

    for inst in indices:
        symbol, yf_sym = inst["symbol"], inst["yfinance_symbol"]
        logger.info(f"Fetching {symbol} ({yf_sym})")
        _fetch_symbol_minute(conn, symbol, yf_sym, with_regime=True)

    vix_data_1m = fetch_yf_ohlcv(YF_VIX, interval="1m", period="1d")
    if vix_data_1m:
        store_price_data(conn, "VIX", vix_data_1m, "price_1m")
        last = vix_data_1m[-1]
        prev = vix_data_1m[-2]["close"] if len(vix_data_1m) > 1 else last["close"]
        store_vix_data(conn, datetime.now(timezone.utc).isoformat(), {
            "open": last["open"], "high": last["high"], "low": last["low"], "close": last["close"],
            "change": last["close"] - prev, "change_pct": (last["close"] - prev) / prev * 100 if prev else 0,
        })
        update_data_status(conn, "VIX", "vix")

    for etf_sym, etf_yf in YF_ETFS.items():
        data = fetch_yf_ohlcv(etf_yf, interval="1m", period="1d")
        if data:
            store_price_data(conn, etf_sym, data, "price_1m")
            update_data_status(conn, etf_sym, "1m")

    for inst in large_caps:
        _fetch_symbol_minute(conn, inst["symbol"], inst["yfinance_symbol"], with_regime=True, with_investment=True)

    if minute % 5 == 0:
        for inst in mid_caps:
            _fetch_symbol_minute(conn, inst["symbol"], inst["yfinance_symbol"], with_regime=True, with_investment=True)
        for yf_sym, symbol in [("^NSEI", "NIFTY"), ("^NSEBANK", "BANKNIFTY")]:
            logger.info(f"Fetching options for {symbol}")
            options_data = fetch_yf_options(yf_sym)
            if options_data:
                store_option_chains(conn, symbol, options_data)
                update_data_status(conn, symbol, "options")
                call_oi = sum(c["open_interest"] for ch in options_data["chains"] for c in ch["calls"])
                put_oi = sum(p["open_interest"] for ch in options_data["chains"] for p in ch["puts"])
                pcr = put_oi / call_oi if call_oi > 0 else 0
                logger.info(f"  {symbol}: PCR={pcr:.2f}, expiries={len(options_data['chains'])}")

    if minute % 15 == 0:
        for inst in small_caps:
            _fetch_symbol_minute(conn, inst["symbol"], inst["yfinance_symbol"], with_regime=True, with_investment=True)
        # Company snapshot: info + news/actions/analyst views merged into fundamentals.
        for inst in indices + large_caps:
            try:
                info = fetch_yf_info(inst["yfinance_symbol"])
                extra_frag: dict = {}
                try:
                    extras = fetch_yf_extras(inst["yfinance_symbol"])
                    extra_frag = store_extras(conn, inst["symbol"], extras)
                except Exception as e:
                    logger.warning(f"Extras skip {inst['symbol']}: {e}")
                merged = dict(info or {})
                merged.update({k: v for k, v in extra_frag.items() if v})
                if merged:
                    store_fundamentals(conn, inst["symbol"], merged)
            except Exception as e:
                logger.warning(f"Fundamentals skip {inst['symbol']}: {e}")
        update_data_status(conn, "ALL", "info")

    # Daily reference-data refresh (first runs of the session, IST): live NSE
    # lot sizes + authoritative index expiries. Re-checks daily so any NSE
    # change flows into the DB/website automatically; writes only on change.
    try:
        from datetime import timedelta as _td
        _ist = now + _td(hours=5, minutes=30)
        if _ist.weekday() < 5 and _ist.hour == 9 and _ist.minute < 3:
            try:
                from lot_sizes import refresh_lot_sizes
                logger.info(f"lots refresh: {refresh_lot_sizes(conn)}")
            except Exception as e:
                logger.warning(f"lot refresh skip: {e}")
            for _nse, _sym in NSE_FNO_SYMBOLS.items():
                _dates = fetch_nse_expiries(_nse)
                if _dates:
                    _k = store_nse_expiries(conn, _sym, _dates)
                    update_data_status(conn, _sym, "options")
                    logger.info(f"  {_sym}: { _k} NSE expiries stored")
    except Exception as e:
        logger.warning(f"daily reference refresh skip: {e}")

    # Weekly deep pass (Monday): extras for MID/SMALL + financial statements for LARGE.
    if now.weekday() == 0 and now.hour == 9 and minute < 15:
        for inst in mid_caps + small_caps:
            try:
                extras = fetch_yf_extras(inst["yfinance_symbol"])
                frag = store_extras(conn, inst["symbol"], extras)
                if frag:
                    store_fundamentals(conn, inst["symbol"], frag)
            except Exception as e:
                logger.warning(f"Weekly extras skip {inst['symbol']}: {e}")
        for inst in large_caps:
            try:
                stmts = fetch_yf_financials(inst["yfinance_symbol"])
                if stmts:
                    store_fundamentals(conn, inst["symbol"], {"financial_statements": stmts})
            except Exception as e:
                logger.warning(f"Weekly financials skip {inst['symbol']}: {e}")
        update_data_status(conn, "WEEKLY", "info")

    try:
        build_breadth(conn)
    except Exception as e:
        logger.warning(f"Breadth skip: {e}")
    try:
        fetch_nse_index_breadth(conn)
    except Exception as e:
        logger.warning(f"NSE breadth skip: {e}")
    snapshot = fetch_market_snapshot(conn)
    logger.info(f"Market snapshot: NIFTY={snapshot.get('nifty')}, BANKNIFTY={snapshot.get('banknifty')}, VIX={snapshot.get('vix')}")

    conn.execute("DELETE FROM price_1m WHERE timestamp < datetime('now', '-2 day')")
    conn.execute("DELETE FROM option_chain WHERE fetched_at < datetime('now', '-3 days')")
    conn.execute("DELETE FROM fundamentals WHERE timestamp < datetime('now', '-7 days')")
    conn.execute("DELETE FROM news WHERE timestamp < datetime('now', '-30 days')")
    conn.execute("DELETE FROM index_breadth WHERE timestamp < datetime('now', '-7 days')")
    conn.commit()
    conn.close()

    logger.info("Fetch complete!")


NSE_INDEX_MAP = {"NIFTY 50": "NIFTY", "NIFTY BANK": "BANKNIFTY", "NIFTY FIN SERVICE": "FINNIFTY",
                 "NIFTY FINANCIAL SERVICES": "FINNIFTY", "INDIA VIX": "VIX"}


def fetch_nse_index_breadth(conn: sqlite3.Connection) -> None:
    """NSE allIndices: official quotes + advances/declines per index (one light call)."""
    try:
        from curl_cffi import requests as cr
    except Exception:
        return
    try:
        s = cr.Session(impersonate="chrome124")
        s.get("https://www.nseindia.com", timeout=20)
        r = s.get("https://www.nseindia.com/api/allIndices", timeout=20,
                  headers={"Accept": "*/*", "Referer": "https://www.nseindia.com/"})
        data = r.json().get("data", [])
    except Exception as e:
        logger.warning(f"NSE index breadth skip: {e}")
        return
    now = datetime.now(timezone.utc).isoformat()
    n = 0
    for x in data:
        # Exact match only: fuzzy matching would map e.g. NIFTY 500 -> NIFTY.
        name = (x.get("indexSymbol") or x.get("index") or "").strip().upper()
        sym = NSE_INDEX_MAP.get(name)
        if not sym:
            continue
        try:
            conn.execute(
                """INSERT OR IGNORE INTO index_breadth
                   (index_name, timestamp, last, change_pct, advances, declines, unchanged, open, high, low, prev_close)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (sym, now,
                 float(x.get("last") or 0), float(x.get("percentChange") or 0),
                 int(x.get("advances") or 0), int(x.get("declines") or 0), int(x.get("unchanged") or 0),
                 float(x.get("open") or 0), float(x.get("high") or 0), float(x.get("low") or 0),
                 float(x.get("previousClose") or 0)))
            n += 1
        except Exception:
            continue
    conn.commit()
    if n:
        logger.info(f"NSE index breadth: {n} indices")


def build_breadth(conn: sqlite3.Connection) -> None:
    """Advance/decline from latest 1m closes vs today's open (fallback: price_1d prev close)."""
    rows = conn.execute("""
        SELECT p.symbol, p.close AS last_close,
               (SELECT open FROM price_1m WHERE symbol=p.symbol AND date(timestamp)=date(p.timestamp) ORDER BY timestamp ASC LIMIT 1) AS day_open,
               (SELECT close FROM price_1d WHERE symbol=p.symbol ORDER BY timestamp DESC LIMIT 1) AS daily_prev
        FROM (SELECT symbol, MAX(timestamp) AS ts FROM price_1m GROUP BY symbol) m
        JOIN price_1m p ON p.symbol=m.symbol AND p.timestamp=m.ts
    """).fetchall()
    adv = dec = unch = 0
    for r in rows:
        try:
            last_c = r["last_close"] or 0
            prev_c = r["day_open"] or r["daily_prev"] or 0
            if not prev_c:
                continue
            chg = (last_c - prev_c) / prev_c * 100
            if chg > 0.05:
                adv += 1
            elif chg < -0.05:
                dec += 1
            else:
                unch += 1
        except Exception:
            continue
    ratio = (adv / dec) if dec else float(adv)
    conn.execute("INSERT OR REPLACE INTO market_breadth (timestamp, advances, declines, unchanged, advance_decline_ratio, pct_above_ema20, pct_above_ema50, pct_above_ema200) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                 (datetime.now(timezone.utc).isoformat(), adv, dec, unch, round(ratio, 2), 0, 0, 0))
    conn.commit()
    logger.info(f"Breadth: adv={adv} dec={dec} unch={unch}")

if __name__ == "__main__":
    fetch_all()
