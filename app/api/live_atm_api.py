"""Read-only live NIFTY ATM endpoint shared by all paper-scanner dashboards.

The dashboards used to read ``atm_strike`` from each scanner's heartbeat row.
That value can lag a strike change, and several runners deliberately replace
it with the previous index close when the market is shut.  This endpoint asks
the broker-agnostic read-only gateway for the current NIFTY 50 quote on every
(page refresh, briefly cached to coalesce polls) and derives the nearest 50
strike from it.  No broker credentials, orders or write calls are involved.
"""
from __future__ import annotations

import time
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any
from zoneinfo import ZoneInfo

from flask import Blueprint, jsonify

from broker_gateway.client import call
from broker_gateway.config import broker_for

bp = Blueprint("live_atm_api", __name__)

IST = ZoneInfo("Asia/Kolkata")
INDEX_SYMBOL = "NSE:NIFTY 50"
STRIKE_STEP = 50
CACHE_SECONDS = 10
STALE_QUOTE_SECONDS = 60

_cache: dict[str, Any] = {"at": 0.0, "value": None}


def _nearest_strike(spot: float) -> float:
    """Nearest 50 strike, half-up (financial rounding, not banker's rounding)."""
    stepped = (Decimal(str(spot)) / Decimal(STRIKE_STEP)).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )
    return float(stepped * Decimal(STRIKE_STEP))


def _fresh_value() -> dict | None:
    """Return a live quote-derived ATM value, or None when unavailable."""
    broker = broker_for("api")  # API process identity in scanners.json
    quotes = call(broker, "quote", symbols=[INDEX_SYMBOL]) or {}
    quote = quotes.get(INDEX_SYMBOL) or {}
    price = quote.get("last_price")
    if price is None:
        return None
    spot = round(float(price), 2)
    age = quote.get("age_seconds")
    stale = age is not None and float(age) > STALE_QUOTE_SECONDS
    value = {
        "spot": spot,
        "atm_strike": _nearest_strike(spot),
        "strike_step": STRIKE_STEP,
        "source": "broker_quote",
        "as_of": datetime.now(IST).isoformat(),
        "quote_age_seconds": round(float(age), 1) if age is not None else None,
        "stale": bool(stale),
    }
    _cache["at"] = time.monotonic()
    _cache["value"] = value
    return value


def _cached_value() -> dict | None:
    """Return the last good value, explicitly flagged as stale."""
    value = _cache.get("value")
    if not value:
        return None
    stale_copy = dict(value)
    stale_copy["source"] = "cached_quote"
    stale_copy["stale"] = True
    return stale_copy


@bp.route("/api/live-atm", methods=["GET"])
def live_atm():
    """Current NIFTY spot and nearest-50 ATM strike for every dashboard."""
    try:
        now = time.monotonic()
        value = _cache.get("value")
        if value and now - _cache["at"] < CACHE_SECONDS:
            return jsonify({"success": True, "data": dict(value)})
        fresh = _fresh_value()
        if fresh:
            return jsonify({"success": True, "data": fresh})
        cached = _cached_value()
        if cached:
            return jsonify({"success": True, "data": cached})
        return jsonify({"success": False, "error": "no NIFTY quote available"})
    except Exception as exc:
        cached = _cached_value()
        if cached:
            return jsonify({"success": True, "data": cached})
        return jsonify({"success": False, "error": str(exc)})
