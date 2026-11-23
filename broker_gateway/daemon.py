#!/usr/bin/env python3
"""Root-owned Unix-socket gateway. Scanners call this; secrets never leave it."""
from __future__ import annotations

import datetime as dt
import grp
import json
import math
import os
import pathlib
import socketserver
import sys
import threading
import time
import traceback

from broker_gateway import __version__
from broker_gateway.adapters import available_brokers, get_adapter
from broker_gateway.errors import BrokerCallFailed, BrokerGatewayError

SOCKET_PATH = os.environ.get("BROKER_GATEWAY_SOCKET", "/run/tradingai/broker_gateway.sock")
SOCKET_GROUP = os.environ.get("BROKER_GATEWAY_GROUP", "ubuntu")
METHODS = {"instruments", "quote", "historical_data", "profile"}
_ADAPTERS: dict[str, object] = {}
_LOCK = threading.Lock()
_MAX_CALLS = max(1, int(os.environ.get("BROKER_GATEWAY_MAX_CALLS", "4")))
_CALL_LIMIT = threading.BoundedSemaphore(_MAX_CALLS)
_FRESH_TTL = float(os.environ.get("BROKER_GATEWAY_FRESH_TTL", "300"))
# A failed validation is cached briefly so a stale token cannot make eight
# scanners hammer the broker's profile endpoint every 5 s. Credential changes
# bypass this cache immediately (signature check happens first).
_FRESH_NEG_TTL = float(os.environ.get("BROKER_GATEWAY_FRESH_NEG_TTL", "30"))
_FRESH_CACHE: dict[str, tuple[object, float, bool]] = {}
_FRESH_ERROR: dict[str, str] = {}
_FRESH_LOCK = threading.Lock()
_FRESH_LOCKS: dict[str, threading.Lock] = {}

# Quote freshness. A broker that publishes a trade timestamp lets us reject a
# stale last_price during live hours. Brokers whose quote endpoint omits a
# timestamp (mStock) are fetched live on every call, so they are treated as
# fresh and still expose ``age_seconds = 0`` for observability.
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
_QUOTE_MAX_AGE = float(os.environ.get("BROKER_GATEWAY_QUOTE_MAX_AGE", "300"))
_MARKET_OPEN = dt.time(9, 0)
_MARKET_CLOSE = dt.time(15, 30)


class GatewayEncoder(json.JSONEncoder):
    def default(self, obj):
        if hasattr(obj, "isoformat"):
            return obj.isoformat()
        return super().default(obj)


def _adapter(name: str):
    with _LOCK:
        if name not in _ADAPTERS:
            _ADAPTERS[name] = get_adapter(name)
        return _ADAPTERS[name]


def _broker_lock(broker: str) -> threading.Lock:
    with _FRESH_LOCK:
        return _FRESH_LOCKS.setdefault(broker, threading.Lock())


def _cached_freshness(broker: str, signature, now: float) -> str | None:
    """Return 'ok'/'failed' when a cached decision still applies, else None.

    A changed credential signature never matches, so a token refresh is adopted
    immediately even if the previous signature had failed validation.
    """
    with _FRESH_LOCK:
        cached = _FRESH_CACHE.get(broker)
    if not cached or cached[0] != signature:
        return None
    age = now - cached[1]
    if cached[2] and age < _FRESH_TTL:
        return "ok"
    if not cached[2] and age < _FRESH_NEG_TTL:
        return "failed"
    return None


def _require_fresh(broker: str, adapter) -> None:
    """Use only the latest, validated token for the selected broker."""
    signature = adapter.credential_signature()
    decision = _cached_freshness(broker, signature, time.monotonic())
    if decision == "ok":
        return
    if decision == "failed":
        with _FRESH_LOCK:
            message = _FRESH_ERROR.get(broker, f"{broker} token is stale or invalid")
        raise BrokerCallFailed(message)

    with _broker_lock(broker):
        now = time.monotonic()
        decision = _cached_freshness(broker, signature, now)
        if decision == "ok":
            return
        if decision == "failed":
            with _FRESH_LOCK:
                message = _FRESH_ERROR.get(broker, f"{broker} token is stale or invalid")
            raise BrokerCallFailed(message)
        try:
            adapter.validate_credentials()
        except Exception as exc:
            message = (
                f"{broker} token is stale or invalid; refresh it before trading: {exc}"
            )
            with _FRESH_LOCK:
                _FRESH_CACHE[broker] = (signature, now, False)
                _FRESH_ERROR[broker] = message
            raise BrokerCallFailed(message) from exc
        with _FRESH_LOCK:
            _FRESH_CACHE[broker] = (signature, now, True)
            _FRESH_ERROR.pop(broker, None)


