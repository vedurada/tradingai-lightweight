"""Unix-socket client used by the Kite-compatible shim."""
from __future__ import annotations

import json
import os
import socket

from broker_gateway.config import scanner_name
from broker_gateway.errors import BrokerGatewayError

SOCKET_PATH = os.environ.get("BROKER_GATEWAY_SOCKET", "/run/tradingai/broker_gateway.sock")
TIMEOUT = float(os.environ.get("BROKER_GATEWAY_TIMEOUT", "180"))


def call(broker: str, method: str, *, timeout: float | None = None, **params):
    """Call the gateway once. ``timeout`` is a client-side deadline only; it is
    never forwarded as a broker method parameter.

    Read-only dashboards pass a short timeout so a slow broker cannot pin a
    gunicorn thread until the 180-second default expires. Order and scanner
    calls keep the default unless they explicitly opt in.
    """
    # The alias identifies the calling scanner to the daemon so order methods
    # can be scoped to one alias instead of every process sharing the socket.
    request = json.dumps({
        "broker": broker,
        "method": method,
        "params": params,
        "scanner": scanner_name(),
    }) + "\n"
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(TIMEOUT if timeout is None else timeout)
            sock.connect(SOCKET_PATH)
            sock.sendall(request.encode("utf-8"))
            buffer = b""
            while b"\n" not in buffer:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                buffer += chunk
    except OSError as exc:
        raise BrokerGatewayError(
            f"cannot reach broker gateway at {SOCKET_PATH}: {exc}"
        ) from exc

    line = buffer.split(b"\n", 1)[0]
    if not line:
        raise BrokerGatewayError("empty response from broker gateway")
    try:
        response = json.loads(line.decode("utf-8"))
    except ValueError as exc:
        raise BrokerGatewayError("invalid response from broker gateway") from exc
    if not response.get("ok"):
        raise BrokerGatewayError(str(response.get("error") or "gateway error"))
    return response.get("result")
