"""Read-only live NIFTY ATM endpoint shared by all paper-scanner dashboards.

The dashboards used to read ``atm_strike`` and the CE/PE ``ltp`` from each
scanner's heartbeat row.  Both can lag: the strike can roll before the next
scan, and the premium is only refreshed when that scanner writes a heartbeat.
This endpoint asks the broker-agnostic read-only gateway for the current NIFTY
50 quote and for the CE/PE contracts held by the requesting scanner.

When a dashboard supplies ``?scanner=<key>``, the CE/PE instrument token and
tradingsymbol are taken from that scanner's own heartbeat row.  This matters
because mStock's weekly NIFTY symbols are not derivable from the ISO expiry
alone (2026-12-01 is ``NIFTY26D01...``, while the derived ``NIFTY26DEC...``
contract expires on 2026-12-29).  Without a scanner key, the contract is
resolved from the mStock instrument master; the legacy symbol derivation is
only a last-resort labelled fallback.  No broker credentials, orders or write
calls are involved.
"""
from __future__ import annotations

import os
import sqlite3
import time
from contextlib import closing
from datetime import datetime, time as dtime
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
MARKET_OPEN = dtime(9, 0)
MARKET_CLOSE = dtime(15, 30)
FALLBACK_MAX_DIFF = 50  # same divergence guard the live scanners use
MONTHS = (
    "JAN", "FEB", "MAR", "APR", "MAY", "JUN",
    "JUL", "AUG", "SEP", "OCT", "NOV", "DEC",
)

# Allowlisted scanner keys.  The API only reads the heartbeat belonging to the
# scanner named by the request; it never guesses or reads another scanner's DB.
SCANNER_STATES: dict[str, tuple[str, str]] = {
    "sma9": (
        os.environ.get("SMA9_DB_PATH", "/opt/tradingai/database/sma9.db"),
        "sma9_scan_state",
    ),
    "sma9-5min": (
        os.environ.get("SMA9_5MIN_DB_PATH", "/opt/tradingai/database/sma9_5min.db"),
        "sma9_5min_scan_state",
    ),
    "sma9-high": (
        os.environ.get("SMA9_HIGH_DB_PATH", "/opt/tradingai/database/sma9_high.db"),
        "sma9_high_scan_state",
    ),
    "sma9-atr": (
        os.environ.get("SMA9_ATR_DB_PATH", "/opt/tradingai/database/sma9_atr.db"),
        "sma9_atr_scan_state",
    ),
    "sma9-adx": (
        os.environ.get("SMA9_ADX_DB_PATH", "/opt/tradingai/database/sma9_adx.db"),
        "sma9_adx_scan_state",
    ),
    "sma9-trail": (
        os.environ.get("SMA9_TRAIL_DB_PATH", "/opt/tradingai/database/sma9_trail.db"),
        "sma9_trail_scan_state",
    ),
    "sma9-high-trail": (
        os.environ.get(
            "SMA9_HIGH_TRAIL_DB_PATH", "/opt/tradingai/database/sma9_high_trail.db"
        ),
        "sma9_high_trail_scan_state",
    ),
    "sma9live": (
        os.environ.get("SMA9_LIVE_DB_PATH", "/opt/tradingai/database/sma9_live.db"),
        "sma9_live_scan_state",
    ),
}

# Scanner-specific strike offsets from the live ATM strike. Only sma9_short
# uses non-ATM contracts: CE at ATM+200 and PE at ATM-200.
SCANNER_STRIKE_OFFSETS: dict[str, dict[str, float]] = {
    "sma9-short": {"CE": 200.0, "PE": -200.0},
}

# Keyed by (scanner, expiry); scanner is "" when no scanner was supplied.
_cache: dict[tuple[str, str], dict[str, Any]] = {}
_last_good: dict[tuple[str, str], dict[str, Any]] = {}

# The NFO master is stable for the session. Index it once per broker instead of
# once per (expiry, strike) pair: ATM moves every few minutes, so a per-strike
# cache caused a full master reload on almost every quote refresh.
MASTER_CONTRACT_CACHE_SECONDS = 3600
_master_index_cache: dict[str, dict] = {}


def _nearest_strike(spot: float) -> float:
    """Nearest 50 strike, half-up (financial rounding, not banker's rounding)."""
    stepped = (Decimal(str(spot)) / Decimal(STRIKE_STEP)).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )
    return float(stepped * Decimal(STRIKE_STEP))


