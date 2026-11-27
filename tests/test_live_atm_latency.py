"""Regression tests for live-ATM dashboard latency and freshness.

The dashboard must never wait on a slow broker quote when a previously verified
snapshot exists, and all scanners must share one short-lived broker snapshot.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

from flask import Flask

from app.api import live_atm_api as m

INDEX = "NSE:NIFTY 50"
EXPIRY = "2026-12-01"
QUOTES = {
    INDEX: {"last_price": 25349.65, "ohlc": {"close": 25349.65}},
    "47804": {"instrument_token": 47804, "last_price": 263.55},
    "47805": {"instrument_token": 47805, "last_price": 242.9},
}
INSTRUMENTS = [
    {
        "instrument_token": 47804,
        "tradingsymbol": "NIFTY26D0125350CE",
        "instrument_type": "CE",
        "strike": 25350.0,
        "expiry": EXPIRY,
    },
    {
        "instrument_token": 47805,
        "tradingsymbol": "NIFTY26D0125350PE",
        "instrument_type": "PE",
        "strike": 25350.0,
        "expiry": EXPIRY,
    },
]


def _patch(monkeypatch):
    calls = []

    def fake_call(broker, method, **params):
        calls.append((method, params))
        if method == "instruments":
            return INSTRUMENTS
        if method == "quote":
            return QUOTES
        raise AssertionError("unexpected gateway method: " + method)

    monkeypatch.setattr(m, "SCANNER_STATES", {})
    monkeypatch.setattr(m, "broker_for", lambda _: "mstock")
    monkeypatch.setattr(m, "call", fake_call)
    for name, value in (
        ("_cache", {}),
        ("_last_good", {}),
        ("_master_index_cache", {}),
        ("_quote_cache", {}),
        ("_refresh_inflight", set()),
        ("_refresh_attempted", {}),
    ):
        monkeypatch.setattr(m, name, value)
    return calls


def _client():
    app = Flask(__name__)
    app.register_blueprint(m.bp)
    return app.test_client()


def test_index_and_option_quotes_are_shared_between_scanners(monkeypatch):
    calls = _patch(monkeypatch)

    m._fresh_value("sma9", EXPIRY)
    m._fresh_value("sma9-high", EXPIRY)

    quote_calls = [p for method, p in calls if method == "quote"]
    index_calls = [p for p in quote_calls if p["symbols"] == [INDEX]]
    option_calls = [p for p in quote_calls if p["symbols"] != [INDEX]]
    assert len(index_calls) == 1
    assert len(option_calls) == 1
    assert len([p for method, p in calls if method == "instruments"]) == 1


def test_dashboard_reads_use_short_gateway_timeouts(monkeypatch):
    calls = _patch(monkeypatch)

    m._fresh_value("", EXPIRY)

    for method, params in calls:
        expected = (
            m.MASTER_TIMEOUT_SECONDS if method == "instruments"
            else m.QUOTE_TIMEOUT_SECONDS
        )
        assert params["timeout"] == expected


def test_failed_quote_refresh_reuses_last_snapshot(monkeypatch):
    _patch(monkeypatch)
    m._broker_quotes("mstock", [INDEX])
    key = ("mstock", (INDEX,))
    m._quote_cache[key]["at"] -= m.QUOTE_CACHE_SECONDS + 1

    def failing_call(broker, method, **params):
        raise RuntimeError("broker timeout")

    monkeypatch.setattr(m, "call", failing_call)

    assert m._broker_quotes("mstock", [INDEX]) == QUOTES


def test_expired_snapshot_is_served_immediately_and_refreshed_in_background(
    monkeypatch,
):
    _patch(monkeypatch)
    fresh = m._fresh_value("sma9", EXPIRY)
    key = ("sma9", EXPIRY)
    m._cache[key]["at"] -= m.CACHE_SECONDS + 1

    def no_sync_refresh(*args, **kwargs):
        raise AssertionError("refresh must not run on the request path")

    monkeypatch.setattr(m, "_fresh_value", no_sync_refresh)
    targets = []

    class FakeThread:
        def __init__(self, *, target, name, daemon):
            targets.append(target)

        def start(self):
            pass

    monkeypatch.setattr(m.threading, "Thread", FakeThread)

    response = _client().get("/api/live-atm?scanner=sma9&expiry=" + EXPIRY)

    assert response.status_code == 200
    data = response.json["data"]
    assert data["stale"] is True
    assert data["source"] == "cached_quote"
    assert data["premiums"]["CE"]["ltp"] == fresh["premiums"]["CE"]["ltp"]
    assert len(targets) == 1

    # A second request while the refresh is in flight must not spawn another.
    second = _client().get("/api/live-atm?scanner=sma9&expiry=" + EXPIRY)
    assert second.json["data"]["stale"] is True
    assert len(targets) == 1


def test_background_refresh_replaces_expired_snapshot(monkeypatch):
    _patch(monkeypatch)
    m._fresh_value("sma9", EXPIRY)
    key = ("sma9", EXPIRY)
    m._cache[key]["at"] -= m.CACHE_SECONDS + 1
    old_at = m._cache[key]["at"]
    captured = {}

    class FakeThread:
        def __init__(self, *, target, name, daemon):
            captured["target"] = target

        def start(self):
            pass

    monkeypatch.setattr(m.threading, "Thread", FakeThread)
    _client().get("/api/live-atm?scanner=sma9&expiry=" + EXPIRY)

    assert key in m._refresh_inflight
    captured["target"]()

    assert m._cache[key]["at"] > old_at
    assert m._cache[key]["value"]["stale"] is False
    assert key not in m._refresh_inflight


def test_gateway_timeout_is_client_side_only(monkeypatch):
    from broker_gateway import client as gw

    sock = MagicMock()
    sock.__enter__.return_value = sock
    sock.recv.return_value = b'{"ok": true, "result": {"last_price": 1}}\n'
    monkeypatch.setattr(gw.socket, "socket", lambda *args, **kwargs: sock)

    result = gw.call("mstock", "quote", timeout=4.0, symbols=[INDEX])

    assert result == {"last_price": 1}
    sock.settimeout.assert_called_once_with(4.0)
    sent = json.loads(sock.sendall.call_args.args[0])
    assert sent["params"] == {"symbols": [INDEX]}
