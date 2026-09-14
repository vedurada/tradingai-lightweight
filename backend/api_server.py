from __future__ import annotations

import json
import os
import sys
import sqlite3
import threading
import time as _time
import uuid
import secrets
import hashlib
import hmac
import functools
from datetime import datetime, timezone
from typing import Optional

assert os.environ.get("FLASK_DEBUG", "0") != "1", "FLASK_DEBUG must not be 1"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, jsonify, request, g
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from monitoring import RequestMonitor
from logging_config import setup_logging, get_logger, log_request, log_alert
from sql_guard import assert_table_name
from auth import generate_api_key, verify_api_key, get_user_id_for_key
from data_quality import (
    DATA_QUALITY_LIVE, DATA_QUALITY_STALE,
    DATA_QUALITY_UNAVAILABLE, DATA_QUALITY_PARTIAL,
    data_age_minutes,
)
from db_pool import ConnectionPool, PooledConnection
from cache import ResponseCache

app = Flask(__name__)

ALLOWED_ORIGINS = os.environ.get(
    "TRADINGAI_CORS_ORIGINS",
    "https://tradingai.in,https://www.tradingai.in,http://localhost:3000,http://localhost:8080",
).split(",")

CORS(
    app,
    origins=ALLOWED_ORIGINS,
    methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
    supports_credentials=True,
)

app.config["MAX_CONTENT_LENGTH"] = 1 * 1024 * 1024

limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["60/minute"],
    storage_uri="memory://",
)

monitor = RequestMonitor()
logger = setup_logging(os.environ.get("TRADINGAI_LOG_LEVEL", "INFO"))

ENDPOINT_TIMEOUTS = {
    "health": 2,
    "price": 5,
    "vix": 5,
    "indicators": 5,
    "symbols": 5,
    "market": 10,
    "global": 10,
    "market_outlook": 10,
    "history": 10,
    "snapshot": 5,
    "strategy": 10,
    "regime": 5,
    "scenarios": 5,
    "outlook": 5,
    "options": 10,
    "pcr": 10,
    "max_pain": 10,
    "backtest": 60,
    "portfolio": 5,
    "alerts": 5,
    "chat": 5,
    "etf": 5,
    "fundamentals": 5,
    "data_status": 5,
    "breadth": 5,
}

import signal

TIMEOUT_HANDLER_CALLED = False


def _request_timeout_handler(signum, frame):
    global TIMEOUT_HANDLER_CALLED
    TIMEOUT_HANDLER_CALLED = True
    raise TimeoutError("Request timeout")


@app.before_request
def _set_request_timeout():
    endpoint = request.endpoint
    if endpoint and endpoint in ENDPOINT_TIMEOUTS:
        signal.signal(signal.SIGALRM, _request_timeout_handler)
        signal.alarm(ENDPOINT_TIMEOUTS[endpoint])
    g.correlation_id = f"req-{uuid.uuid4().hex[:12]}"
    g.request_start = _time.monotonic()


@app.after_request
def _record_metrics_and_clear_timeout(response):
    signal.alarm(0)
    try:
        response.headers["X-Correlation-ID"] = g.correlation_id
    except AttributeError:
        pass
    try:
        endpoint = request.endpoint
        if endpoint:
            duration_ms = (getattr(g, "request_start", _time.monotonic()) - _time.monotonic()) * 1000
            status_code = response.status_code
            error_code = None
            if status_code >= 400:
                try:
                    body = response.get_json()
                    if body and "error" in body and "code" in body["error"]:
                        error_code = body["error"]["code"]
                except Exception:
                    pass
            monitor.record_request(endpoint, duration_ms, status_code, error_code)
            log_request(
                logger, endpoint, status_code, error_code=error_code,
                latency_ms=duration_ms, correlation_id=getattr(g, "correlation_id", "unknown"),
            )
    except Exception:
        pass
    return response
    endpoint = request.endpoint
    if endpoint:
        duration_ms = (_time.monotonic() - g.request_start) * 1000
        status_code = response.status_code
        error_code = None
        if status_code >= 400:
            try:
                body = response.get_json()
                if body and "error" in body and "code" in body["error"]:
                    error_code = body["error"]["code"]
            except Exception:
                pass
        monitor.record_request(endpoint, duration_ms, status_code, error_code)
        log_request(
            logger, endpoint, status_code, error_code=error_code,
            latency_ms=duration_ms, correlation_id=g.correlation_id,
        )
    return response


@app.errorhandler(TimeoutError)
def _handle_timeout(e):
    app.logger.warning(f"Request timeout: {request.endpoint}")
    return error_response("INTERNAL_ERROR", "Request timed out", 504)


@app.errorhandler(413)
def _handle_413(e):
    return error_response("INVALID_REQUEST", "Request body too large", 413)


@app.errorhandler(429)
def _handle_429(e):
    return error_response("RATE_LIMITED", "Too many requests, please wait", 429)


@app.errorhandler(404)
def _handle_404(e):
    return error_response("NOT_FOUND", "Resource not found", 404)


@app.errorhandler(500)
def _handle_500(e):
    app.logger.error(f"Internal error: {e}")
    return error_response("INTERNAL_ERROR", "An internal error occurred", 500)


@app.errorhandler(400)
def _handle_400(e):
    return error_response("INVALID_REQUEST", "Invalid request", 400)


@app.errorhandler(sqlite3.OperationalError)
def _handle_db_error(e):
    app.logger.error(f"DB error: {e}")
    return error_response("SERVICE_DEGRADED", "Database temporarily unavailable — please retry shortly", 503)


_shutdown_in_progress = False
_startup_checked = False


def _ensure_startup():
    global _startup_checked
    if _startup_checked:
        return
    _startup_checked = True
    try:
        conn = get_db()
        conn.execute("SELECT 1").fetchone()
        conn.close()
    except Exception as e:
        app.logger.error(f"Startup check failed: {e}")
        raise


@app.before_request
def _startup_guard():
    _ensure_startup()


@app.before_request
def _check_auth():
    if request.endpoint in ("portfolio_list", "portfolio_add", "portfolio_delete"):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return error_response("UNAUTHORIZED", "Authentication required", 401)
        api_key = auth_header[7:]
        user_id = get_user_id_for_key(api_key)
        if user_id is None:
            return error_response("UNAUTHORIZED", "Authentication required", 401)
        g.user_id = user_id


signal.signal(signal.SIGTERM, lambda signum, frame: globals().__setitem__("_shutdown_in_progress", True) or app.logger.info("SIGTERM received — graceful shutdown started"))


@app.route("/api/metrics")
@limiter.exempt
def metrics():
    summary = monitor.get_summary()
    alerts = monitor.check_alerts()
    return jsonify({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "uptime_seconds": monitor.get_uptime_seconds(),
        "request_counts": summary["counts"],
        "latency": summary["endpoints"],
        "circuit_breakers": summary["circuit_breakers"],
        "external_api_failures": summary["external_api_failures"],
        "alerts": alerts,
        "process_local": True,
        "note": "Metrics are process-local. Multiple workers/instances maintain separate counters.",
    })


DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "database", "tradingai.db")

db_pool = ConnectionPool(lambda: DB_PATH, max_connections=10)
response_cache = ResponseCache()
_pool_db_path = DB_PATH
_pool_lock = threading.Lock()

def get_db():
    global db_pool, _pool_db_path
    current_path = DB_PATH
    with _pool_lock:
        if _pool_db_path != current_path:
            db_pool.close_all()
            db_pool = ConnectionPool(lambda: DB_PATH, max_connections=10)
            _pool_db_path = current_path
    return PooledConnection(db_pool.get(), db_pool)

def row_to_dict(row):
    if row is None:
        return None
    return dict(row)


def _check_source_freshness(source, threshold=30):
    conn = get_db()
    try:
        table_map = {
            "nifty_price": "price_1m",
            "vix": "vix_data",
            "outlook": "market_outlooks",
            "price_1m": "price_1m",
            "vix_data": "vix_data",
            "market_outlooks": "market_outlooks",
        }
        table = table_map.get(source, source)
        row = conn.execute(f"SELECT MAX(timestamp) as ts FROM {table}").fetchone()
        if not row or not row["ts"]:
            return {"status": "unavailable", "age_minutes": None}
        age = data_age_minutes(row["ts"])
        if age is None:
            return {"status": "unavailable", "age_minutes": None}
        if age > threshold:
            return {"status": "stale", "age_minutes": round(age), "threshold": threshold}
        return {"status": "ok", "age_minutes": round(age)}
    except Exception:
        return {"status": "unavailable", "age_minutes": None}
    finally:
        conn.close()


def _record_fetch_result(source, success, error_msg=None):
    conn = get_db()
    try:
        if success:
            conn.execute(
                "UPDATE data_status SET success_count = success_count + 1, consecutive_failures = 0 WHERE source = ?",
                (source,),
            )
        else:
            conn.execute(
                "UPDATE data_status SET error_count = error_count + 1, consecutive_failures = consecutive_failures + 1, last_error = ? WHERE source = ?",
                (error_msg, source),
            )
        conn.commit()
    except Exception:
        conn.rollback()
    finally:
        conn.close()


def _enrich_with_freshness(response, source_tables):
    if not isinstance(response, dict):
        return response
    ages = []
    for table in source_tables:
        conn = get_db()
        try:
            row = conn.execute(f"SELECT MAX(timestamp) as ts FROM {table}").fetchone()
            if row and row["ts"]:
                age = data_age_minutes(row["ts"])
                if age is not None:
                    ages.append(age)
        except Exception:
            pass
        finally:
            conn.close()
    if not ages:
        response["data_quality"] = DATA_QUALITY_UNAVAILABLE
        response["data_freshness"] = {"age_minutes": None, "stale": True}
    elif max(ages) > 30:
        response["data_quality"] = DATA_QUALITY_STALE
        response["data_freshness"] = {"age_minutes": round(max(ages)), "stale": True, "threshold_minutes": 30}
    else:
        response["data_quality"] = DATA_QUALITY_LIVE
        response["data_freshness"] = {"age_minutes": round(max(ages)) if ages else None, "stale": False}
    return response

def _paginate_list(conn, select_sql, select_params, total_sql, total_params, page, page_size):
    offset = (page - 1) * page_size
    rows = conn.execute(select_sql, (*select_params, page_size, offset)).fetchall()
    total_row = conn.execute(total_sql, total_params).fetchone()
    total = total_row[0] if total_row else 0
    return rows, total


def _page_params():
    page = request.args.get("page", 1, type=int)
    page_size = request.args.get("page_size", 50, type=int)
    page_size = min(page_size, 500)
    page = max(page, 1)
    return page, page_size


def _paginated_response(rows, total, page, page_size):
    return jsonify({
        "data": [row_to_dict(r) for r in rows],
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": (total + page_size - 1) // page_size if page_size > 0 else 0,
        },
    })


def serialize_val(v):
    if isinstance(v, float):
        return round(v, 4)
    return v