def _option_symbol(atm: float, expiry: str, option_type: str) -> str | None:
    """Legacy NFO:NIFTY<YYMON><STRIKE><CE|PE> fallback symbol builder."""
    iso = str(expiry or "")
    if len(iso) < 10:
        return None
    try:
        yy = iso[2:4]
        month = MONTHS[int(iso[5:7]) - 1]
    except (ValueError, IndexError):
        return None
    # This cannot represent mStock weekly symbols such as NIFTY26D01...; it
    # stays only for callers that do not identify a scanner heartbeat.
    return f"{OPTION_PREFIX}{yy}{month}{int(round(float(atm)))}{option_type}"


def _age(item: dict) -> float | None:
    value = item.get("age_seconds")
    return round(float(value), 1) if value is not None else None


def _is_stale(item: dict) -> bool:
    age = item.get("age_seconds")
    return age is not None and float(age) > STALE_QUOTE_SECONDS


def _market_is_open(now: datetime) -> bool:
    local = now.astimezone(IST)
    return local.weekday() < 5 and MARKET_OPEN <= local.time() < MARKET_CLOSE


def _effective_spot(index_quote: dict, now: datetime) -> tuple[float, str, str, bool]:
    """Guard against a frozen index quote outside market hours.

    mStock has served an old ``last_price`` with a correct ``ohlc.close`` on
    closed-market days. The live scanners already fall back to the real index
    close when the two diverge by more than 50 points; use the same rule here
    so the dashboard never shows a stale ATM strike.
    """
    raw = float(index_quote["last_price"])
    ohlc = index_quote.get("ohlc") or {}
    close = ohlc.get("close")
    diverged = False
    spot = raw
    if close is not None and not _market_is_open(now):
        try:
            if abs(raw - float(close)) > FALLBACK_MAX_DIFF:
                spot = float(close)
                diverged = True
        except (TypeError, ValueError):
            pass
    source = "index_ohlc_close_fallback" if diverged else "broker_quote"
    spot_source = "index_close_fallback" if diverged else "broker_quote"
    return round(spot, 2), source, spot_source, diverged


def _scanner_state(scanner: str) -> dict:
    """Read one allowlisted scanner's heartbeat row, read-only."""
    entry = SCANNER_STATES.get(scanner)
    if not entry:
        return {}
    db_path, table = entry
    try:
        if not os.path.exists(db_path):
            return {}
        with closing(
            sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
        ) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                f"SELECT value FROM {table} WHERE key='live_status'"
            ).fetchone()
        if not row:
            return {}
        import json

        state = json.loads(row["value"])
        return state if isinstance(state, dict) else {}
    except Exception:
        return {}


def _as_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    number = _as_float(value)
    return int(number) if number is not None else None


def _instrument_index(broker: str) -> dict | None:
    """Return a strike-indexed NIFTY option master, fetched at most hourly."""
    cached = _master_index_cache.get(broker)
    if cached and time.monotonic() - cached["at"] < MASTER_CONTRACT_CACHE_SECONDS:
        return cached["index"]

    try:
        rows = call(broker, "instruments", exchange="NFO") or []
    except Exception:
        # Prefer a slightly stale index over breaking the quote endpoint.
        return cached["index"] if cached else None

    index: dict[tuple[str, float], list[dict]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("tradingsymbol") or "").strip()
        if not symbol.startswith("NIFTY"):
            continue
        opt = str(row.get("instrument_type") or "").strip().upper()
        if opt not in ("CE", "PE"):
            continue
        strike = _as_float(row.get("strike"))
        token = _as_int(row.get("instrument_token"))
        if strike is None or token is None:
            continue
        expiry = str(row.get("expiry") or "").strip()
        index.setdefault((opt, strike), []).append({
            "quote_key": str(token),
            "symbol": symbol,
            "token": token,
            "strike": strike,
            "expiry": expiry,
        })

    _master_index_cache[broker] = {"at": time.monotonic(), "index": index}
    return index


