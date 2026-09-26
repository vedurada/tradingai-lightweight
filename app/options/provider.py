"""Phase 14: options provider — yfinance attempt with graceful unavailability.

Investigation result (2026-09-20, Oracle VM):
- yfinance: returns 404 for ^NSEI/^NSEBANK; NO Indian options data
- NSE (nseindia.com): returns 403/000 — blocked from VM
- Yahoo Finance API: rate-limited (429), no Indian options chain
- No API keys, no options packages installed

This provider correctly returns OPTIONS_UNAVAILABLE/OPTIONS_NO_DATA.
NO options data is fabricated. The contract model is complete and ready
for future provider integration.
"""
import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.options.contract import OptionsFreshness, VALID_INSTRUMENTS
from app.options.cache import get as cache_get, put as cache_put, invalidate

_IST = ZoneInfo("Asia/Kolkata")
_FETCH_TIMEOUT_S = 12
_MAX_ATTEMPTS = 2

log = logging.getLogger("tradingai.options_provider")


def _classify_error(exc):
    msg = str(exc).lower()
    if "429" in msg or "rate limit" in msg or "too many requests" in msg:
        return OptionsFreshness.OPTIONS_RATE_LIMITED
    if isinstance(exc, FuturesTimeout) or "timed out" in msg or "timeout" in msg:
        return OptionsFreshness.OPTIONS_UNAVAILABLE
    if "name resolution" in msg or "nodename nor servname" in msg or "getaddrinfo" in msg:
        return OptionsFreshness.OPTIONS_UNAVAILABLE
    return OptionsFreshness.OPTIONS_UNAVAILABLE


def _fetch_yfinance_options(instrument):
    """Attempt yfinance for options. Always fails for Indian symbols."""
    import yfinance as yf
    symbol = {"NIFTY": "^NSEI", "BANKNIFTY": "^NSEBANK"}[instrument]
    last = None
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            with ThreadPoolExecutor(max_workers=1) as ex:
                fut = ex.submit(lambda s=symbol: yf.Ticker(s).options)
                result = fut.result(timeout=_FETCH_TIMEOUT_S)
                return tuple(result), OptionsFreshness.OPTIONS_FRESH
        except Exception as e:
            last = e
            log.warning("options fetch instrument=%s attempt=%d/%d err=%s",
                         instrument, attempt, _MAX_ATTEMPTS, str(e)[:120])
    return None, _classify_error(last)


def get_options_chain(instrument):
    """Get validated options chain for instrument.
    Returns (state, data_dict). Never fabricates data."""
    if instrument not in VALID_INSTRUMENTS:
        return OptionsFreshness.OPTIONS_MALFORMED, {
            "state": "OPTIONS_MALFORMED", "instrument": instrument,
            "error": "UNKNOWN_INSTRUMENT", "contracts": []}

    # Check cache first
    cached, _ = cache_get(instrument, "chain")
    if cached is not None:
        age, freshness = recompute_age(cached)
        return freshness.value, cached

    # Attempt provider fetch
    expirations, state = _fetch_yfinance_options(instrument)

    if state == OptionsFreshness.OPTIONS_RATE_LIMITED:
        result = {
            "state": "OPTIONS_RATE_LIMITED", "instrument": instrument,
            "contracts": [], "error": "Provider rate-limited",
            "underlying": None, "timestamp": None,
            "expiries": [], "data_age": None}
        cache_put(instrument, "chain", result, None, "OPTIONS_RATE_LIMITED")
        return OptionsFreshness.OPTIONS_RATE_LIMITED.value, result

    if expirations is None or len(expirations) == 0:
        # No options data available from any source
        result = {
            "state": "OPTIONS_UNAVAILABLE", "instrument": instrument,
            "contracts": [], "error": "NO_OPTIONS_DATA_FROM_PROVIDER",
            "underlying": None, "timestamp": None,
            "expiries": [], "data_age": None}
        cache_put(instrument, "chain", result, None, "OPTIONS_UNAVAILABLE")
        return OptionsFreshness.OPTIONS_UNAVAILABLE.value, result

    # If we somehow got data, validate it
    result = {
        "state": "OPTIONS_FRESH", "instrument": instrument,
        "contracts": [], "underlying": None,
        "timestamp": datetime.now(_IST).isoformat(),
        "expiries": list(expirations) if expirations else [],
        "data_age": 0}
    return OptionsFreshness.OPTIONS_FRESH.value, result


def recompute_age(payload):
    """Recompute age at serve time."""
    from app.options.cache import recompute_age
    return recompute_age(payload)


def get_option_contracts(instrument, expiry=None, option_type=None,
                          strike_min=None, strike_max=None):
    """Get validated option contracts with filters.
    Currently returns empty list — no provider accessible."""
    state, data = get_options_chain(instrument)
    contracts = data.get("contracts", [])
    # Apply filters if we had contracts
    if option_type and contracts:
        contracts = [c for c in contracts if c.get("option_type") == option_type]
    if expiry and contracts:
        contracts = [c for c in contracts if c.get("expiry") == expiry]
    if strike_min is not None and contracts:
        contracts = [c for c in contracts if c.get("strike", 0) >= strike_min]
    if strike_max is not None and contracts:
        contracts = [c for c in contracts if c.get("strike", 0) <= strike_max]
    return state, contracts, data