def cache_page(ttl):
    def decorator(f):
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            key_parts = [f.__name__, str(args), str(sorted(kwargs.items()))]
            if request.args:
                key_parts.append(str(sorted(request.args.items(multi=True))))
            key = "|".join(key_parts)
            cached = response_cache.get(key)
            if cached is not None:
                return jsonify(cached)
            result = f(*args, **kwargs)
            if isinstance(result, tuple) and len(result) == 2:
                resp, status = result
                if status == 200 and hasattr(resp, "get_json"):
                    data = resp.get_json()
                    if data is not None and "error" not in data:
                        response_cache.set(key, data, ttl)
                return resp, status
            if hasattr(result, "get_json"):
                data = result.get_json()
                if data is not None and "error" not in data:
                    response_cache.set(key, data, ttl)
            return result
        return wrapper
    return decorator


@app.route("/api/health")
@limiter.exempt
def health():
    pool_status = db_pool.status
    sources = {
        "nifty_price": _check_source_freshness("nifty_price", threshold=30),
        "vix": _check_source_freshness("vix", threshold=60),
        "outlook": _check_source_freshness("outlook", threshold=1440),
    }
    any_stale = any(s["status"] == "stale" for s in sources.values())
    all_stale = all(s["status"] != "ok" for s in sources.values())
    overall = "ok" if not any_stale else "degraded"
    if pool_status["exhausted"]:
        overall = "degraded"
    warnings = []
    for name, info in sources.items():
        if info["status"] == "stale":
            warnings.append(f"{name} data {info['age_minutes']}m stale")
        elif info["status"] == "unavailable":
            warnings.append(f"{name} data unavailable")
    if pool_status["exhausted"]:
        warnings.append("connection pool exhausted")
    freshness = {}
    for name, info in sources.items():
        if info["age_minutes"] is not None:
            freshness[f"{name}_minutes_ago"] = info["age_minutes"]
    return jsonify({
        "status": overall,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "warnings": warnings,
        "data_freshness": freshness,
        "sources": sources,
        "overall": overall,
        "pool": pool_status,
    })

@app.route("/api/symbols")
@cache_page(86400)
def symbols():
    page, page_size = _page_params()
    conn = get_db()
    rows, total = _paginate_list(
        conn,
        "SELECT * FROM symbols WHERE active=1 ORDER BY type, symbol LIMIT ? OFFSET ?",
        (),
        "SELECT COUNT(*) FROM symbols WHERE active=1",
        (),
        page, page_size,
    )
    conn.close()
    return _paginated_response(rows, total, page, page_size)

@app.route("/api/price/<symbol>")
@cache_page(5)
def latest_price(symbol):
    """Single genuine price: same source as /api/<symbol> quote (live_quotes -> price_1m -> price_1d)."""
    s = (symbol or "").upper()
    conn = get_db()
    price_row = conn.execute("SELECT * FROM price_1m WHERE symbol=? ORDER BY timestamp DESC LIMIT 1", (s,)).fetchone()
    live_row = _live_quote_row(conn, s)
    # fallback to price_1d if both empty (weekend / stale)
    if not price_row and not live_row:
        price_row = conn.execute("SELECT * FROM price_1d WHERE symbol=? ORDER BY timestamp DESC LIMIT 1", (s,)).fetchone()
        if price_row:
            # map price_1d row shape to price_row dict with close
            conn.close()
            d = row_to_dict(price_row)
            # expose as quote for consistency
            pq = _build_quote(s, price_row, None)
            if isinstance(pq, dict):
                _pr_ts = dict(price_row).get("timestamp") if price_row else None
                age = data_age_minutes(_pr_ts)
                if age is None or age > 30:
                    pq["data_quality"] = DATA_QUALITY_UNAVAILABLE if age is None else DATA_QUALITY_STALE
                    pq["data_freshness"] = {"age_minutes": None if age is None else round(age), "stale": True}
                else:
                    pq["data_quality"] = DATA_QUALITY_LIVE
                    pq["data_freshness"] = {"age_minutes": round(age), "stale": False}
            return jsonify(pq or d)
    quote = _build_quote(s, price_row, live_row)
    conn.close()
    if quote:
        if isinstance(quote, dict):
            _pr_ts = dict(price_row).get("timestamp") if price_row else None
            _lr_ts = dict(live_row).get("timestamp") if live_row else None
            age = data_age_minutes(_pr_ts) or data_age_minutes(_lr_ts)
            if age is None or age > 30:
                quote["data_quality"] = DATA_QUALITY_UNAVAILABLE if age is None else DATA_QUALITY_STALE
                quote["data_freshness"] = {"age_minutes": None if age is None else round(age), "stale": True}
            else:
                quote["data_quality"] = DATA_QUALITY_LIVE
                quote["data_freshness"] = {"age_minutes": round(age), "stale": False}
        return jsonify(quote)
    return jsonify({"error": "no data", "data_quality": DATA_QUALITY_UNAVAILABLE}), 404

@app.route("/api/prices/<symbol>")
@cache_page(5)
def prices(symbol):
    limit = request.args.get("limit", 100, type=int)
    interval = request.args.get("interval", "1m")
    table = f"price_{interval}" if interval in ("1m", "5m", "15m", "1d") else "price_1m"
    assert_table_name(table)
    conn = get_db()
    rows = conn.execute(f"SELECT * FROM {table} WHERE symbol=? ORDER BY timestamp DESC LIMIT ?", (symbol, limit)).fetchall()
    # keep history as candles, but last_updated/quote remains single-source via /api/price and /api/<symbol>
    conn.close()
    return jsonify([row_to_dict(r) for r in reversed(rows)])

@app.route("/api/prices")
@cache_page(5)
def all_prices():
    page, page_size = _page_params()
    limit = request.args.get("limit", page_size, type=int)
    limit = min(limit, page_size)
    symbols_param = request.args.get("symbols", "")
    conn = get_db()
    if symbols_param:
        syms = symbols_param.split(",")
        placeholders = ",".join("?" for _ in syms)
        assert_table_name("price_1m")
        rows, total = _paginate_list(
            conn,
            f"SELECT * FROM price_1m WHERE symbol IN ({placeholders}) ORDER BY timestamp DESC LIMIT ? OFFSET ?",
            (*syms,),
            "SELECT COUNT(*) FROM price_1m WHERE symbol IN ({})".format(placeholders),
            (*syms,),
            limit, (page - 1) * limit,
        )
    else:
        rows, total = _paginate_list(
            conn,
            "SELECT * FROM price_1m ORDER BY timestamp DESC LIMIT ? OFFSET ?",
            (),
            "SELECT COUNT(*) FROM price_1m",
            (),
            limit, (page - 1) * limit,
        )
    conn.close()
    return _paginated_response(rows, total, page, limit)

@app.route("/api/vix")
@cache_page(5)
def vix():
    conn = get_db()
    row = conn.execute("SELECT * FROM vix_data ORDER BY timestamp DESC LIMIT 1").fetchone()
    conn.close()
    if row:
        d = row_to_dict(row)
        d["price"] = d.get("close", 0)
        age = data_age_minutes(d.get("timestamp"))
        if age is None:
            pass
        elif age > 60:
            d["data_quality"] = DATA_QUALITY_STALE
            d["data_freshness"] = {"age_minutes": round(age), "stale": True, "threshold_minutes": 60}
        else:
            d["data_quality"] = DATA_QUALITY_LIVE
            d["data_freshness"] = {"age_minutes": round(age), "stale": False}
        return jsonify(d)
    return jsonify({"error": "no VIX data", "data_quality": DATA_QUALITY_UNAVAILABLE}), 404

@app.route("/api/vix/history")
@cache_page(5)
def vix_history():
    page, page_size = _page_params()
    limit = request.args.get("limit", page_size, type=int)
    limit = min(limit, page_size)
    conn = get_db()
    rows, total = _paginate_list(
        conn,
        "SELECT * FROM vix_data ORDER BY timestamp DESC LIMIT ? OFFSET ?",
        (),
        "SELECT COUNT(*) FROM vix_data",
        (),
        limit, (page - 1) * limit,
    )
    conn.close()
    return _paginated_response(list(reversed(rows)), total, page, limit)

@app.route("/api/vix/daily")
@cache_page(5)
def vix_daily():
    days = request.args.get("days", 60, type=int)
    conn = get_db()
    rows = conn.execute("SELECT DATE(timestamp) as d, close, change, change_pct FROM vix_data WHERE timestamp >= date('now', '-' || ? || ' days') ORDER BY d", (days,)).fetchall()
    conn.close()
    # Keep last entry per date
    seen = {}
    for r in rows:
        seen[r['d']] = {'date': r['d'], 'close': r['close'], 'change': r['change'], 'change_pct': r['change_pct']}
    return jsonify(list(seen.values()))

@app.route("/api/indicators/<symbol>")
@cache_page(5)
def indicators(symbol):
    conn = get_db()
    row = conn.execute("SELECT * FROM indicators WHERE symbol=? ORDER BY timestamp DESC LIMIT 1", (symbol,)).fetchone()
    conn.close()
    if row:
        return jsonify(row_to_dict(row))
    return jsonify({"error": "no indicators"}), 404

@app.route("/api/indicators")
@cache_page(5)
def indicators_default():
    symbol = request.args.get("symbol", "NIFTY")
    conn = get_db()
    row = conn.execute("SELECT * FROM indicators WHERE symbol=? ORDER BY timestamp DESC LIMIT 1", (symbol,)).fetchone()
    conn.close()
    if row:
        d = row_to_dict(row)
        age = data_age_minutes(row.get("timestamp"))
        if age is None:
            d["data_quality"] = DATA_QUALITY_UNAVAILABLE
            d["data_freshness"] = {"age_minutes": None, "stale": True}
        elif age > 60:
            d["data_quality"] = DATA_QUALITY_STALE
            d["data_freshness"] = {"age_minutes": round(age), "stale": True, "threshold_minutes": 60}
        else:
            d["data_quality"] = DATA_QUALITY_LIVE
            d["data_freshness"] = {"age_minutes": round(age), "stale": False}
        return jsonify(d)
    return jsonify({"error": "no indicators", "data_quality": DATA_QUALITY_UNAVAILABLE}), 404

@app.route("/api/nifty")
def nifty():
    return _symbol_data("NIFTY")

@app.route("/api/banknifty")
def banknifty():
    return _symbol_data("BANKNIFTY")

@app.route("/api/sensex")
def sensex():
    return _symbol_data("SENSEX")

@app.route("/api/finnifty")
def finnifty():
    return _symbol_data("FINNIFTY")

@app.route("/api/<symbol>")
def symbol_generic(symbol):
    s = (symbol or "").upper()
    if s in ("MARKET", "HEALTH", "HISTORY", "VIX", "SNAPSHOT", "SNAPSHOTS", "BREADTH", "SYMBOLS", "STRATEGIES", "OUTLOOKS", "REGIMES", "PRICES", "ETF", "NEWS"):
        return jsonify({"error": "use dedicated endpoint"}), 404
    conn = get_db()
    row = conn.execute("SELECT symbol FROM symbols WHERE UPPER(symbol)=? LIMIT 1", (s,)).fetchone()
    conn.close()
    if not row:
        return jsonify({"error": f"unknown symbol {symbol}"}), 404
    return _symbol_data(s)

def _parse_json_field(value, default=None):
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return default