def _instrument_master_contracts(
    broker: str, expiry: str, atm: float, strikes: dict[str, float] | None = None
) -> tuple[dict[str, dict], str] | None:
    """Resolve CE/PE tokens from the cached mStock master for any strikes."""
    index = _instrument_index(broker)
    if index is None:
        return None

    targets = {
        opt: float((strikes or {}).get(opt, atm))
        for opt in ("CE", "PE")
    }
    contracts: dict[str, dict] = {}
    for opt, target in targets.items():
        candidates = index.get((opt, target)) or []
        if expiry:
            candidates = [c for c in candidates if c["expiry"] == str(expiry)]
        if not candidates:
            return None
        contract = dict(candidates[-1])
        contract["expiry"] = expiry or contract["expiry"]
        contracts[opt] = contract

    return contracts, "instrument_master"


def _heartbeat_contracts(
    scanner: str, expiry: str, atm: float, strikes: dict[str, float] | None = None
) -> tuple[dict[str, dict], str] | None:
    """Return CE/PE contracts from the requesting scanner's heartbeat.

    A heartbeat contract is used only when its strike matches the requested
    target strike (ATM, or ATM plus the scanner's offset). This prevents a
    rolled ATM from being quoted at a stale contract for offset scanners.
    """
    state = _scanner_state(scanner)
    if not state:
        return None

    heartbeat_expiry = str(state.get("expiry") or "").strip()
    if heartbeat_expiry and expiry and heartbeat_expiry != str(expiry):
        return None

    options = state.get("options") or {}
    if not isinstance(options, dict):
        return None

    contracts: dict[str, dict] = {}
    for opt in ("CE", "PE"):
        item = options.get(opt) or {}
        if not isinstance(item, dict):
            return None
        item_expiry = str(item.get("expiry") or "").strip()
        if item_expiry and expiry and item_expiry != str(expiry):
            return None

        token = _as_int(item.get("token"))
        symbol = str(item.get("tradingsymbol") or "").strip()
        if symbol.startswith("NFO:"):
            symbol = symbol[4:]
        if token is None and not symbol:
            return None

        if token is not None:
            quote_key = str(token)
        else:
            quote_key = f"{OPTION_PREFIX}{symbol}"

        strike = _as_float(item.get("strike"))
        target = (strikes or {}).get(opt)
        if target is not None and strike is not None and abs(strike - float(target)) > 0.01:
            continue
        contracts[opt] = {
            "quote_key": quote_key,
            "symbol": symbol,
            "token": token,
            "strike": strike if strike is not None else float(target or atm),
            "expiry": item_expiry or heartbeat_expiry or expiry,
        }

    if not contracts:
        return None
    source = (
        "scanner_heartbeat_token"
        if all(c["token"] is not None for c in contracts.values())
        else "scanner_heartbeat_symbol"
    )
    return contracts, source


def _derived_contracts(
    expiry: str, atm: float, strikes: dict[str, float] | None = None
) -> tuple[dict[str, dict], str]:
    """Legacy fallback used only when no better contract source is available."""
    contracts: dict[str, dict] = {}
    for opt in ("CE", "PE"):
        strike = float((strikes or {}).get(opt, atm))
        symbol = _option_symbol(strike, expiry, opt)
        if not symbol:
            continue
        contracts[opt] = {
            "quote_key": symbol,
            "symbol": symbol[4:] if symbol.startswith("NFO:") else symbol,
            "token": None,
            "strike": strike,
            "expiry": expiry or None,
        }
    return contracts, "derived_symbol"


