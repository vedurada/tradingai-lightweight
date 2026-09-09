from __future__ import annotations

import yfinance as yf
import logging
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger("tradingai.fetch")


class MarketFetcher:
    def __init__(self) -> None:
        self._cache: dict[str, Any] = {}
        self._cache_time: dict[str, float] = {}
        self._cache_ttl = 300

    def _cached(self, key: str, ttl: float = 300) -> Optional[Any]:
        if key in self._cache and key in self._cache_time:
            if (datetime.now(timezone.utc).timestamp() - self._cache_time[key]) < ttl:
                return self._cache[key]
        return None

    def _set_cache(self, key: str, value: Any, ttl: float = 300) -> None:
        self._cache[key] = value
        self._cache_time[key] = datetime.now(timezone.utc).timestamp()

    def fetch_quote(self, symbol: str, yf_symbol: str) -> Optional[dict]:
        cached = self._cached(f"quote:{symbol}")
        if cached:
            return cached
        try:
            ticker = yf.Ticker(yf_symbol)
            info = ticker.info or {}
            price = info.get("regularMarketPrice", info.get("currentPrice", 0))
            prev_close = info.get("previousClose", 0)
            open_price = info.get("open", 0)
            high = info.get("dayHigh", 0)
            low = info.get("dayLow", 0)
            volume = info.get("volume", 0)

            if price == 0:
                hist = ticker.history(period="1d")
                if not hist.empty:
                    row = hist.iloc[-1]
                    price = float(row["Close"])
                    open_price = float(row["Open"])
                    high = float(row["High"])
                    low = float(row["Low"])
                    volume = int(row["Volume"])

            if prev_close == 0:
                prev_close = price

            change = price - prev_close
            change_pct = (change / prev_close * 100) if prev_close else 0

            quote = {
                "symbol": symbol,
                "price": round(price, 2),
                "change": round(change, 2),
                "change_pct": round(change_pct, 2),
                "open": round(open_price, 2),
                "high": round(high, 2),
                "low": round(low, 2),
                "previous_close": round(prev_close, 2),
                "volume": volume,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            self._set_cache(f"quote:{symbol}", quote)
            return quote
        except Exception as e:
            logger.error(f"Quote error for {symbol}: {e}")
            return None

    def fetch_ohlcv(self, symbol: str, yf_symbol: str, period: str = "60d", interval: str = "1d", limit: int = 100) -> list[dict]:
        cached = self._cached(f"ohlcv:{symbol}:{interval}:{limit}")
        if cached:
            return cached
        try:
            ticker = yf.Ticker(yf_symbol)
            hist = ticker.history(period=period, interval=interval)
            if hist.empty:
                return []
            data = []
            for idx, row in hist.tail(limit).iterrows():
                data.append({
                    "timestamp": idx.isoformat(),
                    "open": float(row["Open"]),
                    "high": float(row["High"]),
                    "low": float(row["Low"]),
                    "close": float(row["Close"]),
                    "volume": int(row["Volume"]),
                })
            self._set_cache(f"ohlcv:{symbol}:{interval}:{limit}", data, ttl=600)
            return data
        except Exception as e:
            logger.error(f"OHLCV error for {symbol}: {e}")
            return []

    def fetch_vix(self) -> Optional[dict]:
        cached = self._cached("vix")
        if cached:
            return cached
        try:
            ticker = yf.Ticker("^VIX")
            info = ticker.info or {}
            price = info.get("regularMarketPrice", info.get("currentPrice", 0))
            prev = info.get("previousClose", price + 0.15)
            change = price - prev
            change_pct = (change / prev * 100) if prev else 0
            vix = {
                "symbol": "INDIA VIX",
                "price": round(price, 2),
                "change": round(change, 2),
                "change_pct": round(change_pct, 2),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            self._set_cache("vix", vix)
            return vix
        except Exception as e:
            logger.error(f"VIX error: {e}")
            return None

    def fetch_option_chain(self, symbol: str, yf_symbol: str) -> Optional[dict]:
        cached = self._cached(f"options:{symbol}")
        if cached:
            return cached
        try:
            ticker = yf.Ticker(yf_symbol)
            expirations = ticker.options
            if not expirations:
                return None
            target_expiry = expirations[0]
            opt = ticker.option_chain(target_expiry)
            underlying_price = float(ticker.info.get("regularMarketPrice", 0))
            if underlying_price == 0:
                underlying_price = float(ticker.info.get("currentPrice", 0))

            calls = [
                {
                    "strike": float(row["strike"]),
                    "last_price": float(row["lastPrice"]),
                    "volume": int(row["volume"]),
                    "open_interest": int(row["openInterest"]),
                    "change_in_oi": int(row.get("changeInOpenInterest", 0)),
                    "implied_volatility": float(row.get("impliedVolatility", 0)),
                    "bid": float(row["bid"]),
                    "ask": float(row["ask"]),
                    "option_type": "CE",
                }
                for _, row in opt.calls.iterrows()
            ]
            puts = [
                {
                    "strike": float(row["strike"]),
                    "last_price": float(row["lastPrice"]),
                    "volume": int(row["volume"]),
                    "open_interest": int(row["openInterest"]),
                    "change_in_oi": int(row.get("changeInOpenInterest", 0)),
                    "implied_volatility": float(row.get("impliedVolatility", 0)),
                    "bid": float(row["bid"]),
                    "ask": float(row["ask"]),
                    "option_type": "PE",
                }
                for _, row in opt.puts.iterrows()
            ]

            chain = {
                "symbol": symbol,
                "expiry": target_expiry,
                "underlying_price": underlying_price,
                "calls": calls,
                "puts": puts,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            self._set_cache(f"options:{symbol}", chain, ttl=300)
            return chain
        except Exception as e:
            logger.error(f"Option chain error for {symbol}: {e}")
            return None