def _quote_age_seconds(entry: dict, now: dt.datetime) -> float:
    """Age of a quote from its broker-supplied trade timestamp (0 if absent)."""
    ts = entry.get("last_trade_time")
    if ts is None:
        return 0.0
    try:
        if isinstance(ts, dt.datetime):
            when = ts
        elif isinstance(ts, (int, float)):
            return max(0.0, now.timestamp() - float(ts))
        elif isinstance(ts, str):
            when = dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
        else:
            return 0.0
        if when.tzinfo is None:
            when = when.replace(tzinfo=IST)
        return max(0.0, (now - when).total_seconds())
    except (ValueError, TypeError, OverflowError):
        return 0.0


def _live_market(now: dt.datetime) -> bool:
    local = now.astimezone(IST)
    return local.weekday() < 5 and _MARKET_OPEN <= local.time() <= _MARKET_CLOSE


def _sanitize_quote(result, now=None):
    """Strip invalid, nonpositive or stale ``last_price`` values.

    Paper scanners do ``float(quote[symbol]["last_price"])``. A zero, negative,
    non-finite or (during live hours) stale price would otherwise be accepted
    and could produce bogus paper entries or stop-loss exits. Removing the key
    makes that lookup raise ``KeyError``, which every scanner already handles
    as "LTP unavailable" and skips the option for that poll. Applies to every
    broker at the daemon boundary, so scanner code stays unchanged when
    switching brokers. Every quote also gets ``age_seconds`` and a normalized
    ``last_trade_time`` (None when the broker does not publish one).
    """
    if not isinstance(result, dict):
        return result
    now = now or dt.datetime.now(dt.timezone.utc)
    live = _live_market(now)
    clean = {}
    for symbol, entry in result.items():
        if not isinstance(entry, dict):
            clean[symbol] = entry
            continue
        clean_entry = dict(entry)
        age = _quote_age_seconds(entry, now)
        clean_entry["age_seconds"] = round(age, 1)
        clean_entry.setdefault("last_trade_time", None)
        raw = entry.get("last_price")
        try:
            price = float(raw)
            valid = math.isfinite(price) and price > 0
        except (TypeError, ValueError):
            valid = False
        if not valid or (live and age > _QUOTE_MAX_AGE):
            clean_entry.pop("last_price", None)
        clean[symbol] = clean_entry
    return clean


def dispatch(request: dict):
    if not isinstance(request, dict):
        raise BrokerGatewayError("request must be an object")
    broker = str(request.get("broker", "")).strip().lower()
    method = str(request.get("method", "")).strip()
    params = request.get("params") or {}
    if broker not in available_brokers():
        raise BrokerGatewayError(f"unknown broker {broker!r}")
    if method not in METHODS:
        raise BrokerGatewayError(f"method not allowed: {method!r}")
    if not isinstance(params, dict):
        raise BrokerGatewayError("params must be an object")
    adapter = _adapter(broker)
    adapter.refresh_credentials_if_changed()
    _require_fresh(broker, adapter)
    func = getattr(adapter, method)
    with _CALL_LIMIT:
        result = func(**params)
    return _sanitize_quote(result) if method == "quote" else result


class Handler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        try:
            raw = self.rfile.readline()
            if not raw:
                return
            request = json.loads(raw.decode("utf-8"))
            result = dispatch(request)
            response = {"ok": True, "result": result, "version": __version__}
        except Exception as exc:
            traceback.print_exc(file=sys.stderr)
            response = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        payload = (json.dumps(response, cls=GatewayEncoder) + "\n").encode("utf-8")
        self.wfile.write(payload)
        self.wfile.flush()


class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True
    allow_reuse_address = True
    # Ten scanners reconnect at once after a deploy. socketserver's default
    # backlog of 5 overflows and clients get EAGAIN on connect, so keep a
    # generous queue while threads are being spawned.
    request_queue_size = 128


def main() -> int:
    path = pathlib.Path(SOCKET_PATH)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
    try:
        gid = grp.getgrnam(SOCKET_GROUP).gr_gid
    except KeyError:
        gid = os.getgid()
    os.chown(str(path.parent), 0, gid)
    os.chmod(str(path.parent), 0o750)
    if path.exists():
        path.unlink()

    old_umask = os.umask(0o117)
    try:
        server = Server(str(path), Handler)
    finally:
        os.umask(old_umask)
    os.chown(str(path), 0, gid)
    os.chmod(str(path), 0o660)

    print(f"broker gateway {__version__} listening on {path}", file=sys.stderr, flush=True)
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        try:
            path.unlink()
        except FileNotFoundError:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
