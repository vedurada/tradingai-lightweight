"""Free live data source: yfinance (hardened Phase 11 contract).

Unchanged: provider choice (yfinance), candle OPEN timestamps in
Asia/Kolkata +05:30, quote timestamp == latest candle time, is_complete only
for fully-closed candles, no fabricated values.

Phase 11 hardening:
- Bounded fetch: ThreadPoolExecutor timeout (12s; installed yfinance 0.2.66
  exposes no per-request timeout) + exactly 1 retry, no sleep loops, no
  request storms. Final failure -> explicit UNAVAILABLE/API_ERROR/RATE_LIMITED.
- HTTP 429 (or 'rate limit' in the error) -> state RATE_LIMITED, which the
  live engine treats like NO_DATA (never a trade, distinct reason).
- Read-through shared cache (app.market.cache, SQLite): quote TTL 45s,
  candles TTL 90s. Hits return the stored payload with its ORIGINAL data_ts
  preserved; `age_seconds` for quotes is recomputed at serve time from the
  original quote timestamp so cached data can never look fresh.
- Partial: any instrument failure is isolated per-symbol (no cross
  substitution); every error path logs once via logging (no secrets).
"""
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import yfinance as yf

from app.market import cache as _cache
from app.market import flight as _flight

_IST = ZoneInfo('Asia/Kolkata')
_STALE_QUOTE_S = 3600
_FETCH_TIMEOUT_S = 12
_MAX_ATTEMPTS = 2  # 1 initial + 1 bounded retry

log = logging.getLogger('tradingai.provider')


def _quote_touch(hit):
    """Recompute age/STALE on a cached quote payload at serve time."""
    hit['age_seconds'] = round(
        (datetime.now(_IST) - datetime.fromisoformat(hit['timestamp'])).total_seconds(), 1)
    if hit['age_seconds'] >= _STALE_QUOTE_S:
        hit['state'] = 'STALE'
    return hit


def _to_ist_iso(ts):
    dt = ts.to_pydatetime() if hasattr(ts, 'to_pydatetime') else ts
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_IST).isoformat()


def _classify_error(exc):
    msg = str(exc).lower()
    if '429' in msg or 'rate limit' in msg or 'too many requests' in msg:
        return 'RATE_LIMITED'
    if isinstance(exc, FuturesTimeout) or 'timed out' in msg or 'timeout' in msg:
        return 'TIMEOUT'
    if 'name resolution' in msg or 'nodename nor servname' in msg or 'getaddrinfo' in msg:
        return 'DNS_ERROR'
    return 'API_ERROR'


def _fetch_history(symbol, period, interval):
    """history() with executor timeout + 1 bounded retry. Returns df or raises."""
    last = None
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            with ThreadPoolExecutor(max_workers=1) as ex:
                fut = ex.submit(yf.Ticker(symbol).history, period=period, interval=interval)
                return fut.result(timeout=_FETCH_TIMEOUT_S)
        except Exception as e:  # noqa - classified below
            last = e
            log.warning('provider fetch symbol=%s attempt=%d/%d err=%s',
                        symbol, attempt, _MAX_ATTEMPTS, str(e)[:160])
    raise last


