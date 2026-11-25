"""Zerodha Kite Connect live data provider.

Drops in as a replacement for MarketDataProvider (yfinance) in LiveEngine.
Implements get_quote(symbol) and get_5m_candles(symbol) returning the same
payload shape as app.market.provider.MarketDataProvider so LiveEngine works
unchanged when injected via quote_fn/candles_fn.

Credentials are read from /opt/tradingai/.env.zerodha:
  ZERODHA_MODE=SHADOW|LIVE
  KITE_API_KEY=...
  KITE_API_SECRET=...
  KITE_ACCESS_TOKEN=...
  REDIRECT_URL=...

Zerodha instrument mapping:
  NIFTY    -> trading symbol "NSE:NIFTY 50", token 256265
  BANKNIFTY -> trading symbol "NSE:NIFTY BANK", token 260105
  INDIA_VIX -> trading symbol "NSE:INDIA VIX", token 424963
"""

import os
import logging
from datetime import datetime, timedelta, timezone, date
from zoneinfo import ZoneInfo

try:
    from kiteconnect import KiteConnect
except ImportError:  # pragma: no cover
    KiteConnect = None

from app.market import cache as _cache
from app.market import flight as _flight

_IST = ZoneInfo("Asia/Kolkata")
_STALE_QUOTE_S = 3600
_STALE_CANDLE_S = 900

log = logging.getLogger("tradingai.zerodha")

_ZERODHA_ENV = "/opt/tradingai/.env.zerodha"

_SPOT_SYMBOL_MAP = {
    "NIFTY": "NSE:NIFTY 50",
    "BANKNIFTY": "NSE:NIFTY BANK",
    "INDIA_VIX": "NSE:INDIA VIX",
}

_INSTRUMENT_TOKEN_MAP = {
    "NIFTY": 256265,
    "BANKNIFTY": 260105,
    "INDIA_VIX": 424963,
}

_SYMBOL_TO_ZERODHA = {
    "^NSEI": "NSE:NIFTY 50",
    "^NSEBANK": "NSE:NIFTY BANK",
    "^INDIAVIX": "NSE:INDIA VIX",
    "NIFTY": "NSE:NIFTY 50",
    "BANKNIFTY": "NSE:NIFTY BANK",
    "INDIA_VIX": "NSE:INDIA VIX",
}

_ZERODHA_TO_INSTRUMENT = {v: k for k, v in _SPOT_SYMBOL_MAP.items()}


def _load_env():
    cfg = {}
    if os.path.exists(_ZERODHA_ENV):
        with open(_ZERODHA_ENV) as f:
            for line in f:
                s = line.strip()
                if "=" in s and not s.startswith("#"):
                    k, v = s.split("=", 1)
                    cfg[k.strip()] = v.strip()
    return cfg


def _kite_client():
    if KiteConnect is None:
        log.error("kiteconnect package not installed")
        return None, None
    cfg = _load_env()
    api_key = cfg.get("KITE_API_KEY")
    access_token = cfg.get("KITE_ACCESS_TOKEN")
    if not api_key or not access_token:
        log.warning("Zerodha credentials not configured in %s", _ZERODHA_ENV)
        return None, None
    kc = KiteConnect(api_key=api_key)
    kc.set_access_token(access_token)
    mode = cfg.get("ZERODHA_MODE", "SHADOW")
    return kc, mode


def _to_ist_iso(ts):
    if hasattr(ts, "to_pydatetime"):
        dt = ts.to_pydatetime()
    elif isinstance(ts, str):
        dt = datetime.fromisoformat(ts)
    elif isinstance(ts, datetime):
        dt = ts
    else:
        dt = ts
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_IST).isoformat()


def _classify_error(exc):
    msg = str(exc).lower()
    if "429" in msg or "rate limit" in msg or "too many requests" in msg:
        return "RATE_LIMITED"
    if "timeout" in msg or "timed out" in msg:
        return "TIMEOUT"
    if "name resolution" in msg or "nodename nor servname" in msg or "getaddrinfo" in msg:
        return "DNS_ERROR"
    if "token" in msg or "expired" in msg or "unauthorized" in msg or "403" in msg or "401" in msg:
        return "AUTH_ERROR"
    return "API_ERROR"


