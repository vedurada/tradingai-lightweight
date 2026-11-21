#!/usr/bin/env python3
"""Root-owned Unix-socket gateway. Scanners call this; secrets never leave it."""
from __future__ import annotations

import grp
import json
import os
import pathlib
import socketserver
import sys
import threading
import traceback

from broker_gateway import __version__
from broker_gateway.adapters import available_brokers, get_adapter
from broker_gateway.errors import BrokerGatewayError

SOCKET_PATH = os.environ.get("BROKER_GATEWAY_SOCKET", "/run/tradingai/broker_gateway.sock")
SOCKET_GROUP = os.environ.get("BROKER_GATEWAY_GROUP", "ubuntu")
METHODS = {"instruments", "quote", "historical_data", "profile"}
_ADAPTERS: dict[str, object] = {}
_LOCK = threading.Lock()
_MAX_CALLS = max(1, int(os.environ.get("BROKER_GATEWAY_MAX_CALLS", "4")))
_CALL_LIMIT = threading.BoundedSemaphore(_MAX_CALLS)


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
    func = getattr(adapter, method)
    with _CALL_LIMIT:
        return func(**params)


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
