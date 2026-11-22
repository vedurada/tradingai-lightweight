"""Read-only live NIFTY ATM endpoint shared by all paper-scanner dashboards.

The dashboards used to read ``atm_strike`` and the CE/PE ``ltp`` from each
scanner's heartbeat row.  Both can lag: the strike can roll before the next
scan, and the premium is only refreshed when that scanner writes a heartbeat.
This endpoint asks the broker-agnostic read-only gateway for the current NIFTY
50 quote and for the CE/PE quotes of the resulting ATM strike, then exposes
them with explicit freshness metadata.  No broker credentials, orders or write
calls are involved.
"""
from __future__ import annotations

import time
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any
from zoneinfo import ZoneInfo

from flask import Blueprint, jsonify, request

from broker_gateway.client import call
from broker_gateway.config import broker_for

bp = Blueprint("live_atm_api", __name__)

IST = ZoneInfo("Asia/Kolkata")
INDEX_SYMBOL = "NSE:NIFTY 50"
OPTION_PREFIX = "NFO:NIFTY"
STRIKE_STEP = 50
CACHE_SECONDS = 10
STALE_QUOTE_SECONDS = 60
MONTHS = (
    "JAN", "FEB", "MAR", "APR", "MAY", "JUN",
    "JUL", "AUG", "SEP", "OCT", "NOV", "DEC",
)

# Keyed by the expiry requested by the dashboard ("" when none was supplied).
_cache: dict[str, dict[str, Any]] = {}
_last_good: dict[str, dict[str, Any]] = {}


def _nearest_strike(spot: float) -> float:
    """Nearest 50 strike, half-up (financial rounding, not banker's rounding)."""
    stepped = (Decimal(str(spot)) / Decimal(STRIKE_STEP)).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )
    return float(stepped * Decimal(STRIKE_STEP))


def _option_symbol(atm: float, expiry: str, option_type: str) -> str | None:
    """Build NFO:NIFTY<YYMON><STRIKE><CE|PE> from an ISO expiry date."""
    iso = str(expiry or "")
    if len(iso) < 10:
        return None
    try:
        yy = iso[2:4]
        month = MONTHS[int(iso[5:7]) - 1]
    except (ValueError, IndexError):
        return None
    # Keep the legacy NFO naming used by every scanner in this repo.
    return f"{OPTION_PREFIX}{yy}{month}{int(round(float(atm)))}{option_type}"


def _age(item: dict) -> float | None:
    value = item.get("age_seconds")
    return round(float(value), 1) if value is not None else None


def _is_stale(item: dict) -> bool:
    age = item.get("age_seconds")
    return age is not None and float(age) > STALE_QUOTE_SECONDS


def _fresh_value(expiry: str) -> dict | None:
    """Fetch a live index quote plus CE/PE premiums for the derived ATM."""
    broker = broker_for("api")  # API process identity in scanners.json
    quotes = call(broker, "quote", symbols=[INDEX_SYMBOL]) or {}
    index_quote = quotes.get(INDEX_SYMBOL) or {}
    price = index_quote.get("last_price")
    if price is None:
        return None

    spot = round(float(price), 2)
    atm = _nearest_strike(spot)

    premiums: dict[str, Any] = {}
    symbols = {
        opt: _option_symbol(atm, expiry, opt) for opt in ("CE", "PE")
    }
    wanted = [sym for sym in symbols.values() if sym]
    option_quotes: dict[str, dict] = {}
    if wanted:
        option_quotes = call(broker, "quote", symbols=wanted) or {}
    for opt, sym in symbols.items():
        if not sym:
            premiums[opt] = {"error": "expiry unavailable"}
            continue
        item = option_quotes.get(sym) or {}
        ltp = item.get("last_price")
        premiums[opt] = {
            "symbol": sym,
            "ltp": round(float(ltp), 2) if ltp is not None else None,
            "age_seconds": _age(item),
            "source": "broker_quote" if ltp is not None else None,
            "stale": _is_stale(item) if ltp is not None else True,
        }

    value = {
        "spot": spot,
        "atm_strike": atm,
        "strike_step": STRIKE_STEP,
        "source": "broker_quote",
        "as_of": datetime.now(IST).isoformat(),
        "quote_age_seconds": _age(index_quote),
        "stale": _is_stale(index_quote),
        "expiry": expiry or None,
        "premiums": premiums,
    }
    _cache[expiry] = {"at": time.monotonic(), "value": value}
    _last_good[expiry] = value
    return value


def _stale_value(expiry: str) -> dict | None:
    """Return the last good value, explicitly flagged as stale."""
    entry = _cache.get(expiry) or ({"value": _last_good[expiry]} if expiry in _last_good else None)
    value = (entry or {}).get("value")
    if not value:
        return None
    stale_copy = dict(value)
    stale_copy["source"] = "cached_quote"
    stale_copy["stale"] = True
    stale_copy["premiums"] = {
        opt: {**dict(prem), "stale": True}
        for opt, prem in (value.get("premiums") or {}).items()
    }
    return stale_copy


@bp.route("/api/live-atm", methods=["GET"])
def live_atm():
    """Current NIFTY spot, ATM strike and real ATM CE/PE premiums."""
    expiry = (request.args.get("expiry") or "").strip()
    try:
        now = time.monotonic()
        entry = _cache.get(expiry)
        if entry and now - entry["at"] < CACHE_SECONDS:
            return jsonify({"success": True, "data": dict(entry["value"])})
        fresh = _fresh_value(expiry)
        if fresh:
            return jsonify({"success": True, "data": fresh})
        cached = _stale_value(expiry)
        if cached:
            return jsonify({"success": True, "data": cached})
        return jsonify({"success": False, "error": "no NIFTY quote available"})
    except Exception as exc:
        cached = _stale_value(expiry)
        if cached:
            return jsonify({"success": True, "data": cached})
        return jsonify({"success": False, "error": str(exc)})