def _quote_touch(hit):
    hit["age_seconds"] = round(
        (datetime.now(_IST) - datetime.fromisoformat(hit["timestamp"])).total_seconds(), 1)
    if hit["age_seconds"] >= _STALE_QUOTE_S:
        hit["state"] = "STALE"
    return hit


def _candles_touch(hit):
    try:
        now_ist = datetime.now(_IST)
        for c in hit.get("candles", []):
            try:
                cdt = datetime.fromisoformat(c["timestamp"])
                c["is_complete"] = (now_ist - cdt).total_seconds() >= 5 * 60
            except Exception:
                continue
        data_ts = None
        try:
            data_ts = hit.get("candles")[-1]["timestamp"] if hit.get("candles") else None
        except Exception:
            data_ts = None
        if data_ts:
            age = (now_ist - datetime.fromisoformat(data_ts)).total_seconds()
            hit["state"] = "STALE" if age >= _STALE_CANDLE_S else "LIVE"
            hit["age_seconds"] = round(age, 1)
        else:
            hit["state"] = "STALE"
    except Exception:
        try:
            hit["state"] = "STALE"
        except Exception:
            pass
    return hit


class ZerodhaDataProvider:
    """Zerodha Kite Connect data source with same interface as MarketDataProvider."""

    def __init__(self, use_cache=True):
        self.kc, self.mode = _kite_client()
        self.use_cache = use_cache
        self.active_provider = "zerodha"
        self._instrument_tokens = dict(_INSTRUMENT_TOKEN_MAP)

    def _zerodha_symbol(self, symbol):
        return _SYMBOL_TO_ZERODHA.get(symbol, symbol)

    def _instrument_token(self, symbol):
        tok = self._instrument_tokens.get(symbol.upper())
        if tok is not None:
            return tok
        zs = _SYMBOL_TO_ZERODHA.get(symbol.upper())
        if zs:
            key = _ZERODHA_TO_INSTRUMENT.get(zs)
            if key:
                return self._instrument_tokens.get(key.upper())
        return None

    def get_quote(self, symbol, use_cache=None):
        use_cache = self.use_cache if use_cache is None else use_cache
        zsymbol = self._zerodha_symbol(symbol)

        if use_cache:
            hit, _ = _cache.get(symbol, "quote")
            if hit is not None:
                return _quote_touch(hit)

        leader, ev = _flight.begin(("quote", symbol))
        try:
            if not leader:
                hit, _ = _cache.get(symbol, "quote")
                if hit is not None:
                    return _quote_touch(hit)
            return self._fetch_quote(zsymbol, symbol)
        finally:
            if leader:
                _flight.end(("quote", symbol), ev)

    def _fetch_quote(self, zsymbol, original_symbol):
        if self.kc is None:
            return {"state": "UNAVAILABLE", "source": "zerodha",
                    "symbol": original_symbol,
                    "error": "KiteConnect client not configured"}

        try:
            quote_map = self.kc.quote([zsymbol])
        except Exception as e:
            state = _classify_error(e)
            log.warning("zerodha quote FAILED symbol=%s state=%s",
                        original_symbol, state)
            return {"state": state if state != "TIMEOUT" else "API_ERROR",
                    "source": "zerodha", "symbol": original_symbol,
                    "error": str(e)[:200]}

        q = quote_map.get(zsymbol, {})
        if not q:
            return {"state": "UNAVAILABLE", "source": "zerodha",
                    "symbol": original_symbol}

        last_price = q.get("last_price")
        if not last_price:
            ohlc = q.get("ohlc", {}) or {}
            last_price = ohlc.get("close")
        try:
            price = float(last_price)
        except (TypeError, ValueError):
            return {"state": "UNAVAILABLE", "source": "zerodha",
                    "symbol": original_symbol}
        if not (price > 0):
            return {"state": "UNAVAILABLE", "source": "zerodha",
                    "symbol": original_symbol}

        ltt = q.get("last_trade_time")
        quote_ts = _to_ist_iso(ltt) if ltt else datetime.now(_IST).isoformat()
        now_ist = datetime.now(_IST)
        try:
            age_s = (now_ist - datetime.fromisoformat(quote_ts)).total_seconds()
        except Exception:
            age_s = 0.0

        ohlc = q.get("ohlc", {}) or {}
        prev_close = ohlc.get("close")
        try:
            prev_close = float(prev_close)
        except (TypeError, ValueError):
            prev_close = None
        if prev_close and prev_close > 0:
            change = float(price - prev_close)
            change_pct = float(change / prev_close * 100)
        else:
            change, change_pct = None, None

        state = "LIVE" if age_s < _STALE_QUOTE_S else "STALE"
        out = {
            "symbol": original_symbol,
            "price": price,
            "change": change,
            "change_pct": change_pct,
            "prev_close": prev_close,
            "timestamp": quote_ts,
            "age_seconds": round(age_s, 1),
            "source": "zerodha",
            "state": state,
            "mode": self.mode,
        }
        _cache.put(original_symbol, "quote", out, quote_ts, state)
        return out

    def get_5m_candles(self, symbol, periods=100, use_cache=None):
        use_cache = self.use_cache if use_cache is None else use_cache

        if use_cache:
            hit, _ = _cache.get(symbol, "candles")
            if hit is not None:
                return _candles_touch(hit)

        leader, ev = _flight.begin(("candles", symbol))
        try:
            if not leader:
                hit, _ = _cache.get(symbol, "candles")
                if hit is not None:
                    return _candles_touch(hit)
            return self._fetch_candles(symbol, periods)
        finally:
            if leader:
                _flight.end(("candles", symbol), ev)

    def _fetch_candles(self, symbol, periods):
        if self.kc is None:
            return {"state": "UNAVAILABLE", "source": "zerodha",
                    "symbol": symbol,
                    "error": "KiteConnect client not configured"}

        token = self._instrument_token(symbol)
        if token is None:
            return {"state": "UNAVAILABLE", "source": "zerodha",
                    "symbol": symbol,
                    "error": "no instrument token for " + symbol}

        now_ist = datetime.now(_IST)
        today = now_ist.date().isoformat()

        from_date = (now_ist - timedelta(days=5)).date().isoformat()
        to_date = today

        try:
            rows = self.kc.historical_data(
                instrument_token=token,
                from_date=from_date,
                to_date=to_date,
                interval="5minute",
                continuous=False,
            )
        except Exception as e:
            state = _classify_error(e)
            log.warning("zerodha candles FAILED symbol=%s state=%s",
                        symbol, state)
            return {"state": state if state != "TIMEOUT" else "API_ERROR",
                    "source": "zerodha", "symbol": symbol,
                    "error": str(e)[:200]}

        if not rows:
            return {"state": "UNAVAILABLE", "source": "zerodha",
                    "symbol": symbol}

        candles = []
        for row in rows:
            try:
                ts = _to_ist_iso(row["date"])
                o, h, l, c = (float(row["open"]), float(row["high"]),
                              float(row["low"]), float(row["close"]))
            except (KeyError, TypeError, ValueError):
                continue
            if not (o > 0 and h > 0 and l > 0 and c > 0):
                continue
            candle_dt = datetime.fromisoformat(ts)
            is_complete = (now_ist - candle_dt).total_seconds() >= 5 * 60
            candles.append({
                "timestamp": ts, "open": o, "high": h, "low": l,
                "close": c, "volume": int(row.get("volume") or 0),
                "is_complete": is_complete,
            })

        today_prefix = today + "T"
        today_candles = [c for c in candles if c["timestamp"].startswith(today_prefix)]
        if today_candles:
            candles = today_candles
        else:
            candles = candles[-periods:]

        candles = candles[-periods:]
        out = {"candles": candles, "source": "zerodha", "state": "LIVE",
               "mode": self.mode}
        data_ts = candles[-1]["timestamp"] if candles else None
        _cache.put(symbol, "candles", out, data_ts, "LIVE")
        return out