def _to_ist_iso(ts):
    """Normalize DB timestamps to ISO with offset.

    price_1m candles are stored naive ('YYYY-MM-DD HH:MM:SS') in UTC wall-clock
    (both yfinance candles and the NSE synthetic fallback write datetime.now(utc));
    other tables store UTC ISO. Returns ISO-8601 with offset, or None.
    """
    if not ts:
        return None
    s = str(ts).strip()
    try:
        if "T" in s:
            if s.endswith("Z"):
                return s
            if "+" in s[10:] or s[10:].count("-") > 2:
                return s
            return s + "+00:00"
        # Naive 'YYYY-MM-DD HH:MM:SS' -> UTC (all writers store UTC wall-clock).
        return s.replace(" ", "T") + "+00:00"
    except Exception:
        return None


LIVE_QUOTE_MAX_AGE_MIN = 25


def _live_quote_row(conn, symbol):
    """Fresh NSE live quote if present, else None (caller falls back to candles)."""
    try:
        row = conn.execute("SELECT * FROM live_quotes WHERE symbol=?", (symbol,)).fetchone()
    except Exception:
        return None
    if not row:
        return None
    d = row_to_dict(row)
    try:
        ts = datetime.fromisoformat(str(d.get("timestamp", "")).replace("Z", "+00:00"))
        age_min = (datetime.now(timezone.utc) - ts).total_seconds() / 60
        if age_min > LIVE_QUOTE_MAX_AGE_MIN:
            return None
    except Exception:
        pass
    return d


def _build_quote(symbol, price_row, live_row=None, conn=None):
    """Quote with fallback chain: live NSE row -> 1m candle row. Never empty if either exists."""
    d = dict(live_row) if live_row else (row_to_dict(price_row) if price_row else None)
    if not d:
        return None
    source = (live_row or {}).get("source", "NSE") if live_row else "yfinance"
    if live_row:
        price = d.get("price", 0) or 0
        prev = d.get("previous_close", 0) or 0
        change = d.get("change", (price - prev) if prev else 0) or 0
        return {
            "symbol": symbol, "price": price, "change": round(change, 2),
            "change_pct": round(d.get("change_pct", (change / prev * 100 if prev else 0)) or 0, 2),
            "open": d.get("open", 0), "high": d.get("high", 0), "low": d.get("low", 0),
            "previous_close": prev, "volume": d.get("volume", 0),
            "timestamp": _to_ist_iso(d.get("timestamp")), "stale": not price,
            "source": source,
        }
    d = row_to_dict(price_row)
    close = d.get("close", 0) or 0
    prev = d.get("previous_close", 0) or 0
    if not prev and conn is not None:
        try:
            prow = conn.execute("SELECT close FROM price_1d WHERE symbol=? ORDER BY timestamp DESC LIMIT 2", (symbol,)).fetchall()
            if len(prow) == 2:
                prev = prow[1]["close"] or 0
            elif len(prow) == 1 and prow[0]["close"] != close:
                prev = prow[0]["close"] or 0
            if not prev:
                prow2 = conn.execute("SELECT close FROM price_1m WHERE symbol=? ORDER BY timestamp DESC LIMIT 2", (symbol,)).fetchall()
                if len(prow2) > 1:
                    prev = prow2[1]["close"] or 0
        except Exception:
            pass
    change = (close - prev) if prev else 0
    return {
        "symbol": symbol, "price": close, "change": round(change, 2),
        "change_pct": round(change / prev * 100, 2) if prev else 0,
        "open": d.get("open", 0), "high": d.get("high", 0), "low": d.get("low", 0),
        "previous_close": prev, "volume": d.get("volume", 0),
        "timestamp": _to_ist_iso(d.get("timestamp")), "stale": False,
        "source": source,
    }


def _build_indicators(ind_row):
    if not ind_row:
        return None
    d = row_to_dict(ind_row)
    sr = _parse_json_field(d.get("support_resistance"), {}) or {}
    if isinstance(sr, str):
        sr = {}
    d["support_resistance"] = {"support": sr.get("support", []), "resistance": sr.get("resistance", [])} if isinstance(sr, dict) else {"support": [], "resistance": []}
    return d


def _build_strategy(strat_row):
    """DB single row -> legacy {strategies: [...]} shape (options for indexes, BUY/HOLD/EXIT for stocks)."""
    if not strat_row:
        return None
    d = row_to_dict(strat_row)
    legs_parsed = _parse_json_field(d.get("legs"), None)
    if isinstance(legs_parsed, dict) and "all_strategies" in legs_parsed:
        strategies = legs_parsed.get("all_strategies", []) or []
        legs = legs_parsed.get("legs", [])
        if strategies:
            strategies[0]["legs"] = strategies[0].get("legs", legs)
            return {"strategies": strategies, "timestamp": d.get("timestamp")}
    single = {k: d.get(k) for k in ("strategy", "market_condition", "expiry", "entry_trigger", "maximum_profit", "maximum_loss", "breakeven", "stop_loss", "target", "adjustment", "exit", "strategy_environment", "invalidation", "position_size")}
    single["legs"] = legs_parsed if isinstance(legs_parsed, list) else []
    return {"strategies": [single], "timestamp": d.get("timestamp")}


def _ist_today():
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%Y-%m-%d")
    except Exception:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _locked_strategy(conn, symbol):
    """Today's 9:30 AM locked strategy (indexes), if the lock cron has run."""
    try:
        row = conn.execute("SELECT * FROM daily_strategy WHERE symbol=? AND date=?", (symbol, _ist_today())).fetchone()
    except Exception:
        return None
    if not row:
        return None
    d = row_to_dict(row)
    try:
        strategies = json.loads(d.get("strategy_json") or "[]")
    except Exception:
        strategies = []
    if not strategies:
        return None
    return {"strategies": strategies, "locked": True, "locked_at": d.get("locked_at", "09:30"),
            "regime": d.get("regime", ""), "timestamp": d.get("created_at")}


def _live_expiry(conn, symbol):
    """Nearest real NSE expiry per index from option_expiries (None if none stored).

    Classifies MONTHLY vs WEEKLY: an expiry on the last exchange-weekday of its
    month is the monthly contract, otherwise a weekly. NSE=Tuesday, BSE=Thursday.
    """
    from datetime import date as _date, timedelta as _td
    try:
        today = _ist_today()
    except Exception:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        rows = conn.execute("SELECT expiry FROM option_expiries WHERE symbol=? AND expiry>=? ORDER BY expiry", (symbol, today)).fetchall()
    except Exception:
        return None
    dates = []
    for r in rows:
        try:
            dates.append(_date.fromisoformat(str(r["expiry"])[:10]))
        except Exception:
            continue
    if not dates:
        return None
    weekday = 3 if symbol == "SENSEX" else 1
    day_label = "Thursday" if symbol == "SENSEX" else "Tuesday"
    exchange = "BSE" if symbol == "SENSEX" else "NSE"

    def is_monthly(d):
        m = d.month + 1
        y = d.year + (1 if m > 12 else 0)
        m = 1 if m > 12 else m
        last = _date(y, m, 1) - _td(days=1)
        while last.weekday() != weekday:
            last -= _td(days=1)
        return d == last

    def payload(d, tenor):
        return {"expiry_date": d.isoformat(), "expiry_label": d.strftime("%d %b %Y"),
                "expiry_weekday": day_label, "days_to_expiry": (d - _date.fromisoformat(today)).days,
                "tenor": tenor, "expiry_day": day_label, "source": "NSE",
                "timestamp": datetime.now(timezone.utc).isoformat()}

    monthlies = [d for d in dates if is_monthly(d)]
    weekly = next((d for d in dates if d not in monthlies), None)
    if symbol in ("BANKNIFTY", "FINNIFTY"):
        weekly = None  # monthly-only contracts
    first = weekly or (monthlies[0] if monthlies else None)
    if not first:
        return None
    out = payload(first, "WEEKLY" if weekly and first == weekly else "MONTHLY")
    out.update({"symbol": symbol, "exchange": exchange,
                "weekly": payload(weekly, "WEEKLY") if weekly else None,
                "monthly": payload(monthlies[0], "MONTHLY") if monthlies else None})
    return out


def _build_scenarios(scen_row):
    """DB flattened row -> legacy list [{scenario_type, description, target, stop_loss, trigger}]."""
    if not scen_row:
        return []
    d = row_to_dict(scen_row)
    out = []
    if d.get("bullish_trigger") or d.get("bullish_target"):
        out.append({"scenario_type": "BULLISH", "description": d.get("bullish_confirmation", ""), "trigger": d.get("bullish_trigger", ""), "target": d.get("bullish_target", ""), "stop_loss": d.get("bullish_invalidation", "")})
    if d.get("bearish_trigger") or d.get("bearish_target"):
        out.append({"scenario_type": "BEARISH", "description": d.get("bearish_confirmation", ""), "trigger": d.get("bearish_trigger", ""), "target": d.get("bearish_target", ""), "stop_loss": d.get("bearish_invalidation", "")})
    if d.get("range_condition"):
        out.append({"scenario_type": "RANGE", "description": d.get("range_strategy", ""), "trigger": d.get("range_condition", ""), "target": d.get("range_strategy", ""), "stop_loss": d.get("range_invalidation", "")})
    return out


def _build_outlook(outlook_row):
    if not outlook_row:
        return None
    d = row_to_dict(outlook_row)
    full = _parse_json_field(d.get("outlook"), None)
    if isinstance(full, dict) and full:
        return full
    return {"market_summary": d.get("outlook", ""), "data_quality": d.get("data_quality", "")}


def _data_completeness(**fields):
    return {k: bool(v) for k, v in fields.items()}


def _execute_write(conn, query, params=None, max_retries=3):
    for attempt in range(max_retries):
        try:
            conn.execute("BEGIN IMMEDIATE")
            if params:
                conn.execute(query, params)
            else:
                conn.execute(query)
            conn.commit()
            return True
        except sqlite3.OperationalError as e:
            conn.rollback()
            if "database is locked" in str(e) and attempt < max_retries - 1:
                _time.sleep(0.1 * (attempt + 1))
                continue
            raise


