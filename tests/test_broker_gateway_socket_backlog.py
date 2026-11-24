"""The gateway socket must absorb simultaneous scanner reconnects."""
from __future__ import annotations

from broker_gateway.daemon import Server


def test_gateway_listen_backlog_handles_scanner_fleet():
    # socketserver defaults to 5, which overflows when all scanners restart
    # together and makes clients fail with EAGAIN on connect().
    assert Server.request_queue_size >= 64