class MarketDataProvider:
    def __init__(self):
        self.sources = {'yfinance': yf.Ticker}
        self.active_provider = 'yfinance'

    def get_quote(self, symbol, use_cache=True):
        if use_cache:
            hit, _ = _cache.get(symbol, 'quote')
            if hit is not None:
                return _quote_touch(hit)
        leader, ev = _flight.begin(('quote', symbol))
        try:
            if not leader:
                hit, _ = _cache.get(symbol, 'quote')
                if hit is not None:
                    return _quote_touch(hit)
                # leader failed/timed out: fetch ourselves below
            return self._fetch_quote(symbol)
        finally:
            if leader:
                _flight.end(('quote', symbol), ev)

    def _fetch_quote(self, symbol):
        # 5m + daily bars fetched CONCURRENTLY (was sequential); same data,
        # same fallbacks: daily failure -> prev_close None, price still served.
        try:
            with ThreadPoolExecutor(max_workers=2) as ex:
                f5 = ex.submit(_fetch_history, symbol, '2d', '5m')
                f1 = ex.submit(_fetch_history, symbol, '5d', '1d')
                hist = f5.result()
                try:
                    daily = f1.result()
                except Exception as e:  # noqa - change stays None
                    log.warning('quote prev_close FAILED symbol=%s err=%s',
                                symbol, str(e)[:120])
                    daily = None
        except Exception as e:
            state = _classify_error(e)
            log.warning('quote FAILED symbol=%s state=%s', symbol, state)
            return {'state': state if state != 'TIMEOUT' else 'API_ERROR',
                    'source': 'yfinance', 'symbol': symbol,
                    'error': 'timeout' if state == 'TIMEOUT' else str(e)[:200]}
        if hist.empty:
            return {'state': 'UNAVAILABLE', 'source': 'yfinance', 'symbol': symbol}
        latest = hist.iloc[-1]
        quote_ts = _to_ist_iso(hist.index[-1])
        now_ist = datetime.now(_IST)
        age_s = (now_ist - datetime.fromisoformat(quote_ts)).total_seconds()
        price = float(latest['Close'])
        if not (price > 0):
            return {'state': 'UNAVAILABLE', 'source': 'yfinance',
                    'symbol': symbol, 'timestamp': quote_ts,
                    'reason': 'NON_POSITIVE_PRICE'}
        # Day change MUST be vs previous trading-day close (daily bars),
        # never vs the previous 5-minute bar (that showed a ~5-min move
        # like +12.40 instead of the true day move like +77.40).
        prev_close = None
        if daily is not None:
            try:
                closes = [float(c) for c in daily['Close'].tolist() if c and float(c) > 0]
                if len(closes) >= 2:
                    prev_close = closes[-2]
                elif len(closes) == 1 and float(daily['Close'].iloc[-1]) != price:
                    prev_close = float(daily['Close'].iloc[-1])
            except Exception:  # noqa - change stays None, price still served
                prev_close = None
        if prev_close:
            change = float(price - prev_close)
            change_pct = float(change / prev_close * 100)
        else:
            change, change_pct = None, None
        out = {
            'symbol': symbol,
            'price': price,
            'change': change,
            'change_pct': change_pct,
            'prev_close': prev_close,
            'timestamp': quote_ts,
            'age_seconds': round(age_s, 1),
            'source': 'yfinance',
            'state': 'LIVE' if age_s < _STALE_QUOTE_S else 'STALE'
        }
        _cache.put(symbol, 'quote', out, quote_ts, out['state'])
        return out

    def get_5m_candles(self, symbol, periods=100, use_cache=True):
        if use_cache:
            hit, _ = _cache.get(symbol, 'candles')
            if hit is not None:
                return hit
        leader, ev = _flight.begin(('candles', symbol))
        try:
            if not leader:
                hit, _ = _cache.get(symbol, 'candles')
                if hit is not None:
                    return hit
                # leader failed/timed out: fetch ourselves below
            return self._fetch_candles(symbol, periods)
        finally:
            if leader:
                _flight.end(('candles', symbol), ev)

    def _fetch_candles(self, symbol, periods):
        try:
            hist = _fetch_history(symbol, '10d', '5m')
        except Exception as e:
            state = _classify_error(e)
            log.warning('candles FAILED symbol=%s state=%s', symbol, state)
            return {'state': state if state != 'TIMEOUT' else 'API_ERROR',
                    'source': 'yfinance', 'symbol': symbol,
                    'error': 'timeout' if state == 'TIMEOUT' else str(e)[:200]}
        if hist.empty:
            return {'state': 'UNAVAILABLE', 'source': 'yfinance', 'symbol': symbol}
        now_ist = datetime.now(_IST)
        candles = []
        rows = list(hist.tail(periods + 1).iterrows())
        for idx, row in rows:
            ts = _to_ist_iso(idx)
            candle_dt = datetime.fromisoformat(ts)
            is_complete = (now_ist - candle_dt).total_seconds() >= 5 * 60
            try:
                o, h, l, c = (float(row['Open']), float(row['High']),
                              float(row['Low']), float(row['Close']))
            except (TypeError, ValueError):
                continue
            if not (o > 0 and h > 0 and l > 0 and c > 0):
                continue
            candles.append({
                'timestamp': ts, 'open': o, 'high': h, 'low': l,
                'close': c, 'volume': int(row['Volume'] or 0),
                'is_complete': is_complete
            })
        candles = candles[-periods:]
        out = {'candles': candles, 'source': 'yfinance', 'state': 'LIVE'}
        data_ts = candles[-1]['timestamp'] if candles else None
        _cache.put(symbol, 'candles', out, data_ts, 'LIVE')
        return out
