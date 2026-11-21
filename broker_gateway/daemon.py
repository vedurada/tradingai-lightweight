#!/usr/bin/env python3
"""Root-owned Unix-socket gateway. Scanners call this; secrets never leave it."""
from __future__ import annotations

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
_FRESH_CACHE: dict[str, tuple[object, float, bool]] = {}
_FRESH_LOCK = threading.Lock()
_FRESH_LOCKS: dict[str, threading.Lock] = {}


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


def _require_fresh(broker: str, adapter) -> None:
    """Use only the latest, validated token for the selected broker."""
    signature = adapter.credential_signature()
    now = time.monotonic()
    with _FRESH_LOCK:
        cached = _FRESH_CACHE.get(broker)
    if cached and cached[0] == signature and cached[2] and now - cached[1] < _FRESH_TTL:
        return

    with _broker_lock(broker):
        now = time.monotonic()
        with _FRESH_LOCK:
            cached = _FRESH_CACHE.get(broker)
        if cached and cached[0] == signature and cached[2] and now - cached[1] < _FRESH_TTL:
            return
        try:
            adapter.validate_credentials()
        except Exception as exc:
            with _FRESH_LOCK:
                _FRESH_CACHE[broker] = (signature, now, False)
            raise BrokerCallFailed(
                f"{broker} token is stale or invalid; refresh it before trading: {exc}"
            ) from exc
        with _FRESH_LOCK:
            _FRESH_CACHE[broker] = (signature, now, True)


def _sanitize_quote(result):
    """Strip invalid/nonpositive ``last_price`` values from quote responses.

    Paper scanners do ``float(quote[symbol]["last_price"])``. A zero, negative
    or non-finite price would otherwise be accepted and could produce bogus
    paper entries or stop-loss exits. Removing the key makes that lookup raise
    ``KeyError``, which every scanner already handles as "LTP unavailable" and
    skips the option for that poll. Applies to every broker at the daemon
    boundary, so scanner code stays unchanged when switching brokers.
    """
    if not isinstance(result, dict):
        return result
    clean = {}
    for symbol, entry in result.items():
        if not isinstance(entry, dict):
            clean[symbol] = entry
            continue
        raw = entry.get("last_price")
        try:
            price = float(raw)
            valid = math.isfinite(price) and price > 0
        except (TypeError, ValueError):
            valid = False
        if valid:
            clean[symbol] = entry
        else:
            stripped = dict(entry)
            stripped.pop("last_price", None)
            clean[symbol] = stripped
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