def _fresh_value(scanner: str, expiry: str) -> dict | None:
    """Fetch a live index quote plus the CE/PE premiums for the real contracts."""
    broker = broker_for("api")  # API process identity in scanners.json
    quotes = call(broker, "quote", symbols=[INDEX_SYMBOL]) or {}
    index_quote = quotes.get(INDEX_SYMBOL) or {}
    price = index_quote.get("last_price")
    if price is None:
        return None

    now = datetime.now(IST)
    spot, source, spot_source, diverged = _effective_spot(index_quote, now)
    atm = _nearest_strike(spot)

    offsets = SCANNER_STRIKE_OFFSETS.get(scanner)
    strikes = None
    if offsets:
        strikes = {
            opt: round(atm + float(offset), 2)
            for opt, offset in offsets.items()
        }

    heartbeat = _heartbeat_contracts(scanner, expiry, atm, strikes)
    if heartbeat:
        contracts, contract_source = heartbeat
    else:
        contracts, contract_source = {}, ""

    # Use the master only to fill missing legs. A scanner heartbeat already
    # carries verified tokens for both legs during market hours, so forcing a
    # master lookup here made ATM moves trigger a full master reload.
    need_master = set(contracts) != {"CE", "PE"}
    master = (
        _instrument_master_contracts(broker, expiry, atm, strikes)
        if need_master else None
    )
    if master:
        master_contracts, master_source = master
        for opt, contract in master_contracts.items():
            if opt not in contracts:
                contracts[opt] = contract
        if not contract_source:
            contract_source = master_source
        elif strikes:
            contract_source = contract_source + "+instrument_master"

    if set(contracts) != {"CE", "PE"}:
        derived, derived_source = _derived_contracts(
            expiry, atm, strikes or {"CE": atm, "PE": atm}
        )
        for opt, contract in derived.items():
            if opt not in contracts:
                contracts[opt] = contract
        if not contract_source:
            contract_source = derived_source

    wanted = sorted({c["quote_key"] for c in contracts.values()})
    option_quotes: dict[str, dict] = {}
    if wanted:
        option_quotes = call(broker, "quote", symbols=wanted) or {}

    premiums: dict[str, Any] = {}
    for opt in ("CE", "PE"):
        contract = contracts.get(opt)
        if not contract:
            premiums[opt] = {"error": "expiry unavailable"}
            continue

        key = contract["quote_key"]
        item = option_quotes.get(key) or {}
        expected_token = contract["token"]
        actual_token = _as_int(item.get("instrument_token"))
        if (
            expected_token is not None
            and actual_token not in (None, 0)
            and actual_token != expected_token
        ):
            premiums[opt] = {
                "error": "instrument token mismatch",
                "symbol": contract["symbol"],
                "expected_token": expected_token,
                "actual_token": actual_token,
                "contract_source": contract_source,
                "stale": True,
            }
            continue

        ltp = item.get("last_price")
        bare = contract["symbol"] or key
        premiums[opt] = {
            "symbol": f"NFO:{bare}",
            "tradingsymbol": bare,
            "strike": contract["strike"],
            "expiry": contract["expiry"],
            "instrument_token": expected_token if expected_token is not None else actual_token,
            "contract_source": contract_source,
            "token_verified": expected_token is not None and actual_token == expected_token,
            "ltp": round(float(ltp), 2) if ltp is not None else None,
            "age_seconds": _age(item),
            "age_known": item.get("last_trade_time") is not None,
            "source": "broker_quote" if ltp is not None else None,
            "stale": _is_stale(item) if ltp is not None else True,
        }

    value = {
        "spot": spot,
        "atm_strike": atm,
        "strike_step": STRIKE_STEP,
        "strike_offsets": offsets or {},
        "source": source,
        "spot_source": spot_source,
        "quote_diverged": diverged,
        "as_of": now.isoformat(),
        "quote_age_seconds": _age(index_quote),
        "age_known": index_quote.get("last_trade_time") is not None,
        "freshness": "known" if index_quote.get("last_trade_time") is not None else "unknown_age",
        "stale": _is_stale(index_quote) and not diverged,
        "expiry": expiry or None,
        "scanner": scanner or None,
        "contract_source": contract_source,
        "premiums": premiums,
    }
    key = (scanner, expiry)
    _cache[key] = {"at": time.monotonic(), "value": value}
    _last_good[key] = value
    return value


def _stale_value(key: tuple[str, str]) -> dict | None:
    """Return the last good value, explicitly flagged as stale."""
    entry = _cache.get(key) or ({"value": _last_good[key]} if key in _last_good else None)
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
    """Current NIFTY spot, ATM strike and real CE/PE premiums."""
    expiry = (request.args.get("expiry") or "").strip()
    scanner = (request.args.get("scanner") or "").strip()
    key = (scanner, expiry)
    try:
        now = time.monotonic()
        entry = _cache.get(key)
        if entry and now - entry["at"] < CACHE_SECONDS:
            return jsonify({"success": True, "data": dict(entry["value"])})
        fresh = _fresh_value(scanner, expiry)
        if fresh:
            return jsonify({"success": True, "data": fresh})
        cached = _stale_value(key)
        if cached:
            return jsonify({"success": True, "data": cached})
        return jsonify({"success": False, "error": "no NIFTY quote available"})
    except Exception as exc:
        cached = _stale_value(key)
        if cached:
            return jsonify({"success": True, "data": cached})
        return jsonify({"success": False, "error": str(exc)})