def error_response(code, message, status_code=400):
    return jsonify({
        "error": {
            "code": code,
            "message": message,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    }), status_code


ERROR_CODES = {
    "NO_DATA": "The requested data is not available",
    "UNKNOWN_SYMBOL": "The requested symbol is not tracked",
    "SYMBOL_REQUIRED": "A symbol parameter is required",
    "OUTLOOK_NOT_READY": "Market outlook not yet computed for this date",
    "INVALID_REQUEST": "The request parameters are invalid",
    "RATE_LIMITED": "Too many requests, please wait",
    "INTERNAL_ERROR": "An internal error occurred",
    "DB_UNAVAILABLE": "Database is temporarily unavailable",
    "CIRCUIT_OPEN": "An upstream data source is temporarily unavailable",
}


@app.errorhandler(404)
def _handle_404(e):
    return error_response("NO_DATA", "The requested resource was not found", 404)


@app.errorhandler(500)
def _handle_500(e):
    app.logger.error(f"Unhandled 500: {e}")
    return error_response("INTERNAL_ERROR", "An internal error occurred", 500)


@app.errorhandler(400)
def _handle_400(e):
    return error_response("INVALID_REQUEST", str(e) or "Invalid request", 400)


def _symbol_data(symbol):
    symbol = (symbol or "").upper()
    conn = get_db()
    try:
        result = {}
        price_row = conn.execute("SELECT * FROM price_1m WHERE symbol=? ORDER BY timestamp DESC LIMIT 1", (symbol,)).fetchone()
        quote = _build_quote(symbol, price_row, _live_quote_row(conn, symbol), conn=conn)
        if quote:
            result["quote"] = quote
        ind_row = conn.execute("SELECT * FROM indicators WHERE symbol=? ORDER BY timestamp DESC LIMIT 1", (symbol,)).fetchone()
        ind = _build_indicators(ind_row)
        if ind:
            result["indicators"] = ind
        regime_row = conn.execute("SELECT * FROM market_regime WHERE symbol=? ORDER BY timestamp DESC LIMIT 1", (symbol,)).fetchone()
        if regime_row:
            result["regime"] = row_to_dict(regime_row)
        strat = _locked_strategy(conn, symbol)
        if not strat:
            strat_row = conn.execute("SELECT * FROM strategies WHERE symbol=? ORDER BY timestamp DESC LIMIT 1", (symbol,)).fetchone()
            strat = _build_strategy(strat_row)
        if strat:
            result["strategy"] = strat
        scen_row = conn.execute("SELECT * FROM scenarios WHERE symbol=? ORDER BY timestamp DESC LIMIT 1", (symbol,)).fetchone()
        result["scenarios"] = _build_scenarios(scen_row)
        outlook_row = conn.execute("SELECT * FROM ai_outlooks WHERE symbol=? ORDER BY timestamp DESC LIMIT 1", (symbol,)).fetchone()
        outlook = _build_outlook(outlook_row)
        if outlook:
            result["ai_outlook"] = outlook
        try:
            stype = conn.execute("SELECT type FROM symbols WHERE symbol=?", (symbol,)).fetchone()
            if stype and stype["type"] == "stock":
                inv = {}
                for r in conn.execute("SELECT * FROM investment_views WHERE symbol=? ORDER BY date DESC, horizon", (symbol,)).fetchall():
                    d = row_to_dict(r)
                    if d.get("horizon") not in inv:
                        inv[d.get("horizon")] = d
                if inv:
                    result["investment"] = inv
        except Exception:
            pass
        try:
            srow = conn.execute("SELECT lot_size, lot_source, lot_as_of FROM symbols WHERE symbol=?", (symbol,)).fetchone()
            if srow and srow["lot_size"]:
                result["lot"] = {"size": srow["lot_size"], "source": srow["lot_source"] or "config", "as_of": srow["lot_as_of"]}
        except Exception:
            pass
        try:
            exp = _live_expiry(conn, symbol)
            if not exp:
                from expiry import get_current_expiry
                if symbol in ("NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX"):
                    exp = get_current_expiry(symbol) if callable(get_current_expiry) else {}
            if exp:
                result["expiry"] = exp
        except Exception:
            pass
        quote_ts = (result.get("quote") or {}).get("timestamp")
        result["last_updated"] = quote_ts
        result["computed_at"] = datetime.now(timezone.utc).isoformat()
        result["data_quality"] = (result.get("ai_outlook") or {}).get("data_quality", "GOOD")
        result["data_completeness"] = _data_completeness(
            quote=bool(result.get("quote")),
            indicators=bool(result.get("indicators")),
            regime=bool(result.get("regime")),
            strategy=bool(result.get("strategy")),
            scenarios=bool(result.get("scenarios")),
            outlook=bool(result.get("ai_outlook")),
        )
        return jsonify(result)
    finally:
        conn.close()

@app.route("/api/regime/<symbol>")
@cache_page(3600)
def regime(symbol):
    conn = get_db()
    row = conn.execute("SELECT * FROM market_regime WHERE symbol=? ORDER BY timestamp DESC LIMIT 1", (symbol,)).fetchone()
    conn.close()
    if row:
        return jsonify(row_to_dict(row))
    return jsonify({"error": "no regime"}), 404

@app.route("/api/regimes")
@cache_page(3600)
def all_regimes():
    page, page_size = _page_params()
    conn = get_db()
    rows, total = _paginate_list(
        conn,
        "SELECT * FROM market_regime ORDER BY timestamp DESC LIMIT ? OFFSET ?",
        (),
        "SELECT COUNT(*) FROM market_regime",
        (),
        page, page_size,
    )
    conn.close()
    return _paginated_response(rows, total, page, page_size)

@app.route("/api/strategy/<symbol>")
@cache_page(3600)
def strategy(symbol):
    conn = get_db()
    row = conn.execute("SELECT * FROM strategies WHERE symbol=? ORDER BY timestamp DESC LIMIT 1", (symbol,)).fetchone()
    conn.close()
    if row:
        return jsonify(row_to_dict(row))
    return jsonify({"error": "no strategy"}), 404

@app.route("/api/strategies")
@cache_page(3600)
def all_strategies():
    page, page_size = _page_params()
    conn = get_db()
    rows, total = _paginate_list(
        conn,
        "SELECT * FROM strategies ORDER BY timestamp DESC LIMIT ? OFFSET ?",
        (),
        "SELECT COUNT(*) FROM strategies",
        (),
        page, page_size,
    )
    conn.close()
    return _paginated_response(rows, total, page, page_size)

@app.route("/api/scenarios/<symbol>")
@cache_page(3600)
def scenarios(symbol):
    conn = get_db()
    page, page_size = _page_params()
    rows, total = _paginate_list(
        conn,
        "SELECT * FROM scenarios WHERE symbol=? ORDER BY timestamp DESC LIMIT ? OFFSET ?",
        (symbol,),
        "SELECT COUNT(*) FROM scenarios WHERE symbol=?",
        (symbol,),
        page, page_size,
    )
    conn.close()
    if rows:
        return _paginated_response(rows, total, page, page_size)
    return jsonify({"error": "no scenarios", "data_quality": DATA_QUALITY_UNAVAILABLE}), 404
    conn = get_db()
    row = conn.execute("SELECT * FROM scenarios WHERE symbol=? ORDER BY timestamp DESC LIMIT 1", (symbol,)).fetchone()
    conn.close()
    if row:
        return jsonify(row_to_dict(row))
    return jsonify({"error": "no scenarios"}), 404

@app.route("/api/outlook/<symbol>")
@cache_page(3600)
def outlook(symbol):
    conn = get_db()
    row = conn.execute("SELECT * FROM ai_outlooks WHERE symbol=? ORDER BY timestamp DESC LIMIT 1", (symbol,)).fetchone()
    conn.close()
    if row:
        return jsonify(row_to_dict(row))
    return jsonify({"error": "no outlook"}), 404

@app.route("/api/outlooks")
@cache_page(3600)
def all_outlooks():
    page, page_size = _page_params()
    conn = get_db()
    rows, total = _paginate_list(
        conn,
        "SELECT * FROM ai_outlooks ORDER BY timestamp DESC LIMIT ? OFFSET ?",
        (),
        "SELECT COUNT(*) FROM ai_outlooks",
        (),
        page, page_size,
    )
    conn.close()
    return _paginated_response(rows, total, page, page_size)

@app.route("/api/options/<symbol>")
@limiter.limit("30/minute")
@cache_page(600)
def options(symbol):
    expiry = request.args.get("expiry", "")
    conn = get_db()
    if expiry:
        rows = conn.execute("SELECT * FROM option_chain WHERE symbol=? AND expiry=? ORDER BY option_type, strike", (symbol, expiry)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM option_chain WHERE symbol=? ORDER BY fetched_at DESC LIMIT 200", (symbol,)).fetchall()
    conn.close()
    return jsonify([row_to_dict(r) for r in rows])

@app.route("/api/options/expiries/<symbol>")
@limiter.limit("30/minute")
@cache_page(600)
def option_expiries(symbol):
    conn = get_db()
    rows = conn.execute("SELECT * FROM option_expiries WHERE symbol=? ORDER BY expiry", (symbol,)).fetchall()
    conn.close()
    return jsonify([row_to_dict(r) for r in rows])

@app.route("/api/pcr")
@cache_page(600)
def pcr():
    """Put-Call Ratio per index symbol per expiry, from EOD OI data."""
    symbols = request.args.get("symbols", "NIFTY,BANKNIFTY,FINNIFTY").split(",")
    conn = get_db()
    out = {}
    for sym in symbols:
        sym = sym.strip().upper()
        expiries = conn.execute(
            "SELECT DISTINCT expiry FROM option_chain WHERE symbol=? ORDER BY expiry", (sym,)
        ).fetchall()
        sym_data = []
        for e in expiries:
            expiry = e["expiry"]
            pe = conn.execute("SELECT SUM(open_interest) s FROM option_chain WHERE symbol=? AND expiry=? AND option_type='PE'", (sym, expiry)).fetchone()["s"] or 0
            ce = conn.execute("SELECT SUM(open_interest) s FROM option_chain WHERE symbol=? AND expiry=? AND option_type='CE'", (sym, expiry)).fetchone()["s"] or 0
            pcr_val = round(pe / ce, 3) if ce > 0 else None
            sym_data.append({"expiry": expiry, "pcr": pcr_val, "pe_oi": pe, "ce_oi": ce})
        out[sym] = sym_data
    conn.close()
    return jsonify(out)

@app.route("/api/maxpain")
@cache_page(600)
def max_pain():
    """Max-pain strike per index symbol per expiry."""
    symbols = request.args.get("symbols", "NIFTY,BANKNIFTY,FINNIFTY").split(",")
    conn = get_db()
    out = {}
    for sym in symbols:
        sym = sym.strip().upper()
        expiries = conn.execute(
            "SELECT DISTINCT expiry FROM option_chain WHERE symbol=? ORDER BY expiry", (sym,)
        ).fetchall()
        sym_data = []
        from backend.options import OptionsEngine
        engine = OptionsEngine()
        for e in expiries:
            expiry = e["expiry"]
            chain = conn.execute(
                "SELECT strike, option_type, open_interest FROM option_chain WHERE symbol=? AND expiry=?",
                (sym, expiry)
            ).fetchall()
            mp_result = engine.calculate_max_pain([dict(r) for r in chain])
            mp_strike = mp_result["max_pain"]
            total_oi = sum(r["open_interest"] for r in chain if r["strike"] > 0 and r["open_interest"] > 0)
            sym_data.append({"expiry": expiry, "max_pain": mp_strike, "total_oi": total_oi, "strikes": len([r for r in chain if r["strike"] > 0 and r["open_interest"] > 0])})
        out[sym] = sym_data
    conn.close()
    return jsonify(out)

@app.route("/api/pcr-history")
@cache_page(600)
def pcr_history():
    """Daily PCR/max-pain trend per index symbol (for the small multi-day chart)."""
    symbols = request.args.get("symbols", "NIFTY,BANKNIFTY,FINNIFTY").split(",")
    days = request.args.get("days", 7, type=int)
    conn = get_db()
    out = {}
    for sym in symbols:
        sym = sym.strip().upper()
        rows = conn.execute(
            "SELECT * FROM pcr_history WHERE symbol=? ORDER BY date DESC LIMIT ?", (sym, days)
        ).fetchall()
        out[sym] = [row_to_dict(r) for r in reversed(rows)]
    conn.close()
    return jsonify(out)

@app.route("/api/oi-top")
@cache_page(600)
def oi_top():
    """Top OI strikes per symbol/expiry/side."""
    symbol = request.args.get("symbol", "NIFTY")
    expiry = request.args.get("expiry", "")
    conn = get_db()
    if expiry:
        rows = conn.execute("SELECT * FROM oi_top_strikes WHERE symbol=? AND expiry=? ORDER BY side, rank", (symbol, expiry)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM oi_top_strikes WHERE symbol=? ORDER BY side, rank LIMIT 40", (symbol,)).fetchall()
    conn.close()
    return jsonify([row_to_dict(r) for r in rows])

@app.route("/api/oi-concentration/<symbol>")
@cache_page(600)
def oi_concentration(symbol):
    """OI concentration per expiry with source-aware OI change."""
    symbol = symbol.upper()
    conn = get_db()

    spot = None
    qr = conn.execute("SELECT price FROM live_quotes WHERE symbol=? ORDER BY timestamp DESC LIMIT 1", (symbol,)).fetchone()
    if qr:
        spot = qr["price"]

    expiries = conn.execute(
        "SELECT DISTINCT expiry FROM option_chain WHERE symbol=? ORDER BY expiry", (symbol,)
    ).fetchall()

    out = {"symbol": symbol, "spot": spot}
    for e in expiries:
        expiry = e["expiry"]
        rows = conn.execute(
            "SELECT strike, option_type, open_interest, change_in_oi FROM option_chain WHERE symbol=? AND expiry=?",
            (symbol, expiry)
        ).fetchall()

        contracts = [dict(r) for r in rows]
        from backend.options import OptionsEngine
        engine = OptionsEngine()
        concentration = engine.compute_oi_concentration(contracts)

        # Add strike distance from spot
        if spot and spot > 0:
            for sd in concentration["strikes"]:
                sd["distance_from_spot_pct"] = round((sd["strike"] - spot) / spot * 100, 2)

        out[expiry] = concentration

    conn.close()
    return jsonify(out)

@app.route("/api/expected-move/<symbol>")
@cache_page(600)
def expected_move(symbol):
    """Options-implied expected move using ATM IV and time to expiry."""
    symbol = symbol.upper()
    conn = get_db()

    spot = None
    qr = conn.execute("SELECT price FROM live_quotes WHERE symbol=? ORDER BY timestamp DESC LIMIT 1", (symbol,)).fetchone()
    if qr:
        spot = qr["price"]

    expiries = conn.execute(
        "SELECT DISTINCT expiry FROM option_chain WHERE symbol=? ORDER BY expiry", (symbol,)
    ).fetchall()

    out = {"symbol": symbol, "spot": spot, "expected_moves": {}}
    for e in expiries:
        expiry = e["expiry"]
        rows = conn.execute(
            "SELECT strike, option_type, open_interest, implied_volatility FROM option_chain WHERE symbol=? AND expiry=?",
            (symbol, expiry)
        ).fetchall()
        contracts = [dict(r) for r in rows]
        from backend.options import OptionsEngine
        engine = OptionsEngine()
        result = engine.compute_expected_move(contracts, spot or 0, expiry)
        out["expected_moves"][expiry] = result["expected_move"]

    conn.close()
    return jsonify(out)

@app.route("/api/options-intelligence/<symbol>")
@limiter.limit("30/minute")
def options_intelligence(symbol):
    """Consolidated Options Intelligence: PCR, OI, Max Pain, IV, Expected Move, Options View, Confirmation."""
    symbol = symbol.upper()
    conn = get_db()
    try:
        from backend.options import OptionsEngine
        engine = OptionsEngine()

        spot = None
        qr = conn.execute("SELECT price FROM live_quotes WHERE symbol=? ORDER BY timestamp DESC LIMIT 1", (symbol,)).fetchone()
        if qr and qr["price"]:
            spot = qr["price"]

        expiries = conn.execute(
            "SELECT DISTINCT expiry FROM option_chain WHERE symbol=? ORDER BY expiry", (symbol,)
        ).fetchall()

        has_option_data = False
        for e in expiries:
            expiry = e["expiry"]
            rows = conn.execute(
                "SELECT strike, option_type, open_interest, change_in_oi, implied_volatility FROM option_chain WHERE symbol=? AND expiry=?",
                (symbol, expiry)
            ).fetchall()
            if rows:
                has_option_data = True
                break

        result = {
            "symbol": symbol,
            "spot": spot,
            "data_quality": "LIVE" if has_option_data else "DATA UNAVAILABLE",
            "as_of": datetime.now(timezone.utc).isoformat(),
            "pcr": None,
            "oi": None,
            "max_pain": None,
            "iv": None,
            "expected_move": None,
            "options_view": None,
            "confirmation": None,
            "data_completeness": _data_completeness(
                spot=spot is not None,
                option_chain=has_option_data,
            ),
        }

        for e in expiries:
            expiry = e["expiry"]
            rows = conn.execute(
                "SELECT strike, option_type, open_interest, change_in_oi, implied_volatility FROM option_chain WHERE symbol=? AND expiry=?",
                (symbol, expiry)
            ).fetchall()
            contracts = [dict(r) for r in rows]

            if contracts:
                concentration = engine.compute_oi_concentration(contracts)
                result["oi"] = {
                    "call_total": concentration["call_oi"],
                    "put_total": concentration["put_oi"],
                    "total_oi": concentration["total_oi"],
                    "call_oi_change": concentration["call_oi_change"],
                    "put_oi_change": concentration["put_oi_change"],
                    "change_available": concentration["oi_change_available"],
                    "highest_call_oi": concentration["highest_call_oi"],
                    "highest_put_oi": concentration["highest_put_oi"],
                    "oi_concentration": concentration["oi_concentration"],
                    "major_call_zones": concentration["major_call_zones"],
                    "major_put_zones": concentration["major_put_zones"],
                }

            total_ce_oi = sum(c["open_interest"] for c in contracts if c["option_type"] == "CE")
            total_pe_oi = sum(c["open_interest"] for c in contracts if c["option_type"] == "PE")
            if total_ce_oi + total_pe_oi > 0:
                result["pcr"] = {
                    "value": round(total_pe_oi / total_ce_oi, 3) if total_ce_oi > 0 else None,
                    "pe_oi": total_pe_oi,
                    "ce_oi": total_ce_oi,
                }

            if spot and spot > 0 and contracts:
                em = engine.compute_expected_move(contracts, spot, expiry)
                result["expected_move"] = em["expected_move"]

                if contracts:
                    atm_iv = engine.calculate_iv_stats(contracts)
                    result["iv"] = {
                        "atm": atm_iv.get("avg_iv"),
                        "min": atm_iv.get("min_iv"),
                        "max": atm_iv.get("max_iv"),
                    }

                if contracts:
                    mp = engine.calculate_max_pain(contracts)
                    mp_strike = mp.get("max_pain") if isinstance(mp, dict) else None
                    if mp_strike is not None:
                        result["max_pain"] = {"strike": mp_strike}

            break

        pcr_val = result["pcr"]["value"] if result.get("pcr") and result["pcr"].get("value") is not None else None
        mp_strike = result["max_pain"]["strike"] if result.get("max_pain") and result["max_pain"].get("strike") is not None else None
        em_result = result.get("expected_move") or {}
        em_points = em_result.get("points") if isinstance(em_result.get("points"), (int, float)) else None

        exp_bias = None
        exp_conf = 0
        derived = engine.derive_options_bias(mp_strike, spot, pcr_val, result.get("oi"))
        exp_bias = derived.get("options_bias")
        exp_conf = derived.get("options_confidence", 0)

        mkt_bias = "BULLISH"
        mkt_conf = 76
        try:
            from outlook import build_outlook
            from zoneinfo import ZoneInfo
            ist = datetime.now(ZoneInfo("Asia/Kolkata"))
            outlook = build_outlook(conn, symbol, ist.strftime("%Y-%m-%d"))
            if outlook and outlook.get("bias"):
                mkt_bias = outlook["bias"].get("label", "BULLISH")
            if outlook and outlook.get("confidence"):
                mkt_conf = outlook["confidence"]
        except Exception:
            pass

        if result["oi"] or result["pcr"] or em_points is not None:
            conf = engine.compute_confirmation(
                market_bias=mkt_bias, market_confidence=mkt_conf,
                options_bias=exp_bias, options_confidence=exp_conf,
                pcr_value=pcr_val, max_pain_strike=mp_strike, spot=spot,
                expected_move_points=em_points, oi_concentration=result.get("oi"),
            )
            result["confirmation"] = conf["confirmation"]
            result["options_view"] = {
                "bias": exp_bias if exp_bias else "NEUTRAL",
                "confidence": exp_conf,
                "reasons": conf["confirmation"].get("reasons", []),
            }

        return jsonify(result)
    finally:
        conn.close()

def _build_outlook_on_demand(conn, symbol):
    """Build a full outlook payload on the fly for any tracked symbol (index or stock)."""
    try:
        if not conn.execute("SELECT 1 FROM indicators WHERE symbol=? LIMIT 1", (symbol,)).fetchone():
            return None
        from zoneinfo import ZoneInfo
        from outlook import build_outlook
        ist = datetime.now(ZoneInfo("Asia/Kolkata"))
        payload = build_outlook(conn, symbol, ist.strftime("%Y-%m-%d"))
        payload["created_at"] = ist.strftime("%Y-%m-%d %H:%M:%S IST")
        payload["on_demand"] = True
        return payload
    except Exception:
        return None


@app.route("/api/market-outlook")
@cache_page(3600)
def market_outlook_latest():
    """Latest daily market outlook record (framework payload), LLM-primary."""
    symbol = request.args.get("symbol", "NIFTY").upper()
    try:
        from outlook import merge_llm_into_payload
    except Exception:
        merge_llm_into_payload = None
    conn = get_db()
    try:
        row = conn.execute("SELECT payload, created_at FROM market_outlooks WHERE symbol=? ORDER BY date DESC, id DESC LIMIT 1", (symbol,)).fetchone()
        if row is None:
            data = _build_outlook_on_demand(conn, symbol)
            if data is not None and merge_llm_into_payload is not None:
                data = merge_llm_into_payload(conn, symbol, data)
            if data is None:
                return jsonify({"error": f"no outlook yet for {symbol}"}), 404
            return jsonify(data)
        data = _parse_json_field(row["payload"])
        if merge_llm_into_payload is not None:
            data = merge_llm_into_payload(conn, symbol, data)
        data["created_at"] = row["created_at"]
        return jsonify(data)
    finally:
        conn.close()

@app.route("/api/market-outlook/<date>")
@cache_page(3600)
def market_outlook_by_date(date):
    """Market outlook for a specific date (YYYY-MM-DD)."""
    symbol = request.args.get("symbol", "NIFTY").upper()
    try:
        from outlook import merge_llm_into_payload
    except Exception:
        merge_llm_into_payload = None
    conn = get_db()
    row = conn.execute("SELECT payload, created_at FROM market_outlooks WHERE date=? AND symbol=? ORDER BY id DESC LIMIT 1", (date, symbol)).fetchone()
    if row is None:
        conn.close()
        return jsonify({"error": f"no outlook for {symbol} on " + date}), 404
    data = _parse_json_field(row["payload"])
    if merge_llm_into_payload is not None:
        data = merge_llm_into_payload(conn, symbol, data)
    conn.close()
    data["created_at"] = row["created_at"]
    return jsonify(data)

@app.route("/api/portfolio", methods=["GET"])
@limiter.limit("30/minute")
def portfolio_list():
    user_id = getattr(g, "user_id", None)
    if user_id is None:
        return error_response("UNAUTHORIZED", "Authentication required", 401)
    conn = get_db()
    rows = conn.execute("SELECT * FROM portfolio WHERE user_id=? ORDER BY created_at DESC", (user_id,)).fetchall()
    conn.close()
    items = [row_to_dict(r) for r in rows]
    try:
        quotes = market()  # reuse cached market payload for live LTPs
        instr = (quotes.get_json() if hasattr(quotes, "get_json") else {}).get("instruments", {})
    except Exception:
        instr = {}
    for it in items:
        q = instr.get(it["symbol"], {})
        price = q.get("price") or q.get("last_price")
        if it.get("exit_price"):
            price = it["exit_price"]
        if price:
            it["live_price"] = price
            it["market_value"] = round(price * (it.get("quantity") or 0), 2)
            if it.get("entry_price"):
                it["pnl_pct"] = round(((price - it["entry_price"]) / it["entry_price"]) * 100 * (1 if it.get("direction") != "SHORT" else -1), 2)
    return jsonify(items)

_VALID_SYMBOLS = None


def get_valid_symbols():
    global _VALID_SYMBOLS
    if _VALID_SYMBOLS is None:
        config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config", "instruments.json")
        with open(config_path) as f:
            config = json.load(f)
        _VALID_SYMBOLS = set()
        for inst in config["indices"] + config["stocks"]:
            _VALID_SYMBOLS.add(inst["symbol"])
    return _VALID_SYMBOLS


def validate_portfolio_payload(body):
    errors = {}
    symbol = (body.get("symbol") or "").strip().upper()
    if symbol not in get_valid_symbols():
        errors["symbol"] = "Symbol is not tracked"
    entry_price = body.get("entry_price")
    try:
        if entry_price is None or float(entry_price) <= 0:
            errors["entry_price"] = "Entry price must be positive"
    except (TypeError, ValueError):
        errors["entry_price"] = "Entry price must be a number"
    quantity = body.get("quantity")
    try:
        if quantity is None or int(quantity) < 1 or float(quantity) != int(quantity):
            errors["quantity"] = "Quantity must be a positive integer"
    except (TypeError, ValueError):
        errors["quantity"] = "Quantity must be an integer"
    direction = (body.get("direction") or "LONG").upper()
    if direction not in ("LONG", "SHORT"):
        errors["direction"] = "Direction must be LONG or SHORT"
    entry_date = body.get("entry_date")
    if entry_date:
        try:
            datetime.strptime(str(entry_date), "%Y-%m-%d")
        except ValueError:
            errors["entry_date"] = "Invalid date format (YYYY-MM-DD)"
    strategy = body.get("strategy")
    if not strategy or not str(strategy).strip():
        errors["strategy"] = "Strategy required"
    return errors


@app.route("/api/portfolio", methods=["POST"])
@limiter.limit("30/minute")
def portfolio_add():
    user_id = getattr(g, "user_id", None)
    if user_id is None:
        return error_response("UNAUTHORIZED", "Authentication required", 401)
    body = request.get_json(silent=True) or {}
    errors = validate_portfolio_payload(body)
    if errors:
        return error_response("INVALID_REQUEST", json.dumps(errors), 400)
    sym = (body.get("symbol") or "").strip().upper()
    direction = (body.get("direction") or "LONG").upper()
    conn = get_db()
    try:
        _execute_write(
            conn,
            "INSERT INTO portfolio (user_id, symbol, strategy, entry_price, quantity, direction, entry_date,"
            "exit_price, exit_date, points, result, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,datetime('now'))",
            (user_id, sym, body.get("strategy", ""), body.get("entry_price"), body.get("quantity"),
             direction, body.get("entry_date") or datetime.now(timezone.utc).date().isoformat(),
             body.get("exit_price"), body.get("exit_date"), body.get("points"),
             (body.get("result") or "").upper()),
        )
    finally:
        conn.close()
    return jsonify({"ok": True})

@app.route("/api/portfolio/<int:pid>", methods=["DELETE"])
@limiter.limit("30/minute")
def portfolio_delete(pid):
    user_id = getattr(g, "user_id", None)
    if user_id is None:
        return error_response("UNAUTHORIZED", "Authentication required", 401)
    conn = get_db()
    row = conn.execute("SELECT id FROM portfolio WHERE id=? AND user_id=?", (pid, user_id)).fetchone()
    if row is None:
        conn.close()
        return error_response("NOT_FOUND", "Portfolio entry not found", 404)
    conn.execute("DELETE FROM portfolio WHERE id=? AND user_id=?", (pid, user_id))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

_backtest_jobs = {}
_jobs_lock = threading.Lock()


def _validate_backtest_payload(body):
    errors = []
    if not body:
        return errors
    if "symbol" in body:
        sym = str(body.get("symbol", "")).strip().upper()
        if not sym:
            errors.append("symbol is required")
    if "days" in body:
        try:
            d = int(body.get("days", 0))
            if d <= 0:
                errors.append("days must be positive")
        except (TypeError, ValueError):
            errors.append("days must be integer")
    return errors


def _submit_backtest(job_id, engine_type, params):
    try:
        from backtest import BacktestEngine
        db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "database", "tradingai.db")
        engine = BacktestEngine(db_path)
        if engine_type == "run":
            result = engine.run(params.get("symbol", "NIFTY").strip().upper(), params.get("days", 30))
        elif engine_type == "run_vix_strangle":
            result = engine.run_vix_strangle(params.get("symbol", "NIFTY").strip().upper(), params.get("days", 3650))
        elif engine_type == "run_5m_real":
            result = engine.run_5m_real(params.get("symbol", "NIFTY").strip().upper(), params.get("days", 60))
        else:
            result = engine.run(params.get("symbol", "NIFTY").strip().upper(), params.get("days", 30))
        with _jobs_lock:
            _backtest_jobs[job_id] = {"status": "completed", "result": result}
    except Exception as e:
        with _jobs_lock:
            _backtest_jobs[job_id] = {"status": "failed", "error": str(e)}


@app.route("/api/backtest")
@limiter.limit("10/minute")
def backtest():
    body = request.args.to_dict() if request.method == "GET" else (request.get_json(silent=True) or {})
    if isinstance(body, dict) and body:
        errors = _validate_backtest_payload(body)
        if errors:
            return error_response("INVALID_REQUEST", json.dumps(errors), 400)
    else:
        body = request.args.to_dict()
    body["symbol"] = str(body.get("symbol", "NIFTY")).strip().upper()
    body["days"] = int(body.get("days", 30))

    job_id = str(uuid.uuid4())[:12]
    with _jobs_lock:
        _backtest_jobs[job_id] = {"status": "running", "started_at": datetime.now(timezone.utc).isoformat()}
    thread = threading.Thread(
        target=_submit_backtest,
        args=(job_id, "run", body),
        daemon=True,
    )
    thread.start()
    return jsonify({"job_id": job_id, "status": "running", "poll": f"/api/backtest/{job_id}"}), 202


@app.route("/api/backtest/vix-strangle")
@limiter.limit("10/minute")
def backtest_vix_strangle():
    body = request.args.to_dict() if request.method == "GET" else (request.get_json(silent=True) or {})
    if isinstance(body, dict) and body:
        errors = _validate_backtest_payload(body)
        if errors:
            return error_response("INVALID_REQUEST", json.dumps(errors), 400)
    else:
        body = request.args.to_dict()
    body["symbol"] = str(body.get("symbol", "NIFTY")).strip().upper()
    body["days"] = int(body.get("days", 3650))

    job_id = str(uuid.uuid4())[:12]
    with _jobs_lock:
        _backtest_jobs[job_id] = {"status": "running", "started_at": datetime.now(timezone.utc).isoformat()}
    thread = threading.Thread(
        target=_submit_backtest,
        args=(job_id, "run_vix_strangle", body),
        daemon=True,
    )
    thread.start()
    return jsonify({"job_id": job_id, "status": "running", "poll": f"/api/backtest/{job_id}"}), 202


@app.route("/api/backtest/5m-real")
@limiter.limit("10/minute")
def backtest_5m_real():
    body = request.args.to_dict() if request.method == "GET" else (request.get_json(silent=True) or {})
    if isinstance(body, dict) and body:
        errors = _validate_backtest_payload(body)
        if errors:
            return error_response("INVALID_REQUEST", json.dumps(errors), 400)
    else:
        body = request.args.to_dict()
    body["symbol"] = str(body.get("symbol", "NIFTY")).strip().upper()
    body["days"] = int(body.get("days", 60))

    job_id = str(uuid.uuid4())[:12]
    with _jobs_lock:
        _backtest_jobs[job_id] = {"status": "running", "started_at": datetime.now(timezone.utc).isoformat()}
    thread = threading.Thread(
        target=_submit_backtest,
        args=(job_id, "run_5m_real", body),
        daemon=True,
    )
    thread.start()
    return jsonify({"job_id": job_id, "status": "running", "poll": f"/api/backtest/{job_id}"}), 202


@app.route("/api/backtest/<job_id>", methods=["GET"])
def backtest_poll(job_id):
    with _jobs_lock:
        job = _backtest_jobs.get(job_id)
    if job is None:
        return error_response("NOT_FOUND", "Job not found", 404)
    if job["status"] == "running":
        return jsonify({"job_id": job_id, "status": "running"}), 202
    if job["status"] == "completed":
        return jsonify({"job_id": job_id, "status": "completed", "result": job["result"]})
    if job["status"] == "failed":
        return error_response("BACKTEST_FAILED", job["error"], 500)

@app.route("/api/alerts")
@cache_page(5)
def alerts():
    page, page_size = _page_params()
    symbol = request.args.get("symbol", "").strip().upper()
    conn = get_db()
    if symbol:
        rows, total = _paginate_list(
            conn,
            "SELECT * FROM alerts WHERE symbol=? ORDER BY timestamp DESC LIMIT ? OFFSET ?",
            (symbol,),
            "SELECT COUNT(*) FROM alerts WHERE symbol=?",
            (symbol,),
            page, page_size,
        )
    else:
        rows, total = _paginate_list(
            conn,
            "SELECT * FROM alerts ORDER BY timestamp DESC LIMIT ? OFFSET ?",
            (),
            "SELECT COUNT(*) FROM alerts",
            (),
            page, page_size,
        )
    conn.close()
    return _paginated_response(rows, total, page, page_size)

@app.route("/api/etf-holdings")
@cache_page(86400)
def etf_holdings():
    symbol = request.args.get("symbol", "").strip().upper()
    conn = get_db()
    if symbol:
        rows = conn.execute("SELECT * FROM etf_holdings WHERE symbol=? ORDER BY pct DESC", (symbol,)).fetchall()
    else:
        rows = conn.execute("SELECT symbol, holding_symbol, holding_name, pct, MAX(fetch_date) AS fetch_date"
                            " FROM etf_holdings GROUP BY symbol, holding_symbol ORDER BY symbol, pct DESC").fetchall()
    conn.close()
    return jsonify([row_to_dict(r) for r in rows])

@app.route("/api/breadth")
@cache_page(5)
def breadth():
    conn = get_db()
    row = conn.execute("SELECT * FROM market_breadth ORDER BY timestamp DESC LIMIT 1").fetchone()
    conn.close()
    if row:
        return jsonify(row_to_dict(row))
    return jsonify({"error": "no breadth"}), 404

@app.route("/api/index-breadth")
@cache_page(5)
def index_breadth():
    """Latest official NSE advances/declines per index."""
    conn = get_db()
    rows = conn.execute("""
        SELECT b.* FROM index_breadth b
        JOIN (SELECT index_name, MAX(timestamp) AS ts FROM index_breadth GROUP BY index_name) m
          ON m.index_name=b.index_name AND m.ts=b.timestamp
        ORDER BY b.index_name""").fetchall()
    conn.close()
    return jsonify([row_to_dict(r) for r in rows])


@app.route("/api/breadth/history")
@cache_page(5)
def breadth_history():
    page, page_size = _page_params()
    conn = get_db()
    rows, total = _paginate_list(
        conn,
        "SELECT * FROM market_breadth ORDER BY timestamp DESC LIMIT ? OFFSET ?",
        (),
        "SELECT COUNT(*) FROM market_breadth",
        (),
        page, page_size,
    )
    conn.close()
    return _paginated_response(list(reversed(rows)), total, page, page_size)

@app.route("/api/snapshot")
@cache_page(5)
def snapshot():
    conn = get_db()
    row = conn.execute("SELECT * FROM market_snapshots ORDER BY timestamp DESC LIMIT 1").fetchone()
    conn.close()
    if row:
        return jsonify(row_to_dict(row))
    return jsonify({"error": "no snapshot"}), 404

@app.route("/api/snapshots")
@cache_page(5)
def snapshots():
    page, page_size = _page_params()
    conn = get_db()
    rows, total = _paginate_list(
        conn,
        "SELECT * FROM market_snapshots ORDER BY timestamp DESC LIMIT ? OFFSET ?",
        (),
        "SELECT COUNT(*) FROM market_snapshots",
        (),
        page, page_size,
    )
    conn.close()
    return _paginated_response(rows, total, page, page_size)

@app.route("/api/fundamentals/<symbol>")
@cache_page(86400)
def fundamentals(symbol):
    conn = get_db()
    row = conn.execute("SELECT * FROM fundamentals WHERE symbol=? ORDER BY timestamp DESC LIMIT 1", (symbol,)).fetchone()
    conn.close()
    if row:
        return jsonify(row_to_dict(row))
    return jsonify({"error": "no fundamentals"}), 404

@app.route("/api/data_status")
@cache_page(5)
def data_status():
    conn = get_db()
    rows = conn.execute("SELECT * FROM data_status ORDER BY symbol").fetchall()
    conn.close()
    return jsonify([row_to_dict(r) for r in rows])

@app.route("/api/etf")
@cache_page(86400)
def etf():
    conn = get_db()
    rows = conn.execute("SELECT * FROM etf_data ORDER BY timestamp DESC LIMIT 50").fetchall()
    conn.close()
    return jsonify([row_to_dict(r) for r in rows])

_MARKET_BG_RUNNING = False


def _refresh_market_background():
    global _MARKET_BG_RUNNING
    _MARKET_BG_RUNNING = True
    while True:
        _time.sleep(15)
        try:
            data = _build_market()
            with _MARKET["lock"] if "lock" in _MARKET else _MARKET:
                _MARKET["data"] = data
                _MARKET["at"] = _time.time()
                _MARKET["building"] = False
        except Exception as e:
            app.logger.error(f"Market refresh failed: {e}")
            with _MARKET["lock"] if "lock" in _MARKET else _MARKET:
                _MARKET["building"] = False
        if _MARKET["data"] is None:
            pass


def _ensure_market_bg():
    global _MARKET_BG_RUNNING
    if not _MARKET_BG_RUNNING and _MARKET["data"] is not None:
        _MARKET_BG_RUNNING = True
        threading.Thread(target=_refresh_market_background, daemon=True).start()


@app.route("/api/market")
@cache_page(20)
def market():
    """Legacy shape: {instruments: {SYM: symbol_payload}, ai_outlook, last_updated, data_quality}.
    Non-blocking: stale data served during rebuild with STALE flag; background refresh thread
    keeps cache current so site-wide ticker and dashboard never block."""
    c = _MARKET
    now = _time.time()
    if "lock" not in c:
        c["lock"] = threading.Lock()
    with c["lock"]:
        if c["data"] is not None and (now - c["at"]) < _MARKET_TTL:
            return jsonify(c["data"])
        if c["data"] is not None:
            if not c.get("building"):
                c["building"] = True
                _ensure_market_bg()
            data = dict(c["data"]) if isinstance(c["data"], dict) else c["data"]
            if isinstance(data, dict):
                data["data_quality"] = DATA_QUALITY_STALE
                data["data_freshness"] = {"age_minutes": round(now - c["at"]), "stale": True}
            return jsonify(data)
        if not c.get("building"):
            c["building"] = True
        try:
            data = _build_market()
            c["data"] = data
            c["at"] = _time.time()
            c["building"] = False
            if data is not None:
                _ensure_market_bg()
                return jsonify(data)
        except Exception as e:
            app.logger.warning(f"market rebuild failed: {e}")
            c["building"] = False
    deadline = _time.time() + _MARKET_TTL + 15
    while c["data"] is None and _time.time() < deadline:
        _time.sleep(0.5)
        with c["lock"]:
            if c["data"] is not None:
                return jsonify(c["data"])
            if not c.get("building"):
                c["building"] = True
        try:
            data = _build_market()
            with c["lock"]:
                c["data"] = data
                c["at"] = _time.time()
                c["building"] = False
            if data is not None:
                _ensure_market_bg()
                return jsonify(data)
        except Exception:
            with c["lock"]:
                c["building"] = False
            break
    with c["lock"]:
        if c["data"] is None:
            return jsonify({"error": "market data unavailable", "data_quality": DATA_QUALITY_UNAVAILABLE}), 404
        data = c["data"]
        if isinstance(data, dict) and data.get("data_quality") not in (DATA_QUALITY_STALE, DATA_QUALITY_UNAVAILABLE):
            age = now - c["at"]
            if age > 30:
                data["data_quality"] = DATA_QUALITY_STALE
                data["data_freshness"] = {"age_minutes": round(age), "stale": True}
    return jsonify(c["data"])


def _build_market():
    conn = get_db()
    sym_rows = conn.execute("SELECT symbol FROM symbols WHERE active=1 ORDER BY type, symbol").fetchall()
    symbols = [r["symbol"] for r in sym_rows] or ["NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX"]
    conn.close()
    instruments = {}
    latest_ts = None
    # Reuse _symbol_data logic without extra HTTP: query directly.
    from flask import json as flask_json
    for sym in symbols:
        with app.test_request_context():
            resp = _symbol_data(sym)
            payload = resp.get_json()
        if payload and payload.get("quote"):
            instruments[sym] = payload
            ts = payload.get("last_updated")
            if ts and (not latest_ts or ts > latest_ts):
                latest_ts = ts
    nifty_ai = (instruments.get("NIFTY") or {}).get("ai_outlook", {})
    has_prices = any(bool(v.get("quote")) for v in instruments.values())
    return {"source": "TradingAI DB (AI-assisted)", "last_updated": latest_ts, "data_quality": (nifty_ai.get("data_quality") or "GOOD"), "ai_outlook": nifty_ai, "instruments": instruments, "data_completeness": {"instruments": bool(instruments), "ai_outlook": bool(nifty_ai), "has_prices": has_prices}}

GLOBAL_SYMBOLS = {
    "^NSEI": {"name": "NIFTY 50 (India)"},
    "^DJI": {"name": "Dow Jones"},
    "^GSPC": {"name": "S&P 500"},
    "^IXIC": {"name": "Nasdaq Composite"},
    "GC=F": {"name": "Gold"},
    "CL=F": {"name": "Crude Oil (WTI)"},
    "DX-Y.NYB": {"name": "US Dollar Index"},
    "INR=X": {"name": "USD/INR"},
    "^TNX": {"name": "US 10Y Yield"},
    "^VIX": {"name": "CBOE Volatility Index"},
}

_GLOBAL_CACHE = {"at": 0.0, "data": None}

_MARKET_TTL = 20
_MARKET = {"data": None, "at": 0.0, "building": False, "lock": threading.Lock()}


@app.route("/api/global")
def global_markets():
    """Live global markets via Yahoo (single batch download), cached 90s."""
    import math as _math
    import time as _time
    now = _time.time()
    if _GLOBAL_CACHE["data"] and now - _GLOBAL_CACHE["at"] < 90:
        return jsonify(_GLOBAL_CACHE["data"])
    out = {}
    try:
        import yfinance as yf
        syms = list(GLOBAL_SYMBOLS.keys())
        df = yf.download(syms, period="2d", interval="1d", group_by="ticker", auto_adjust=False, progress=False, threads=True)
        for s in syms:
            try:
                sub = df[s].dropna(how="all") if hasattr(df[s], "dropna") else df[s]
                closes = [float(v) for v in sub["Close"].tolist() if v is not None and not _math.isnan(v)]
                if not closes:
                    continue
                price = closes[-1]
                prev = closes[-2] if len(closes) > 1 else price
                change = price - prev
                chg_pct = (change / prev * 100) if prev else 0
                out[s] = {
                    "name": GLOBAL_SYMBOLS[s]["name"], "price": round(price, 2),
                    "change": round(change, 2), "change_pct": round(chg_pct, 2),
                    "yf": s, "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            except Exception:
                continue
    except Exception as e:
        app.logger.warning(f"Global fetch failed: {e}")
    _GLOBAL_CACHE.update({"at": now, "data": out})
    return jsonify(out)

@app.route("/api/history")
@cache_page(600)
def history():
    """Grouped {SYM: [...]} shape; covers history + monthly archive (1-year retention)."""
    symbol = request.args.get("symbol", "")
    days = request.args.get("days", 365, type=int)
    conn = get_db()
    if symbol:
        rows = conn.execute("SELECT *, 'live' AS _src FROM history WHERE UPPER(symbol)=UPPER(?) AND date >= date('now', '-' || ? || ' days') ORDER BY date DESC", (symbol, days)).fetchall()
        arch = conn.execute("SELECT *, 'archive' AS _src FROM history_archive WHERE UPPER(symbol)=UPPER(?) AND date >= date('now', '-' || ? || ' days') ORDER BY date DESC", (symbol, days)).fetchall()
    else:
        rows = conn.execute("SELECT *, 'live' AS _src FROM history WHERE date >= date('now', '-' || ? || ' days') ORDER BY symbol, date DESC", (days,)).fetchall()
        arch = conn.execute("SELECT *, 'archive' AS _src FROM history_archive WHERE date >= date('now', '-' || ? || ' days') ORDER BY symbol, date DESC", (days,)).fetchall()
    conn.close()
    rows = list(rows) + list(arch)
    grouped = {}
    for r in rows:
        d = row_to_dict(r)
        d.pop("_src", None)
        try:
            ntc = d.get("no_trade_conditions")
            d["no_trade_conditions"] = json.loads(ntc) if isinstance(ntc, str) and ntc else (ntc or [])
        except Exception:
            d["no_trade_conditions"] = []
        grouped.setdefault(d.get("symbol", "UNKNOWN"), []).append(d)
    for sym in grouped:
        grouped[sym].sort(key=lambda e: e.get("date", ""), reverse=True)

    # Live marked-to-market for any OPEN (in-session) paper trades.
    _mark_open_trades(grouped)
    return jsonify(grouped)

def _mark_open_trades(grouped) -> None:
    """Attach live_price / live_points to OPEN paper trades so history.html can
    show a floating P&L during the session (settles at the 15:20 close)."""
    open_rows = [e for entries in grouped.values() for e in entries if e.get("result") == "OPEN" and e.get("locked_price") is not None]
    if not open_rows:
        return
    quotes = {}
    try:
        data = _MARKET.get("data") if _MARKET else None
        # Only read the cached quote snapshot; never trigger a 20s rebuild here.
        if data is None:
            return
        instr = (data or {}).get("instruments", {})
        for sym, p in instr.items():
            q = (p or {}).get("quote") or {}
            if q.get("price") is not None:
                quotes[sym.upper()] = float(q["price"])
    except Exception:
        quotes = {}
    for e in open_rows:
        price = quotes.get(str(e.get("symbol", "")).upper())
        if price is None:
            continue
        e["live_price"] = price
        sign = -1 if str(e.get("direction", "")).upper() == "SHORT" else 1
        e["live_points"] = round((price - float(e["locked_price"])) * sign, 2)

@app.route("/api/investment/<symbol>")
def investment(symbol):
    """SHORT (weeks) + LONG (months) investment views for stocks."""
    conn = get_db()
    rows = conn.execute("SELECT * FROM investment_views WHERE UPPER(symbol)=UPPER(?) ORDER BY date DESC, horizon", (symbol,)).fetchall()
    conn.close()
    out = {}
    for r in rows:
        d = row_to_dict(r)
        if d.get("horizon") not in out:
            out[d.get("horizon")] = d
    return jsonify(out if out else {"error": "no investment views"}), 200 if out else 404


@app.route("/api/news")
def news():
    conn = get_db()
    rows = conn.execute("SELECT * FROM news ORDER BY timestamp DESC LIMIT 50").fetchall()
    conn.close()
    return jsonify([row_to_dict(r) for r in rows])

@app.route("/api/news/<symbol>")
def symbol_news(symbol):
    conn = get_db()
    rows = conn.execute("SELECT * FROM news WHERE UPPER(symbol)=UPPER(?) ORDER BY timestamp DESC LIMIT 20", (symbol,)).fetchall()
    conn.close()
    return jsonify([row_to_dict(r) for r in rows])

MF_CATEGORY_ORDER = ["Large Cap", "Flexi Cap", "Mid Cap", "Small Cap", "Multi Cap", "ELSS", "Index", "Value", "Balanced Advantage", "Liquid"]

@app.route("/api/mf")
def mutual_funds():
    """Ranked mutual fund buckets: watchlist funds with NAV + annualized 1Y/3Y/5Y returns."""
    conn = get_db()
    total = conn.execute("SELECT COUNT(*) c FROM mf_schemes").fetchone()["c"]
    counts = {r["category"]: r["c"] for r in conn.execute("SELECT category, COUNT(*) c FROM mf_schemes GROUP BY category")}
    buckets = []
    for cat in MF_CATEGORY_ORDER:
        rows = conn.execute(
            "SELECT scheme_code, scheme_name, fund_house, nav, nav_date, ret_1y, ret_3y, ret_5y, computed_at"
            " FROM mf_returns WHERE category LIKE ? ORDER BY ret_1y IS NULL, ret_1y DESC LIMIT 12",
            (f"%{cat}%",),
        ).fetchall()
        funds = [row_to_dict(r) for r in rows]
        buckets.append({"category": cat, "funds": funds, "schemes_tracked": counts.get(cat, 0)})
    conn.close()
    return jsonify({"total_schemes": total, "last_updated": datetime.now(timezone.utc).isoformat(), "buckets": buckets})

@app.route("/api/actions")
@cache_page(5)
def all_actions():
    """Latest corporate actions across symbols (dividends, splits, buybacks)."""
    conn = get_db()
    rows = conn.execute("SELECT * FROM corporate_actions ORDER BY timestamp DESC LIMIT 25").fetchall()
    conn.close()
    return jsonify([row_to_dict(r) for r in rows])

@app.route("/api/actions/<symbol>")
def symbol_actions():
    """Dividends + splits stored from Yahoo, newest first."""
    conn = get_db()
    rows = conn.execute("SELECT * FROM corporate_actions WHERE UPPER(symbol)=UPPER(?) ORDER BY timestamp DESC LIMIT 20", (symbol,)).fetchall()
    conn.close()
    return jsonify([row_to_dict(r) for r in rows])

@app.route("/api/company/<symbol>")
@cache_page(86400)
def company(symbol):
    """Latest stored company snapshot: info + analyst views + financials keys."""
    conn = get_db()
    row = conn.execute("SELECT * FROM fundamentals WHERE UPPER(symbol)=UPPER(?) ORDER BY timestamp DESC LIMIT 1", (symbol,)).fetchone()
    conn.close()
    if not row:
        return jsonify({"error": "no company data"}), 404
    d = row_to_dict(row)
    data = _parse_json_field(d.get("data"), {}) or {}
    return jsonify({
        "symbol": symbol.upper(), "timestamp": d.get("timestamp"),
        "analyst_recommendation": data.get("analyst_recommendation", {}),
        "analyst_price_targets": data.get("analyst_price_targets", {}),
        "earnings_dates": data.get("earnings_dates", []),
        "latest_dividend": data.get("latest_dividend", {}),
        "latest_split": data.get("latest_split", {}),
        "has_financial_statements": any(k.startswith("financials.") or k.startswith("balance_sheet.") or k.startswith("cashflow.") or k == "financial_statements" for k in data.keys()),
        "info": {k: v for k, v in data.items() if not isinstance(v, (dict, list))},
    })

# ── Chat: lightweight, VM-friendly (nginx 10s cache, rate-limited) ──
_CHAT_RATE = {}  # ip -> [timestamps]
_CHAT_MAX_PER_MIN = 8
_CHAT_MAX_LEN = 300

def _chat_rate_ok(ip: str) -> bool:
    now = _time.time()
    lst = _CHAT_RATE.get(ip, [])
    lst = [t for t in lst if now - t < 60]
    ok = len(lst) < _CHAT_MAX_PER_MIN
    if ok:
        lst.append(now)
    _CHAT_RATE[ip] = lst
    # prune map every ~200 keys
    if len(_CHAT_RATE) > 400:
        for k in list(_CHAT_RATE.keys())[:200]:
            if not _CHAT_RATE[k] or now - _CHAT_RATE[k][-1] > 300:
                _CHAT_RATE.pop(k, None)
    return ok

@app.route("/api/chat/messages", methods=["GET", "POST"])
@limiter.limit("30/minute")
def chat_messages():
    channel = (request.args.get("channel") or request.args.get("c") or "global").strip()[:20].lower() or "global"
    if request.method == "GET":
        try:
            limit = min(int(request.args.get("limit", "50")), 100)
            since = request.args.get("since", "0")
            since_id = int(since) if str(since).isdigit() else 0
        except Exception:
            limit, since_id = 50, 0
        conn = get_db()
        if since_id:
            rows = conn.execute("SELECT id, channel, username, text, kind, created_at FROM chat_messages WHERE channel=? AND id>? ORDER BY id ASC LIMIT ?", (channel, since_id, limit)).fetchall()
        else:
            rows = conn.execute("SELECT id, channel, username, text, kind, created_at FROM chat_messages WHERE channel=? ORDER BY id DESC LIMIT ? ", (channel, limit)).fetchall()
            rows = list(reversed(rows))
        # include latest system alerts inline so chat window shows TRADE without extra call
        conn.close()
        return jsonify([dict(r) for r in rows])
    # POST
    ip = request.headers.get("X-Forwarded-For", request.remote_addr or "0.0.0.0").split(",")[0].strip()
    if not _chat_rate_ok(ip):
        return jsonify({"error": "rate limited: 8/min"}), 429
    data = request.get_json(silent=True) or {}
    username = str(data.get("username") or request.args.get("username") or "Anonymous").strip()[:20] or "Anonymous"
    text = str(data.get("text") or data.get("message") or "").strip()
    kind = str(data.get("kind") or "user").strip()[:10]
    if kind not in ("user", "system", "alert"):
        kind = "user"
    if not text:
        return jsonify({"error": "empty"}), 400
    if len(text) > _CHAT_MAX_LEN:
        text = text[:_CHAT_MAX_LEN]
    # basic sanitize: strip control chars
    text = "".join(c for c in text if c == "\n" or ord(c) >= 32)
    username = "".join(c for c in username if ord(c) >= 32)[:20]
    ch = str(data.get("channel") or channel).strip()[:20].lower() or "global"
    ts = datetime.now(timezone.utc).isoformat()
    conn = get_db()
    try:
        cur = conn.execute("INSERT INTO chat_messages (channel, username, text, kind, created_at) VALUES (?,?,?,?,?)", (ch, username, text, kind, ts))
        conn.commit()
        nid = cur.lastrowid
        try:
            _execute_write(
                conn,
                "DELETE FROM chat_messages WHERE id NOT IN (SELECT id FROM chat_messages WHERE channel=? ORDER BY id DESC LIMIT 500) AND channel=?",
                (ch, ch),
            )
            _execute_write(
                conn,
                "DELETE FROM chat_messages WHERE id NOT IN (SELECT id FROM chat_messages ORDER BY id DESC LIMIT 2000)",
            )
        except Exception:
            pass
    finally:
        conn.close()
    return jsonify({"id": nid, "channel": ch, "username": username, "text": text, "kind": kind, "created_at": ts})

@app.route("/api/chat/alerts")
@limiter.limit("30/minute")
def chat_alerts():
    """Latest system alerts (TRADE/CLOSE/news) for chat window — nginx cache 10s makes polling cheap."""
    try:
        limit = min(int(request.args.get("limit", "20")), 50)
    except Exception:
        limit = 20
    conn = get_db()
    rows = conn.execute("SELECT id, channel, username, text, kind, created_at FROM chat_messages WHERE kind='alert' ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return jsonify([dict(r) for r in reversed(rows)])

def _push_chat_alert(channel: str, text: str, username: str = "AI"):
    """Fire-and-forget system alert into chat_messages (used by outlook.py / pnl_tracker)."""
    try:
        conn = get_db()
        ts = datetime.now(timezone.utc).isoformat()
        conn.execute("INSERT INTO chat_messages (channel, username, text, kind, created_at) VALUES (?,?,?,?,?)", (channel.strip()[:20].lower() or "alerts", username[:20], text[:500], "alert", ts))
        conn.execute("DELETE FROM chat_messages WHERE kind='alert' AND id NOT IN (SELECT id FROM chat_messages WHERE kind='alert' ORDER BY id DESC LIMIT 200)")
        conn.commit()
        conn.close()
    except Exception:
        pass

if __name__ == "__main__":
    port = int(os.environ.get("API_PORT", 8000))
    app.run(host="0.0.0.0", port=port, debug=False)
