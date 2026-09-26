"""Phase 14: Options data layer contract validation and freshness states."""
from enum import Enum


class OptionsFreshness(Enum):
    OPTIONS_FRESH = "OPTIONS_FRESH"
    OPTIONS_STALE = "OPTIONS_STALE"
    OPTIONS_NO_DATA = "OPTIONS_NO_DATA"
    OPTIONS_UNAVAILABLE = "OPTIONS_UNAVAILABLE"
    OPTIONS_RATE_LIMITED = "OPTIONS_RATE_LIMITED"
    OPTIONS_MALFORMED = "OPTIONS_MALFORMED"
    OPTIONS_PARTIAL = "OPTIONS_PARTIAL"


VALID_INSTRUMENTS = frozenset({"NIFTY", "BANKNIFTY"})
VALID_OPTION_TYPES = frozenset({"CE", "PE"})

# Freshness threshold: options data older than this is STALE
FRESHNESS_THRESHOLD_S = 300  # 5 minutes for options

# Cache TTL for options data
CACHE_TTL_S = 120  # 2 minutes


def validate_contract(record):
    """Validate a single option contract record.
    Returns (is_valid, list_of_errors)."""
    errors = []
    if not record or not isinstance(record, dict):
        return False, ["MISSING_RECORD"]

    instrument = record.get("instrument")
    if instrument not in VALID_INSTRUMENTS:
        errors.append(f"INVALID_INSTRUMENT:{instrument}")

    option_type = record.get("option_type")
    if option_type not in VALID_OPTION_TYPES:
        errors.append(f"INVALID_OPTION_TYPE:{option_type}")

    strike = record.get("strike")
    if strike is None:
        errors.append("MISSING_STRIKE")
    elif not isinstance(strike, (int, float)) or strike <= 0:
        errors.append(f"INVALID_STRIKE:{strike}")

    expiry = record.get("expiry")
    if not expiry or not isinstance(expiry, str):
        errors.append("MISSING_EXPIRY")

    timestamp = record.get("timestamp")
    if not timestamp or not isinstance(timestamp, str):
        errors.append("MISSING_TIMESTAMP")

    # Price fields: must be positive if present, never silently zeroed
    for field in ("last_price", "bid", "ask", "volume", "open_interest"):
        val = record.get(field)
        if val is not None and not isinstance(val, (int, float)):
            errors.append(f"INVALID_{field.upper()}:{val}")
        if val is not None and val < 0:
            errors.append(f"NEGATIVE_{field.upper()}:{val}")

    implied_volatility = record.get("implied_volatility")
    if implied_volatility is not None:
        if not isinstance(implied_volatility, (int, float)) or implied_volatility < 0:
            errors.append(f"INVALID_IV:{implied_volatility}")

    # Check for duplicate contract key
    if instrument and expiry and strike and option_type:
        contract_key = f"{instrument}|{expiry}|{strike}|{option_type}"
        if record.get("_contract_key") == contract_key and record.get("_dup"):
            errors.append(f"DUPLICATE_CONTRACT:{contract_key}")

    return len(errors) == 0, errors


def classify_freshness(provider_timestamp_served, now_ist_s=None):
    """Classify freshness from provider timestamp.
    Returns (OptionsFreshness, age_seconds)."""
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo
    if now_ist_s is None:
        now_ist_s = datetime.now(ZoneInfo("Asia/Kolkata")).timestamp()
    if provider_timestamp_served is None:
        return OptionsFreshness.OPTIONS_NO_DATA, None
    if isinstance(provider_timestamp_served, str):
        try:
            dt = datetime.fromisoformat(provider_timestamp_served)
            provider_timestamp_served = dt.timestamp()
        except (ValueError, TypeError):
            return OptionsFreshness.OPTIONS_MALFORMED, None
    age = now_ist_s - provider_timestamp_served
    if age < 0:
        return OptionsFreshness.OPTIONS_MALFORMED, round(abs(age), 1)
    if age < FRESHNESS_THRESHOLD_S:
        return OptionsFreshness.OPTIONS_FRESH, round(age, 1)
    return OptionsFreshness.OPTIONS_STALE, round(age, 1)


def validate_underlying_consistency(options_underlying, index_price, tolerance_pct=1.0):
    """Validate that options-chain underlying matches index market data.
    Returns (consistent, deviation_pct)."""
    if options_underlying is None or index_price is None:
        return False, None
    if index_price == 0:
        return False, None
    deviation = abs(options_underlying - index_price) / index_price * 100
    return deviation <= tolerance_pct, round(deviation, 4)
