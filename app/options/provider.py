"""Phase 14: options provider — Zerodha only (yfinance removed).

Indian options data is sourced from Zerodha Kite Connect via
scripts/options_trading_engine.py (kite client). This module no longer
attempts yfinance (which has no Indian options chain and always 404s for
^NSEI / ^NSEBANK). No options data is fabricated.
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
    """yfinance removed: Indian options are unavailable from yfinance.

    Always returns (None, OPTIONS_UNAVAILABLE) so callers fall through to
    the Zerodha options engine (scripts/options_trading_engine.py) which
    uses kiteconnect for exact premiums and strikes.
    """
    log.warning("options yfinance removed for instrument=%s; use Zerodha options engine", instrument)
    return None, OptionsFreshness.OPTIONS_UNAVAILABLE


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

    # Zerodha options are served by scripts/options_trading_engine.py via
    # kiteconnect. This provider intentionally returns UNAVAILABLE here so
    # the API layer never fabricates option chain data.
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
        result = {
            "state": "OPTIONS_UNAVAILABLE", "instrument": instrument,
            "contracts": [], "error": "NO_OPTIONS_DATA_FROM_PROVIDER",
            "underlying": None, "timestamp": None,
            "expiries": [], "data_age": None}
        cache_put(instrument, "chain", result, None, "OPTIONS_UNAVAILABLE")
        return OptionsFreshness.OPTIONS_UNAVAILABLE.value, result

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
    """Get validated option contracts with filters."""
    state, data = get_options_chain(instrument)
    contracts = data.get("contracts", [])
    if option_type and contracts:
        contracts = [c for c in contracts if c.get("option_type") == option_type]
    if expiry and contracts:
        contracts = [c for c in contracts if c.get("expiry") == expiry]
    if strike_min is not None and contracts:
        contracts = [c for c in contracts if c.get("strike", 0) >= strike_min]
    if strike_max is not None and contracts:
        contracts = [c for c in contracts if c.get("strike", 0) <= strike_max]
    return state, contracts, data
