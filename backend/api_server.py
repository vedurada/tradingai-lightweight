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
from data_fetcher_db import _validate_data_depth
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
    methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
    # A5: no frontend fetch uses credentials (verified) — cookies stay out.
    supports_credentials=False,
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


def _load_alert_rules():
    # B6.8: centralized operational thresholds. Missing/invalid file falls back
    # to the built-in defaults in monitoring.check_alerts — tuning never needs code.
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config", "alerting.json")
    try:
        with open(path) as f:
            rules = json.load(f)
        if not isinstance(rules, dict):
            raise ValueError("alerting.json must be a JSON object")
        return rules
    except Exception as e:
        logger.warning(f"Alert rules fallback to built-ins ({e})")
        return None


ALERT_RULES = _load_alert_rules()

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
        # SIGALRM can only be armed from the main thread; gthread workers
        # serve requests in worker threads, so skip arming there.
        if threading.current_thread() is threading.main_thread():
            signal.signal(signal.SIGALRM, _request_timeout_handler)
            signal.alarm(ENDPOINT_TIMEOUTS[endpoint])
    g.correlation_id = f"req-{uuid.uuid4().hex[:12]}"
    g.request_start = _time.monotonic()


@app.after_request
def _record_metrics_and_clear_timeout(response):
    # signal.alarm is process-wide; only disarm when armed on the main thread.
    if threading.current_thread() is threading.main_thread():
        try:
            signal.alarm(0)
        except Exception:
            pass
    try:
        response.headers["X-Correlation-ID"] = g.correlation_id
    except AttributeError:
        pass
    try:
        endpoint = request.endpoint
        if endpoint:
            duration_ms = (_time.monotonic() - getattr(g, "request_start", _time.monotonic())) * 1000
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
        error = _verify_bearer()
        if error is not None:
            return error


def _verify_bearer():
    """Shared Bearer check — identical 401 envelope everywhere.
    Returns None on success (and sets g.user_id), else an error response."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return error_response("UNAUTHORIZED", "Authentication required", 401)
    api_key = auth_header[7:]
    user_id = get_user_id_for_key(api_key)
    if user_id is None:
        return error_response("UNAUTHORIZED", "Authentication required", 401)
    g.user_id = user_id
    return None


signal.signal(signal.SIGTERM, lambda signum, frame: globals().__setitem__("_shutdown_in_progress", True) or app.logger.info("SIGTERM received — graceful shutdown started"))


@app.route("/api/metrics")
@limiter.exempt
def metrics():
    # A4: localhost observers stay open; remote callers need a Bearer key
    # (same 401 envelope). Keeps recon value out of public reach.
    remote = (request.remote_addr or "").split(",")[0].strip()
    if remote not in ("127.0.0.1", "::1"):
        auth_error = _verify_bearer()
        if auth_error is not None:
            return auth_error
    summary = monitor.get_summary()
    alerts = monitor.check_alerts(ALERT_RULES)
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
    pooled = PooledConnection(db_pool.get(), db_pool)
    # B6.4: track per-request connections so teardown_request can reclaim slots
    # leaked by view paths that raise before reaching conn.close().
    try:
        conns = g._db_conns
    except Exception:
        try:
            g._db_conns = conns = []
        except Exception:
            return pooled
    conns.append(pooled)
    return pooled

def row_to_dict(row):
    if row is None:
        return None
    return dict(row)


@app.teardown_request
def _close_leaked_connections(exc):
    # B6.4 safety net: reclaim pool slots from views that raised before
    # conn.close(). PooledConnection.close() is idempotent, so explicit
    # closes plus this pass never double-return.
    try:
        conns = getattr(g, "_db_conns", None)
    except Exception:
        return
    if not conns:
        return
    for c in conns:
        try:
            c.close()
        except Exception:
            pass


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
        assert_table_name(table)
        date_col = "date" if table == "market_outlooks" else "timestamp"
        row = conn.execute(f"SELECT MAX({date_col}) as ts FROM {table}").fetchone()
        if not row or not row["ts"]:
            result = {"status": "unavailable", "age_minutes": None}
        else:
            age = data_age_minutes(row["ts"])
            if age is None:
                result = {"status": "unavailable", "age_minutes": None}
            elif age > threshold:
                result = {"status": "stale", "age_minutes": round(age), "threshold": threshold}
            else:
                result = {"status": "ok", "age_minutes": round(age)}

            try:
                depth_row = conn.execute(f"SELECT COUNT(*) as cnt FROM {table}").fetchone()
                if depth_row and depth_row["cnt"] < 5:
                    result["depth_issues"] = [f"low_row_count: {depth_row['cnt']}"]
            except Exception:
                pass

        return result
    except Exception:
        return {"status": "unavailable", "age_minutes": None}
    finally:
        conn.close()


def _deep_health_check():
    try:
        return _validate_data_depth()
    except Exception:
        return {"tables_checked": 0, "all_healthy": False, "details": {}}


def _record_fetch_result(source, success, error_msg=None):
    # B6.7: writes to fetch_health (source-grained). Previously targeted
    # nonexistent data_status columns and always rolled back.
    conn = get_db()
    try:
        now = datetime.now(timezone.utc).isoformat()
        if success:
            conn.execute(
                "INSERT INTO fetch_health (source, success_count, error_count, consecutive_failures, last_error, last_ok_at)"
                " VALUES (?, 1, 0, 0, NULL, ?) ON CONFLICT(source) DO UPDATE SET"
                " success_count = success_count + 1, consecutive_failures = 0, last_ok_at = excluded.last_ok_at",
                (source, now),
            )
        else:
            conn.execute(
                "INSERT INTO fetch_health (source, success_count, error_count, consecutive_failures, last_error, last_ok_at)"
                " VALUES (?, 0, 1, 1, ?, NULL) ON CONFLICT(source) DO UPDATE SET"
                " error_count = error_count + 1, consecutive_failures = consecutive_failures + 1, last_error = excluded.last_error",
                (source, error_msg),
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
        assert_table_name(table)
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
    try:
        deep = _deep_health_check()
    except Exception:
        deep = {"tables_checked": 0, "all_healthy": False, "details": {}}
    try:
        size_conn = get_db()
        try:
            sz = size_conn.execute("SELECT page_count * page_size AS bytes FROM pragma_page_count(), pragma_page_size()").fetchone()
            db_size_mb = round((sz["bytes"] if sz and sz["bytes"] else 0) / 1024 / 1024, 2)
        finally:
            size_conn.close()
    except Exception:
        db_size_mb = None
    return jsonify({
        "status": overall,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "warnings": warnings,
        "data_freshness": freshness,
        "sources": sources,
        "overall": overall,
        "pool": pool_status,
        "deep_health": deep,
        "db_size_mb": db_size_mb,
    })

@app.route("/api/ready")
@limiter.exempt
def ready():
    # B6.9: PROCESS readiness only — DB file readable + pool alive.
    # Deliberately no freshness/deep_health/overall verdict: a ready process
    # must never imply healthy market data. /api/health stays authoritative.
    issues = []
    try:
        probe = get_db()
        try:
            probe.execute("SELECT 1 FROM symbols LIMIT 1").fetchone()
        finally:
            probe.close()
    except Exception as e:
        issues.append(f"db_unreadable: {type(e).__name__}")
    try:
        if db_pool.status["exhausted"]:
            issues.append("connection pool exhausted")
    except Exception as e:
        issues.append(f"pool_unknown: {type(e).__name__}")
    if issues:
        return jsonify({"ready": False, "issues": issues}), 503
    return jsonify({"ready": True, "issues": []})

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
        age = data_age_minutes(d.get("timestamp"))
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
    source = d.get("source", "NSE") if live_row else "yfinance"
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
    try:
        row = conn.execute("SELECT * FROM market_regime WHERE symbol=? ORDER BY timestamp DESC LIMIT 1", (symbol,)).fetchone()
    finally:
        conn.close()
    if row:
        return jsonify(row_to_dict(row))
    return jsonify({"error": "no regime"}), 404

@app.route("/api/regimes")
@cache_page(3600)
def all_regimes():
    page, page_size = _page_params()
    conn = get_db()
    try:
        rows, total = _paginate_list(
            conn,
            "SELECT * FROM market_regime ORDER BY timestamp DESC LIMIT ? OFFSET ?",
            (),
            "SELECT COUNT(*) FROM market_regime",
            (),
            page, page_size,
        )
    finally:
        conn.close()
    return _paginated_response(rows, total, page, page_size)

@app.route("/api/strategy/<symbol>")
@cache_page(3600)
def strategy(symbol):
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM strategies WHERE symbol=? ORDER BY timestamp DESC LIMIT 1", (symbol,)).fetchone()
    finally:
        conn.close()
    if row:
        d = row_to_dict(row)
        d["name"] = d.get("strategy")
        d["entry"] = d.get("entry_trigger")
        d["risk"] = d.get("maximum_loss")
        d["strategies"] = [{"name": d.get("strategy"), "entry": d.get("entry_trigger"), "risk": d.get("maximum_loss"), "target": d.get("target"), "rank": 1}]
        return jsonify(d)
    return jsonify({"error": "no strategy"}), 404

@app.route("/api/strategies")
@cache_page(3600)
def all_strategies():
    page, page_size = _page_params()
    conn = get_db()
    try:
        rows, total = _paginate_list(
            conn,
            "SELECT * FROM strategies ORDER BY timestamp DESC LIMIT ? OFFSET ?",
            (),
            "SELECT COUNT(*) FROM strategies",
            (),
            page, page_size,
        )
    finally:
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
        from options import OptionsEngine
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
        from options import OptionsEngine
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
        from options import OptionsEngine
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
        from options import OptionsEngine
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
    """Latest daily market outlook record (framework payload), LLM-primary.
    Returns both raw fields (for indices pages) and outlook wrapper (for today terminal)."""
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
            data["outlook"] = {k: data.get(k) for k in ["bias", "confidence", "primary_view", "key_drivers", "regime", "decision", "date", "symbol"]}
            return jsonify(data)
        data = _parse_json_field(row["payload"])
        if merge_llm_into_payload is not None:
            data = merge_llm_into_payload(conn, symbol, data)
        data["created_at"] = row["created_at"]
        data["outlook"] = {k: data.get(k) for k in ["bias", "confidence", "primary_view", "key_drivers", "regime", "decision", "date", "symbol"]}
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
    data["outlook"] = {k: data.get(k) for k in ["bias", "confidence", "primary_view", "key_drivers", "regime", "decision", "date", "symbol"]}
    return jsonify(data)

@app.route("/api/market-outlooks")
@cache_page(600)
def market_outlooks_range():
    """Market outlooks for a date range."""
    symbol = request.args.get("symbol", "NIFTY").upper()
    date_from = request.args.get("from")
    date_to = request.args.get("to")
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT date, payload, created_at FROM market_outlooks WHERE symbol=? AND date >= ? AND date <= ? ORDER BY date ASC",
            (symbol, date_from or "2016-01-01", date_to or "2099-12-31"),
        ).fetchall()
        outlooks = []
        for r in rows:
            p = _parse_json_field(r["payload"])
            decision = (p.get("decision") or {})
            verdict = decision.get("verdict") or "WAIT"
            conf = p.get("confidence")
            strat0 = ((p.get("strategies") or [{}])[0].get("name") if p.get("strategies") else None)
            if verdict == "WAIT" and isinstance(conf, (int, float)) and conf >= 32 and strat0 and strat0.upper() != "NO TRADE":
                verdict = "TRADE"
            outlooks.append({
                "date": r["date"],
                "verdict": verdict,
                "confidence": conf,
                "regime": (p.get("regime") or {}).get("primary"),
                "bias": (p.get("bias") or {}).get("label"),
                "tradeability": (p.get("tradeability") or {}).get("band"),
                "strategy": ((p.get("strategies") or [{}])[0].get("name") if p.get("strategies") else None),
            })
        return jsonify({"symbol": symbol, "count": len(outlooks), "outlooks": outlooks})
    finally:
        conn.close()

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


@app.route("/api/walkforward/<symbol>/<start>/<end>")
@limiter.limit("10/minute")
def walkforward(symbol, start, end):
    from walkforward import run_walkforward
    symbol = str(symbol).strip().upper()
    db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "database", "tradingai.db")
    try:
        results = run_walkforward(
            symbol=symbol,
            start_date=start,
            end_date=end,
            dev_days=int(request.args.get("dev_days", 30)),
            val_days=int(request.args.get("val_days", 14)),
            oos_days=int(request.args.get("oos_days", 14)),
            step_days=int(request.args.get("step_days", 0)) or 14,
            db_path=db_path,
        )
        return jsonify({"symbol": symbol, "windows": [r._asdict() for r in results]})
    except Exception as e:
        return error_response("WALKFORWARD_FAILED", str(e), 500)


@app.route("/api/evidence/<symbol>/<date>")
@limiter.limit("10/minute")
def evidence(symbol, date):
    from historical_evidence import run_historical_evidence, SimilarityCondition
    symbol = str(symbol).strip().upper()
    db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "database", "tradingai.db")
    try:
        conditions = SimilarityCondition(
            regime=request.args.get("regime", "ANY"),
            gap_direction=request.args.get("gap", "ANY"),
            price_location=request.args.get("location", "ANY"),
            vwap_position=request.args.get("vwap", "ANY"),
            rsi_range_min=int(request.args.get("rsi_min", 0)) if request.args.get("rsi_min") else None,
            rsi_range_max=int(request.args.get("rsi_max", 100)) if request.args.get("rsi_max") else None,
            trade_readiness=request.args.get("readiness", "ANY"),
            setup_type=request.args.get("setup", "ANY"),
        )
        result = run_historical_evidence(
            symbol=symbol,
            query_date=date,
            conditions=conditions,
            db_path=db_path,
        )
        return jsonify(result._asdict())
    except Exception as e:
        return error_response("EVIDENCE_FAILED", str(e), 500)


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
    try:
        rows = conn.execute("SELECT * FROM data_status ORDER BY symbol").fetchall()
        try:
            health = conn.execute("SELECT * FROM fetch_health ORDER BY source").fetchall()
        except Exception:
            health = []
    finally:
        conn.close()
    return jsonify({
        "symbols": [row_to_dict(r) for r in rows],
        "fetch_health": [row_to_dict(r) for r in health],
    })

@app.route("/api/etf")
@cache_page(86400)
def etf():
    conn = get_db()
    rows = conn.execute("SELECT * FROM etf_data ORDER BY timestamp DESC LIMIT 50").fetchall()
    conn.close()
    return jsonify([row_to_dict(r) for r in rows])

_MARKET_BG_RUNNING = False
_LAST_MARKET_CHANGE = {"data": None, "at": 0.0}


def _refresh_market_background():
    global _MARKET_BG_RUNNING
    _MARKET_BG_RUNNING = True
    while True:
        _time.sleep(15)
        try:
            data = _build_market()
            mc_data = None
            try:
                import market_change
                mc = market_change.analyze("NIFTY")
                if mc.get("material"):
                    app.logger.info(f"Material market change detected: {mc['changes']}")
                mc_data = mc
            except Exception as exc:
                app.logger.debug(f"market_change check skipped: {exc}")
            with _MARKET["lock"] if "lock" in _MARKET else _MARKET:
                _MARKET["data"] = data
                _MARKET["at"] = _time.time()
                _MARKET["building"] = False
            global _LAST_MARKET_CHANGE
            _LAST_MARKET_CHANGE = {"data": mc_data, "at": _time.time()}
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


@app.route("/api/market-change")
def market_change_endpoint():
    """Material change status from market_change engine.

    Returns the latest material change analysis: whether a material change
    was detected, what changed, and the change details for display.
    Stale after 15 minutes (background refresh interval)."""
    now = _time.time()
    d = _LAST_MARKET_CHANGE
    if d["data"] is not None and (now - d["at"]) < 900:
        return jsonify(d["data"])
    if d["data"] is not None:
        stale = dict(d["data"])
        stale["stale"] = True
        return jsonify(stale)
    return jsonify({"material": False, "reason": "no_data", "changes": []}), 200


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
    _nq = nifty_ai.get("data_quality")
    if _nq == DATA_QUALITY_PARTIAL:
        _nq = "GOOD"
    return {"source": "TradingAI DB (AI-assisted)", "last_updated": latest_ts, "data_quality": (_nq or "GOOD"), "ai_outlook": nifty_ai, "instruments": instruments, "data_completeness": {"instruments": bool(instruments), "ai_outlook": bool(nifty_ai), "has_prices": has_prices}}

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
    # A2: only key holders may speak as system/alert; unauthenticated callers
    # get the identical 401 envelope as portfolio endpoints.
    if kind in ("system", "alert"):
        auth_error = _verify_bearer()
        if auth_error is not None:
            return auth_error
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

@app.route("/api/market/state/<symbol>")
@cache_page(60)
def market_state(symbol):
    """Complete market state for a symbol: indicators + regime + SR + expected range.

    All values are observed or derived — NEVER synthesized.
    Timestamp is candle timestamp (look-ahead protection).
    """
    symbol = (symbol or "").upper()
    conn = get_db()
    try:
        from market_state import build_market_state
        state = build_market_state(symbol, conn)
        if state is None:
            return jsonify({"error": "no market state", "data_quality": DATA_QUALITY_UNAVAILABLE}), 404
        result = state.to_dict()
        result["data_quality"] = DATA_QUALITY_LIVE
        result["data_freshness"] = {"age_minutes": 0, "stale": False}
        result["computed_at"] = datetime.now(timezone.utc).isoformat()
        return jsonify(result)
    except Exception as e:
        return error_response("INTERNAL_ERROR", str(e), 500)
    finally:
        conn.close()


@app.route("/api/market/expected-range/<symbol>")
@cache_page(600)
def expected_range_endpoint(symbol):
    """Expected price range from ATR + VIX for a symbol."""
    symbol = (symbol or "").upper()
    conn = get_db()
    try:
        from expected_range import compute_expected_range
        ind_row = conn.execute(
            "SELECT * FROM indicators WHERE symbol=? ORDER BY timestamp DESC LIMIT 1", (symbol,)
        ).fetchone()
        if not ind_row:
            return jsonify({"error": "no indicators", "data_quality": DATA_QUALITY_UNAVAILABLE}), 404
        ind = dict(ind_row)
        price = ind.get("day_high", 0) or ind.get("close", 0) or 0
        bb = {"upper": ind.get("bollinger_upper"), "lower": ind.get("bollinger_lower"),
              "middle": ind.get("bollinger_middle"), "width": ind.get("bollinger_width")}
        atr = ind.get("atr")
        sr = _parse_json_field(ind.get("support_resistance"), {})
        ind_for_range = {"bollinger_bands": bb if bb.get("upper") else None,
                         "atr": atr, "support_resistance": sr if isinstance(sr, dict) else {}}
        expected = compute_expected_range(ind_for_range, price, None)
        expected["data_quality"] = DATA_QUALITY_LIVE
        expected["symbol"] = symbol
        expected["timestamp"] = ind.get("timestamp", "")
        return jsonify(expected)
    except Exception as e:
        return error_response("INTERNAL_ERROR", str(e), 500)
    finally:
        conn.close()


@app.route("/api/market/validate/<symbol>")
@cache_page(300)
def market_validate(symbol):
    """Market data validation report for a symbol."""
    symbol = (symbol or "").upper()
    conn = get_db()
    try:
        from data_validator import MarketValidator
        mv = MarketValidator(DB_PATH)
        result = {"symbol": symbol, "checks": {}}

        cont_1m = mv.validate_candle_continuity(conn, symbol, "price_1m", 1)
        cont_5m = mv.validate_candle_continuity(conn, symbol, "price_5m", 5)
        ohlc_5m = mv.validate_candle_ohlc(conn, "price_5m")
        ohlc_1m = mv.validate_candle_ohlc(conn, "price_1m")
        ist = mv.validate_ist_timestamps(conn, "price_1m")

        if cont_1m["gaps"]:
            result["checks"]["continuity_1m"] = cont_1m
        if cont_5m["gaps"]:
            result["checks"]["continuity_5m"] = cont_5m
        if ohlc_5m["invalid"] > 0:
            result["checks"]["ohlc_5m"] = ohlc_5m
        if ohlc_1m["invalid"] > 0:
            result["checks"]["ohlc_1m"] = ohlc_1m
        if ist["non_ist_count"] > 0:
            result["checks"]["ist_timestamps"] = ist

        try:
            mc = mv.validate_market_candles(conn)
            result["checks"]["market_candles"] = mc
        except Exception:
            pass

        result["valid"] = len(result["checks"]) == 0
        return jsonify(result)
    except Exception as e:
        return error_response("INTERNAL_ERROR", str(e), 500)
    finally:
        conn.close()


@app.route("/api/options/state/<symbol>")
@limiter.limit("30/minute")
def options_state(symbol):
    """Options Intelligence State: bias, key levels, options snapshot with evidence and uncertainty. Mobile-first format."""
    symbol = symbol.upper()
    if symbol not in ("NIFTY", "BANKNIFTY", "SENSEX"):
        return error_response("NOT_SUPPORTED", f"{symbol} is not available as a live options product", 404)
    conn = get_db()
    try:
        spot = None
        qr = conn.execute("SELECT price FROM live_quotes WHERE symbol=? ORDER BY timestamp DESC LIMIT 1", (symbol,)).fetchone()
        if qr and qr["price"]:
            spot = qr["price"]

        rows = conn.execute(
            "SELECT strike, option_type, open_interest, change_in_oi, implied_volatility, volume FROM option_chain WHERE symbol=? ORDER BY strike",
            (symbol,),
        ).fetchall()
        chain = [dict(r) for r in rows]

        if not chain:
            from options_state import OptionsState
            state = OptionsState(
                symbol=symbol, timestamp="", spot=spot,
                atm_strike=None, expiry=None, dte=None,
                pcr=None, pe_oi=None, ce_oi=None, total_oi=None,
                max_pain=None, iv_atm=None, iv_rank=None,
                expected_move=None, bias="NEUTRAL", confidence=0,
                evidence=[], uncertainty=["No option chain data available"],
                data_quality="DATA UNAVAILABLE",
            )
            return jsonify(state.to_dict())

        from options_normalizer import build_options_state
        state = build_options_state(symbol, chain, spot, data_quality="LIVE")
        return jsonify(state.to_dict())
    except Exception as e:
        return error_response("INTERNAL_ERROR", str(e), 500)
    finally:
        conn.close()


@app.route("/api/trade-setup/<symbol>")
@limiter.limit("30/minute")
def trade_setup(symbol):
    """Trade Setup: Market + Options + Gap → lifecycle stages with readiness GO/WAIT/NO_SETUP."""
    symbol = symbol.upper()
    if symbol not in ("NIFTY", "BANKNIFTY", "SENSEX"):
        return error_response("NOT_SUPPORTED", f"{symbol} is not available as a live options product", 404)
    conn = get_db()
    try:
        from trade_lifecycle import detect_trade_setup

        # Spot from live quotes
        spot = None
        qr = conn.execute("SELECT price FROM live_quotes WHERE symbol=? ORDER BY timestamp DESC LIMIT 1", (symbol,)).fetchone()
        if qr and qr["price"]:
            spot = qr["price"]

        # Market indicators
        ind = conn.execute(
            "SELECT rsi, adx, atr, vwap, pivot, prev_day_close, day_high, day_low FROM indicators WHERE symbol=? ORDER BY timestamp DESC LIMIT 1",
            (symbol,)).fetchone()
        ind = dict(ind) if ind else {}

        # Regime
        reg = conn.execute(
            "SELECT regime, confidence FROM market_regime WHERE symbol=? ORDER BY timestamp DESC LIMIT 1",
            (symbol,)).fetchone()
        reg = dict(reg) if reg else {}

        # Previous close for gap calculation
        prev_close = None
        if ind.get("prev_day_close"):
            prev_close = ind["prev_day_close"]
        else:
            pc = conn.execute(
                "SELECT close FROM price_1d WHERE symbol=? AND date(timestamp) < date('now') ORDER BY timestamp DESC LIMIT 1",
                (symbol,)).fetchone()
            if pc:
                prev_close = pc["close"]

        # Open price
        day_open = ind.get("day_open")
        if not day_open and spot:
            day_open = spot

        # Gap calculation
        gap = None
        if day_open and prev_close:
            try:
                gap_pts = float(day_open) - float(prev_close)
                gap_pct = round(gap_pts / float(prev_close) * 100, 2)
                kind = "GAP UP" if gap_pts > float(prev_close) * 0.0015 else "GAP DOWN" if gap_pts < -float(prev_close) * 0.0015 else "FLAT OPEN"
                gap = {
                    "gap_pct": gap_pct,
                    "kind": kind,
                    "open": float(day_open),
                    "high": ind.get("day_high"),
                    "low": ind.get("day_low"),
                    "prev_close": float(prev_close),
                }
            except (TypeError, ValueError):
                gap = None

        # Market state
        market_state = None
        if ind:
            market_state = {
                "spot": spot,
                "regime": reg,
                "confidence": reg.get("confidence") if reg else None,
                "indicators": {k: v for k, v in ind.items() if v is not None},
            }

        # Options state (best effort)
        options_state = None
        try:
            rows = conn.execute(
                "SELECT strike, option_type, open_interest, implied_volatility FROM option_chain WHERE symbol=? ORDER BY strike",
                (symbol,)).fetchall()
            if rows:
                from options_normalizer import build_options_state
                chain = [dict(r) for r in rows]
                options_state = build_options_state(symbol, chain, spot)
        except Exception:
            pass

        timestamp = ""
        try:
            from datetime import datetime, timezone
            timestamp = datetime.now(timezone.utc).isoformat()
        except Exception:
            pass

        setup = detect_trade_setup(
            symbol=symbol,
            market_state=market_state,
            options_state=options_state.to_dict() if options_state else None,
            gap=gap,
            timestamp=timestamp,
            data_quality="LIVE" if spot else "DATA UNAVAILABLE",
        )
        return jsonify(setup.to_dict())
    except Exception as e:
        return error_response("INTERNAL_ERROR", str(e), 500)
    finally:
        conn.close()


@app.route("/api/replay/<symbol>/<date>")
@limiter.limit("30/minute")
def replay(symbol, date):
    """Historical AI Replay: timestamp-by-timestamp with strict no-lookahead."""
    symbol = symbol.upper()
    if symbol not in ("NIFTY", "BANKNIFTY", "SENSEX"):
        return error_response("NOT_SUPPORTED", f"{symbol} is not available as a live options product", 404)
    conn = get_db()
    try:
        from replay_engine import replay_day

        # Get 5m candles for the day
        try:
            rows = conn.execute(
                "SELECT timestamp, open, high, low, close, volume FROM price_5m WHERE symbol=? AND date(timestamp)=? ORDER BY timestamp",
                (symbol, date),
            ).fetchall()
            candles = [dict(r) for r in rows]
        except Exception:
            candles = []

        # Previous close from price_1d
        prev_close = None
        try:
            pc = conn.execute(
                "SELECT close FROM price_1d WHERE symbol=? AND date(timestamp) < ? ORDER BY timestamp DESC LIMIT 1",
                (symbol, date),
            ).fetchone()
            if pc and pc["close"]:
                prev_close = float(pc["close"])
        except Exception:
            pass

        # Options chain
        options_chain = None
        try:
            oc = conn.execute(
                "SELECT strike, option_type, open_interest, implied_volatility FROM option_chain WHERE symbol=? ORDER BY strike",
                (symbol,),
            ).fetchall()
            if oc:
                options_chain = [dict(r) for r in oc]
        except Exception:
            pass

        # Determine data quality
        data_quality = "LIVE" if candles else "DATA UNAVAILABLE"

        snapshots = replay_day(
            symbol=symbol,
            date=date,
            candles=candles,
            prev_close=prev_close,
            options_chain=options_chain,
            options_timestamp=None,
        )

        result = {
            "symbol": symbol,
            "date": date,
            "data_quality": data_quality,
            "snapshots": [s.to_dict() for s in snapshots],
            "total_snapshots": len(snapshots),
        }
        return jsonify(result)
    except Exception as e:
        return error_response("INTERNAL_ERROR", str(e), 500)
    finally:
        conn.close()


# Quote tracker instances (global, per symbol)
_quote_trackers: Dict[str, Any] = {}


@app.route("/api/quote/telemetry/<symbol>")
@limiter.limit("30/minute")
def quote_telemetry(symbol):
    """Quote telemetry: cadence, freshness, source info for a symbol."""
    symbol = symbol.upper()
    if symbol not in ("NIFTY", "BANKNIFTY", "SENSEX"):
        return error_response("NOT_SUPPORTED", f"{symbol} is not a tracked symbol", 404)
    try:
        from quote_tracker import QuoteTracker
        if symbol not in _quote_trackers:
            _quote_trackers[symbol] = QuoteTracker(symbol)
        tracker = _quote_trackers[symbol]
        return jsonify(tracker.get_telemetry())
    except Exception as e:
        return error_response("INTERNAL_ERROR", str(e), 500)


@app.route("/api/quote/track/<symbol>")
@limiter.limit("60/minute")
def quote_track(symbol):
    """Track a single quote: returns the quote with telemetry metadata."""
    symbol = symbol.upper()
    if symbol not in ("NIFTY", "BANKNIFTY", "SENSEX"):
        return error_response("NOT_SUPPORTED", f"{symbol} is not a tracked symbol", 404)
    conn = get_db()
    try:
        from quote_tracker import QuoteTracker
        if symbol not in _quote_trackers:
            _quote_trackers[symbol] = QuoteTracker(symbol)
        tracker = _quote_trackers[symbol]

        qr = conn.execute(
            "SELECT price, timestamp FROM live_quotes WHERE symbol=? ORDER BY timestamp DESC LIMIT 1",
            (symbol,)).fetchone()
        if qr and qr["price"]:
            quote = tracker.receive(
                float(qr["price"]),
                source_timestamp=qr["timestamp"],
                source="live_quotes",
            )
            return jsonify({
                "symbol": symbol,
                "price": quote["current_price"],
                "price_change": quote["price_change"],
                "previous_price": quote["previous_price"],
                "quote_received_at": quote["quote_received_at"],
                "source_timestamp": quote["source_timestamp"],
                "source": quote["source"],
                "update_interval_ms": quote["update_interval_ms"],
                "quote_age_ms": quote["quote_age_ms"],
            })
        return jsonify({"symbol": symbol, "price": None, "source": "no_data"})
    except Exception as e:
        return error_response("INTERNAL_ERROR", str(e), 500)
    finally:
        conn.close()


@app.route("/api/journal", methods=["POST"])
@limiter.limit("30/minute")
def journal_create():
    """Create a new trade journal entry."""
    body = request.get_json(silent=True) or {}
    required = ["date", "instrument", "user_action"]
    missing = [f for f in required if f not in body]
    if missing:
        return error_response("INVALID_REQUEST", f"Missing: {', '.join(missing)}", 400)
    try:
        from journal import insert_journal
        record = insert_journal(
            date=str(body["date"]),
            instrument=str(body["instrument"]).upper(),
            strategy=str(body.get("strategy", "")) or None,
            direction=str(body.get("direction", "")).upper() or None,
            planned_entry=float(body["planned_entry"]) if body.get("planned_entry") is not None else None,
            actual_entry=float(body.get("actual_entry")) if body.get("actual_entry") is not None else None,
            stop=float(body.get("stop")) if body.get("stop") is not None else None,
            target=float(body.get("target")) if body.get("target") is not None else None,
            actual_exit=float(body.get("actual_exit")) if body.get("actual_exit") is not None else None,
            quantity=int(body["quantity"]) if body.get("quantity") is not None else None,
            risk_planned=float(body.get("risk_planned")) if body.get("risk_planned") is not None else None,
            risk_actual=float(body.get("risk_actual")) if body.get("risk_actual") is not None else None,
            market_regime=str(body.get("market_regime", "")) or None,
            tradingai_evidence_score=float(body["tradingai_evidence_score"]) if body.get("tradingai_evidence_score") is not None else None,
            tradingai_confidence=float(body.get("tradingai_confidence")) if body.get("tradingai_confidence") is not None else None,
            user_action=str(body["user_action"]).upper(),
            user_reason=str(body.get("user_reason", "")) or None,
            result=str(body.get("result", "")) or None,
            mistake=str(body.get("mistake", "")) or None,
            notes=str(body.get("notes", "")) or None,
            tradingai_setup_id=str(body.get("tradingai_setup_id", "")) or None,
        )
        return jsonify({
            "journal_id": record.journal_id,
            "tradingai_setup_id": record.tradingai_setup_id,
            "date": record.date,
            "instrument": record.instrument,
            "user_action": record.user_action,
            "created_at": record.created_at,
        }), 201
    except Exception as e:
        return error_response("JOURNAL_CREATE_FAILED", str(e), 500)


@app.route("/api/journal/<journal_id>", methods=["GET"])
@limiter.limit("60/minute")
def journal_get(journal_id):
    """Get a trade journal entry by ID."""
    try:
        from journal import get_journal
        record = get_journal(journal_id)
        if record is None:
            return error_response("NOT_FOUND", f"Journal {journal_id} not found", 404)
        return jsonify({
            "journal_id": record.journal_id,
            "tradingai_setup_id": record.tradingai_setup_id,
            "date": record.date,
            "instrument": record.instrument,
            "strategy": record.strategy,
            "direction": record.direction,
            "planned_entry": record.planned_entry,
            "actual_entry": record.actual_entry,
            "stop": record.stop,
            "target": record.target,
            "actual_exit": record.actual_exit,
            "quantity": record.quantity,
            "risk_planned": record.risk_planned,
            "risk_actual": record.risk_actual,
            "market_regime": record.market_regime,
            "tradingai_evidence_score": record.tradingai_evidence_score,
            "tradingai_confidence": record.tradingai_confidence,
            "user_action": record.user_action,
            "user_reason": record.user_reason,
            "result": record.result,
            "mistake": record.mistake,
            "notes": record.notes,
            "created_at": record.created_at,
            "updated_at": record.updated_at,
        })
    except Exception as e:
        return error_response("JOURNAL_GET_FAILED", str(e), 500)


@app.route("/api/journal", methods=["GET"])
@limiter.limit("60/minute")
def journal_list():
    """List trade journal entries with filters."""
    instrument = request.args.get("instrument")
    date_from = request.args.get("date_from")
    date_to = request.args.get("date_to")
    user_action = request.args.get("user_action")
    limit = min(int(request.args.get("limit", 50)), 100)
    offset = int(request.args.get("offset", 0))
    try:
        from journal import list_journals
        records = list_journals(
            instrument=instrument, date_from=date_from, date_to=date_to,
            user_action=user_action, limit=limit, offset=offset,
        )
        return jsonify({
            "total": len(records),
            "limit": limit,
            "offset": offset,
            "entries": [{
                "journal_id": r.journal_id,
                "tradingai_setup_id": r.tradingai_setup_id,
                "date": r.date,
                "instrument": r.instrument,
                "strategy": r.strategy,
                "direction": r.direction,
                "user_action": r.user_action,
                "result": r.result,
                "notes": r.notes,
                "created_at": r.created_at,
            } for r in records],
        })
    except Exception as e:
        return error_response("JOURNAL_LIST_FAILED", str(e), 500)


@app.route("/api/journal/<journal_id>/update", methods=["POST"])
@limiter.limit("30/minute")
def journal_update(journal_id):
    """Update mutable journal fields (notes, mistake, user_action, user_reason).

    Core trade fields are immutable. Updates create audit events.
    """
    body = request.get_json(silent=True) or {}
    allowed = {"notes", "mistake", "user_action", "user_reason"}
    if not any(k in body for k in allowed):
        return error_response("INVALID_REQUEST", f"Allowed fields: {', '.join(allowed)}", 400)
    try:
        from journal import update_journal_notes, get_journal
        existing = get_journal(journal_id)
        if existing is None:
            return error_response("NOT_FOUND", f"Journal {journal_id} not found", 404)
        record = update_journal_notes(
            journal_id,
            notes=body.get("notes", existing.notes),
            mistake=body.get("mistake", existing.mistake),
            user_action=body.get("user_action", existing.user_action),
            user_reason=body.get("user_reason", existing.user_reason),
        )
        return jsonify({
            "journal_id": record.journal_id,
            "user_action": record.user_action,
            "notes": record.notes,
            "mistake": record.mistake,
            "updated_at": record.updated_at,
        })
    except Exception as e:
        return error_response("JOURNAL_UPDATE_FAILED", str(e), 500)


@app.route("/api/journal/<journal_id>/events", methods=["GET"])
@limiter.limit("60/minute")
def journal_events(journal_id):
    """Get audit events for a journal entry."""
    try:
        from journal import get_events
        events = get_events(journal_id)
        return jsonify({
            "journal_id": journal_id,
            "total_events": len(events),
            "events": [{
                "event_id": e.event_id,
                "event_type": e.event_type,
                "field_name": e.field_name,
                "old_value": e.old_value,
                "new_value": e.new_value,
                "created_at": e.created_at,
            } for e in events],
        })
    except Exception as e:
        return error_response("JOURNAL_EVENTS_FAILED", str(e), 500)


@app.route("/api/journal/<journal_id>/compare", methods=["GET"])
@limiter.limit("30/minute")
def journal_compare(journal_id):
    """TradingAI plan vs actual trader action comparison."""
    try:
        from journal import get_comparison
        comparison = get_comparison(journal_id)
        if comparison is None:
            return error_response("NOT_FOUND", f"Journal {journal_id} not found", 404)
        return jsonify(comparison)
    except Exception as e:
        return error_response("JOURNAL_COMPARE_FAILED", str(e), 500)


@app.route("/api/journal/stats", methods=["GET"])
@limiter.limit("30/minute")
def journal_stats():
    """Deterministic statistics. Returns INSUFFICIENT_DATA if sample < 10."""
    instrument = request.args.get("instrument")
    strategy = request.args.get("strategy")
    date_from = request.args.get("date_from")
    date_to = request.args.get("date_to")
    try:
        from journal import get_deterministic_stats
        stats = get_deterministic_stats(
            instrument=instrument, strategy=strategy,
            date_from=date_from, date_to=date_to,
        )
        return jsonify(stats)
    except Exception as e:
        return error_response("JOURNAL_STATS_FAILED", str(e), 500)


@app.route("/api/journal/feedback", methods=["POST"])
@limiter.limit("30/minute")
def journal_feedback():
    """Add feedback to a journal entry."""
    body = request.get_json(silent=True) or {}
    if "journal_id" not in body or "rating" not in body:
        return error_response("INVALID_REQUEST", "journal_id and rating required", 400)
    try:
        from journal import add_feedback
        feedback = add_feedback(
            journal_id=str(body["journal_id"]),
            rating=int(body["rating"]),
            category=str(body.get("category", "")) or None,
            comment=str(body.get("comment", "")) or None,
        )
        if feedback is None:
            return error_response("NOT_FOUND", "Journal not found", 404)
        return jsonify({
            "feedback_id": feedback.feedback_id,
            "journal_id": feedback.journal_id,
            "rating": feedback.rating,
            "category": feedback.category,
            "created_at": feedback.created_at,
        }), 201
    except Exception as e:
        return error_response("FEEDBACK_FAILED", str(e), 500)


@app.route("/api/intelligence/summary", methods=["GET"])
@limiter.limit("30/minute")
def pi_summary():
    """Trading Intelligence Summary."""
    date_from = request.args.get("date_from")
    date_to = request.args.get("date_to")
    try:
        from personal_intelligence import intelligence_summary
        return jsonify(intelligence_summary(
            date_from=date_from or None, date_to=date_to or None,
        ))
    except Exception as e:
        return error_response("PI_SUMMARY_FAILED", str(e), 500)


@app.route("/api/intelligence/instrument/<symbol>", methods=["GET"])
@limiter.limit("30/minute")
def pi_instrument(symbol):
    """Per-Instrument Analysis."""
    try:
        from personal_intelligence import intelligence_instrument
        return jsonify(intelligence_instrument(symbol.upper()))
    except Exception as e:
        return error_response("PI_INSTRUMENT_FAILED", str(e), 500)


@app.route("/api/intelligence/strategy/<name>", methods=["GET"])
@limiter.limit("30/minute")
def pi_strategy(name):
    """Per-Strategy Analysis."""
    try:
        from personal_intelligence import intelligence_strategy
        return jsonify(intelligence_strategy(name))
    except Exception as e:
        return error_response("PI_STRATEGY_FAILED", str(e), 500)


@app.route("/api/intelligence/regime/<name>", methods=["GET"])
@limiter.limit("30/minute")
def pi_regime(name):
    """Market Regime Analysis."""
    try:
        from personal_intelligence import intelligence_regime
        return jsonify(intelligence_regime(name.upper()))
    except Exception as e:
        return error_response("PI_REGIME_FAILED", str(e), 500)


@app.route("/api/intelligence/behavior", methods=["GET"])
@limiter.limit("30/minute")
def pi_behavior():
    """Behavior Analysis."""
    try:
        from personal_intelligence import intelligence_behavior
        return jsonify(intelligence_behavior())
    except Exception as e:
        return error_response("PI_BEHAVIOR_FAILED", str(e), 500)


@app.route("/api/intelligence/mistakes", methods=["GET"])
@limiter.limit("30/minute")
def pi_mistakes():
    """Recurring Mistake Patterns."""
    try:
        from personal_intelligence import intelligence_mistakes
        return jsonify(intelligence_mistakes())
    except Exception as e:
        return error_response("PI_MISTAKES_FAILED", str(e), 500)


@app.route("/api/intelligence/setup-adherence", methods=["GET"])
@limiter.limit("30/minute")
def pi_setup_adherence():
    """Setup Adherence."""
    try:
        from personal_intelligence import intelligence_setup_adherence
        return jsonify(intelligence_setup_adherence())
    except Exception as e:
        return error_response("PI_SETUP_ADHERENCE_FAILED", str(e), 500)


@app.route("/api/key-levels")
@cache_page(60)
def key_levels():
    """Key Levels: support, resistance, opening range for a symbol.

    Reuses market_state.build_market_state() — no duplicate calculation.
    """
    symbol = request.args.get("symbol", "").upper()
    if not symbol:
        return error_response("SYMBOL_REQUIRED", "A symbol parameter is required", 400)
    conn = get_db()
    try:
        from market_state import build_market_state
        state = build_market_state(symbol, conn)
        if state is None:
            return jsonify({
                "symbol": symbol,
                "supports": [],
                "resistances": [],
                "opening_range": None,
                "data_state": "UNAVAILABLE",
                "message": "Insufficient market data to compute key levels",
            }), 200
        supports = list(state.support or [])
        resistances = list(state.resistance or [])
        opening_range = None
        ind = state.indicators or {}
        if ind.get("day_open") and ind.get("prev_day_close"):
            try:
                opening_range = {
                    "low": min(float(ind["day_open"]), float(ind["prev_day_close"])),
                    "high": max(float(ind["day_open"]), float(ind["prev_day_close"])),
                }
            except (TypeError, ValueError):
                opening_range = None
        return jsonify({
            "symbol": symbol,
            "supports": supports,
            "resistances": resistances,
            "opening_range": opening_range,
            "timestamp": state.timestamp,
            "data_state": "LIVE",
        }), 200
    except Exception as e:
        return error_response("INTERNAL_ERROR", str(e), 500)
    finally:
        conn.close()


@app.route("/api/intraday-conditions")
@cache_page(60)
def intraday_conditions():
    """Intraday Conditions: bullish, bearish, no-trade conditions for a symbol.

    Reuses regime data from build_market_state and RegimeEngine — no duplicate calculation.
    Conditions are derived from observed indicators (RSI, MACD, regime, VIX).
    """
    symbol = request.args.get("symbol", "").upper()
    if not symbol:
        return error_response("SYMBOL_REQUIRED", "A symbol parameter is required", 400)
    conn = get_db()
    try:
        from market_state import build_market_state
        from regime import RegimeEngine
        state = build_market_state(symbol, conn)
        if state is None:
            return jsonify({
                "symbol": symbol,
                "bullish": None,
                "bearish": None,
                "no_trade": None,
                "data_state": "UNAVAILABLE",
                "message": "Insufficient market data to determine conditions",
            }), 200
        ind = state.indicators or {}
        regime = state.regime or {}
        regime_name = regime.get("regime", "UNKNOWN") if isinstance(regime, dict) else regime
        confidence = regime.get("confidence", 0) if isinstance(regime, dict) else 0
        rsi = ind.get("rsi")
        macd = ind.get("macd")
        vix = ind.get("vix") or (state.snapshot or {}).get("vix")

        bullish = None
        bearish = None
        no_trade = None

        if regime_name == "BULLISH" and rsi is not None and rsi < 70 and macd is not None and macd > 0:
            bullish = f"Trend intact ({regime_name}, RSI {rsi:.0f}, MACD positive). Scale into positions on dips."
            no_trade = f"Avoid new positions if RSI exceeds 70 or MACD turns negative."
        elif regime_name == "BEARISH" and rsi is not None and rsi > 30 and macd is not None and macd < 0:
            bearish = f"Downward pressure confirmed ({regime_name}, RSI {rsi:.0f}, MACD negative). Use defined-risk strategies."
            no_trade = f"No trades in uncertain or sideways regimes. Wait for confirmation."
        else:
            no_trade = f"Market regime is {regime_name}. Wait for clear trend confirmation before entering positions."
            if vix is not None and vix > 20:
                no_trade += f" VIX elevated at {vix:.1f}."

        return jsonify({
            "symbol": symbol,
            "bullish": bullish,
            "bearish": bearish,
            "no_trade": no_trade,
            "regime": regime_name,
            "confidence": confidence,
            "timestamp": state.timestamp,
            "data_state": "LIVE",
        }), 200
    except Exception as e:
        return error_response("INTERNAL_ERROR", str(e), 500)
    finally:
        conn.close()


@app.route("/api/risk/<symbol>")
@cache_page(60)
def risk_endpoint(symbol):
    """Risk guidance: max risk, recommended position size, warnings for a symbol.

    Reuses trade_lifecycle.detect_trade_setup() — no duplicate calculation.
    """
    symbol = symbol.upper()
    if symbol not in ("NIFTY", "BANKNIFTY", "SENSEX"):
        return error_response("NOT_SUPPORTED", f"{symbol} is not available", 404)
    conn = get_db()
    try:
        from trade_lifecycle import detect_trade_setup
        from market_state import build_market_state
        market_state = build_market_state(symbol, conn)
        if market_state is None:
            return jsonify({
                "symbol": symbol,
                "max_risk": "1% of capital",
                "recommended_size": None,
                "warnings": ["Market state unavailable: cannot compute risk. Data pending backend verification."],
                "data_state": "UNAVAILABLE",
            }), 200
        ind = market_state.indicators or {}
        prev_close = ind.get("prev_day_close")
        day_open = ind.get("day_open")
        spot = market_state.snapshot.get("spot") if market_state.snapshot else None
        if not spot and day_open:
            spot = day_open
        if not prev_close:
            row = conn.execute(
                "SELECT close FROM price_1d WHERE symbol=? ORDER BY timestamp DESC LIMIT 1", (symbol,)
            ).fetchone()
            if row:
                prev_close = row["close"]
        gap = None
        if day_open and prev_close:
            try:
                gap = {
                    "gap_pct": round((float(day_open) - float(prev_close)) / float(prev_close) * 100, 2),
                    "open": float(day_open),
                    "prev_close": float(prev_close),
                }
            except (TypeError, ValueError):
                gap = None
        options_state = None
        try:
            rows = conn.execute(
                "SELECT strike, option_type, open_interest, implied_volatility FROM option_chain WHERE symbol=? ORDER BY strike",
                (symbol,),
            ).fetchall()
            if rows:
                options_state = {"chain": [dict(r) for r in rows]}
        except Exception:
            pass
        setup = detect_trade_setup(
            symbol=symbol,
            market_state={
                "spot": spot,
                "regime": market_state.regime,
                "confidence": market_state.regime.get("confidence", 0) if isinstance(market_state.regime, dict) else 0,
                "indicators": ind,
            },
            options_state=options_state,
            gap=gap,
            timestamp=market_state.timestamp or "",
        )
        stages = setup.stages if hasattr(setup, "stages") else {}
        warnings = []
        for stage_name, stage in stages.items():
            if stage.status == "WAIT":
                warnings.append(stage.reason or f"{stage_name}: conditions not ready.")
            elif stage.status == "NO_SETUP":
                warnings.append(f"No trade warranted at this time ({stage_name}).")
        max_risk = "1% of capital"
        if getattr(setup, "max_risk", None):
            max_risk = setup.max_risk
        recommended_size = getattr(setup, "recommended_size", None)
        return jsonify({
            "symbol": symbol,
            "max_risk": max_risk,
            "recommended_size": recommended_size,
            "warnings": warnings if warnings else ["No active warnings."],
            "data_state": "LIVE",
            "timestamp": market_state.timestamp or "",
        }), 200
    except Exception as e:
        return error_response("INTERNAL_ERROR", str(e), 500)
    finally:
        conn.close()


@app.route("/api/session-timeline")
@cache_page(5)
def session_timeline():
    """Session Timeline: PRE_MARKET, OPEN, LIVE, CLOSED, POST_MARKET states.

    Computed from market hours (9:30 AM - 3:30 PM IST). No external dependency.
    """
    from datetime import datetime, timezone, timedelta
    now_utc = datetime.now(timezone.utc)
    try:
        ist_now = now_utc + timedelta(hours=5, minutes=30)
    except Exception:
        ist_now = now_utc
    hour = ist_now.hour
    minute = ist_now.minute
    mins = hour * 60 + minute
    is_weekday = ist_now.weekday() < 5

    pre_market = "PRE-MARKET: Prepare. Review overnight news, global markets, and pre-market ranges."
    open_market = "OPEN: Market opened at 9:30 AM IST. First 15 minutes are high-volatility."
    trading_hours = "LIVE: Active trading session. Monitor positions and adjust as needed."
    close = "CLOSED: Market closed at 3:30 PM IST. Review positions and plan for next session."
    post_market = "POST-MARKET: After-hours analysis. Review daily outcomes and prepare for next day."

    if not is_weekday:
        state = "CLOSED"
        state_desc = "Market closed — Weekend. No trading activity."
    elif mins < 570:
        state = "PRE_MARKET"
        mins_to_open = 570 - mins
        state_desc = f"PRE-MARKET: {mins_to_open} minutes until market open."
    elif mins < 990:
        state = "OPEN"
        state_desc = open_market
    elif mins < 1200:
        state = "LIVE"
        mins_to_close = 1200 - mins
        state_desc = f"LIVE: {mins_to_close} minutes until market close."
    elif mins < 1230:
        state = "CLOSED"
        state_desc = close
    else:
        state = "POST_MARKET"
        state_desc = post_market

    return jsonify({
        "state": state,
        "description": state_desc,
        "pre_market": pre_market,
        "open_market": open_market,
        "trading_hours": trading_hours,
        "close": close,
        "post_market": post_market,
        "ist_time": ist_now.strftime("%H:%M:%S IST"),
        "ist_date": ist_now.strftime("%d %b %Y"),
        "timestamp": now_utc.isoformat(),
        "data_state": "LIVE",
    }), 200


@app.route("/api/outlook/5m/latest/<symbol>", methods=["GET"])
@limiter.limit("30/minute")
def api_outlook_5m_latest(symbol):
    from outlook_change_detector import evaluate, needs_ai_outlook
    try:
        result = evaluate(symbol)
        ai_needs = needs_ai_outlook(symbol)
        return jsonify({
            "success": True,
            "data": {
                **result,
                "ai_outlook_available": not ai_needs["needs_ai"],
            },
        }), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/outlook/5m/timeline/<symbol>", methods=["GET"])
@limiter.limit("30/minute")
def api_outlook_5m_timeline(symbol):
    from db_schema import DB_PATH
    import sqlite3
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        page = request.args.get("page", 1, type=int)
        per_page = request.args.get("per_page", 20, type=int)
        offset = (page - 1) * per_page

        total = conn.execute(
            "SELECT COUNT(*) FROM ai_outlooks_5m WHERE instrument=?", (symbol,)
        ).fetchone()[0]

        rows = conn.execute(
            "SELECT * FROM ai_outlooks_5m WHERE instrument=? ORDER BY generated_at DESC LIMIT ? OFFSET ?",
            (symbol, per_page, offset),
        ).fetchall()

        outlooks = []
        for r in rows:
            d = dict(r)
            for f in ("evidence_json", "watch_levels_json", "confirmation_json", "invalidation_json", "risk_json", "material_changes_json"):
                try:
                    d[f] = json.loads(d.get(f) or "[]")
                except (json.JSONDecodeError, TypeError):
                    d[f] = []
            outlooks.append(d)

        return jsonify({
            "success": True,
            "data": {
                "outlooks": outlooks,
                "pagination": {"page": page, "per_page": per_page, "total": total},
            },
        }), 200
    finally:
        conn.close()


@app.route("/api/outlook/5m/snapshot/<symbol>", methods=["GET"])
@limiter.limit("30/minute")
def api_outlook_5m_snapshot(symbol):
    from db_schema import DB_PATH
    import sqlite3
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT * FROM market_snapshots_5m WHERE symbol=? ORDER BY candle_timestamp DESC LIMIT 1",
            (symbol,),
        ).fetchone()
        if not row:
            return jsonify({"success": True, "data": {"snapshot": None, "data_state": "NO_DATA"}}), 200
        d = dict(row)
        return jsonify({"success": True, "data": {"snapshot": d, "data_state": "LIVE"}}), 200
    finally:
        conn.close()


@app.route("/api/outlook/5m/changes/<symbol>", methods=["GET"])
@limiter.limit("30/minute")
def api_outlook_5m_changes(symbol):
    from outlook_change_detector import evaluate
    try:
        result = evaluate(symbol)
        return jsonify({"success": True, "data": result}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/ai-outlook/<symbol>", methods=["GET"])
@limiter.limit("30/minute")
def api_ai_outlook(symbol):
    from db_schema import DB_PATH
    from outlook_scheduler import is_market_open, get_current_candle_timestamp
    import sqlite3, json
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        market_status = is_market_open()
        current_ts = get_current_candle_timestamp()

        row = conn.execute(
            "SELECT * FROM ai_outlooks_5m WHERE instrument=? ORDER BY generated_at DESC LIMIT 1",
            (symbol,),
        ).fetchone()
        current = dict(row) if row else None

        if current:
            for f in ("evidence_json", "watch_levels_json", "confirmation_json", "invalidation_json", "risk_json", "material_changes_json"):
                try:
                    current[f] = json.loads(current.get(f) or "[]")
                except (json.JSONDecodeError, TypeError):
                    current[f] = []
            generated_dt = datetime.fromisoformat(current["generated_at"].replace("Z", "+00:00"))
            age_seconds = (datetime.now(timezone.utc) - generated_dt).total_seconds()
            current["age_seconds"] = round(age_seconds)
            current["age_minutes"] = round(age_seconds / 60)
            if age_seconds > MAX_OUTLOOK_AGE_MINUTES * 60:
                current["age_status"] = "STALE"
            elif age_seconds > OUTLOOK_AGE_WARN_MINUTES * 60:
                current["age_status"] = "AGING"
            else:
                current["age_status"] = "FRESH"
        else:
            current = {"data_state": "NO_OUTLOOK", "age_status": "NO_OUTLOOK"}

        prev_row = conn.execute(
            "SELECT * FROM ai_outlooks_5m WHERE instrument=? AND generated_at < ? ORDER BY generated_at DESC LIMIT 1",
            (symbol, row["generated_at"] if row else "1970-01-01T00:00:00Z"),
        ).fetchone()
        previous = dict(prev_row) if prev_row else None

        timeline = []
        tl_rows = conn.execute(
            "SELECT * FROM ai_outlooks_5m WHERE instrument=? ORDER BY generated_at DESC LIMIT 20",
            (symbol,),
        ).fetchall()
        for r in tl_rows:
            d = dict(r)
            for f in ("evidence_json", "watch_levels_json", "confirmation_json", "invalidation_json", "risk_json"):
                try:
                    d[f] = json.loads(d.get(f) or "[]")
                except (json.JSONDecodeError, TypeError):
                    d[f] = []
            timeline.append(d)

        data_state = market_status.get("session", "CLOSED")
        if not current or current.get("data_state") == "NO_OUTLOOK":
            data_state = "UNAVAILABLE"
        elif market_status.get("session") == "CLOSED":
            data_state = "DELAYED"

        return jsonify({
            "success": True,
            "data": {
                "instrument": symbol,
                "current": current,
                "previous": previous,
                "change": None if not previous else {
                    "bias_changed": previous.get("bias") != (current or {}).get("bias"),
                    "confidence_changed": previous.get("confidence") != (current or {}).get("confidence"),
                    "regime_changed": previous.get("market_regime") != (current or {}).get("market_regime"),
                    "trade_state_changed": previous.get("trade_state") != (current or {}).get("trade_state"),
                },
                "timeline": timeline,
                "data_state": data_state,
                "market_status": market_status,
                "current_candle": current_ts,
            },
        }), 200
    finally:
        conn.close()


@app.route("/api/ai-outlook/timeline/<symbol>", methods=["GET"])
@limiter.limit("30/minute")
def api_ai_outlook_timeline(symbol):
    from db_schema import DB_PATH
    import sqlite3, json
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        page = request.args.get("page", 1, type=int)
        per_page = request.args.get("per_page", 20, type=int)
        offset = (page - 1) * per_page

        total = conn.execute(
            "SELECT COUNT(*) FROM ai_outlooks_5m WHERE instrument=?", (symbol,)
        ).fetchone()[0]

        rows = conn.execute(
            "SELECT * FROM ai_outlooks_5m WHERE instrument=? ORDER BY generated_at DESC LIMIT ? OFFSET ?",
            (symbol, per_page, offset),
        ).fetchall()

        outlooks = []
        for r in rows:
            d = dict(r)
            for f in ("evidence_json", "watch_levels_json", "confirmation_json", "invalidation_json", "risk_json", "material_changes_json"):
                try:
                    d[f] = json.loads(d.get(f) or "[]")
                except (json.JSONDecodeError, TypeError):
                    d[f] = []
            outlooks.append(d)

        return jsonify({
            "success": True,
            "data": {
                "instrument": symbol,
                "outlooks": outlooks,
                "pagination": {"page": page, "per_page": per_page, "total": total},
            },
        }), 200
    finally:
        conn.close()


@app.route("/api/ai-outlook/scheduler", methods=["GET"])
@limiter.limit("10/minute")
def api_ai_outlook_scheduler():
    from outlook_scheduler import is_market_open, get_current_candle_timestamp, run_scheduler
    from db_schema import DB_PATH
    import sqlite3

    market_status = is_market_open()
    current_candle = get_current_candle_timestamp()

    result = {"dry_run": True}
    try:
        result = run_scheduler(dry_run=True)
    except Exception as e:
        result = {"dry_run": True, "error": str(e)}

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        snapshot_count = conn.execute(
            "SELECT COUNT(*) FROM market_snapshots_5m WHERE candle_timestamp=?",
            (current_candle,) if current_candle else ("",),
        ).fetchone()[0]
        outlook_count = conn.execute(
            "SELECT COUNT(*) FROM ai_outlooks_5m WHERE instrument='NIFTY'",
        ).fetchone()[0]
    finally:
        conn.close()

    return jsonify({
        "success": True,
        "data": {
            "market_status": market_status,
            "current_candle": current_candle,
            "scheduler_dry_run": result,
            "stats": {
                "snapshots_current_candle": snapshot_count,
                "total_outlooks_nifty": outlook_count,
            },
        },
    }), 200


@app.route("/api/outlook/5m/outcome", methods=["POST"])
@limiter.limit("30/minute")
def api_outlook_5m_outcome():
    data = request.get_json(silent=True) or {}
    outlook_id = data.get("outlook_id")
    symbol = data.get("symbol", "NIFTY")
    horizon_minutes = data.get("horizon_minutes", 5)
    entry_price = data.get("entry_price")

    from outcome_engine import OutcomeEngine
    engine = OutcomeEngine()

    if outlook_id:
        result = engine.record_outcome(outlook_id, symbol, entry_price, horizon_minutes)
        return jsonify({"success": True, "data": result}), 200

    pending = engine.get_pending_evaluations()
    evaluated = []
    for p in pending:
        ev = engine.evaluate_outcome(p["outlook_id"], p["symbol"], p["horizon_minutes"])
        if ev:
            evaluated.append(ev)
    return jsonify({"success": True, "data": {"pending": pending, "evaluated": evaluated}}), 200


if __name__ == "__main__":
    port = int(os.environ.get("API_PORT", 8000))
    app.run(host="0.0.0.0", port=port, debug=False)
