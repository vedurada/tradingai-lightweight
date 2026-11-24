"""Tests for the opt-in mStock Type A order path. No real network or secrets."""
from __future__ import annotations

import io
import json
import urllib.error
import urllib.parse

import pytest

from broker_gateway import daemon
from broker_gateway.adapters.mstock import MStockAdapter
from broker_gateway.errors import BrokerCallFailed, BrokerGatewayError


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


@pytest.fixture
def adapter(monkeypatch, tmp_path):
    secret = tmp_path / "mstock.env"
    secret.write_text(
        "MSTOCK_API_KEY=test-key\nMSTOCK_ACCESS_TOKEN=test-token\n", encoding="utf-8"
    )
    monkeypatch.setenv("MSTOCK_SECRET_FILE", str(secret))
    monkeypatch.setenv("BROKER_GATEWAY_CACHE_DIR", str(tmp_path / "cache"))
    return MStockAdapter()


def test_order_methods_are_disabled_until_opt_in(monkeypatch, adapter):
    monkeypatch.setattr(daemon, "_ORDERS_ENABLED", False)
    request = {"broker": "mstock", "method": "place_order", "params": {}}
    with pytest.raises(BrokerGatewayError, match="disabled"):
        daemon.dispatch(request)
    monkeypatch.setattr(daemon, "_ORDERS_ENABLED", True)
    monkeypatch.setattr(daemon, "_adapter", lambda name: adapter)
    monkeypatch.setattr(daemon, "_require_fresh", lambda broker, adapter: None)
    # Opt-in reaches the adapter; invalid input is still refused there.
    bad = {
        **request,
        "params": {
            "variety": "reg", "exchange": "NFO", "tradingsymbol": "X",
            "transaction_type": "HOLD", "order_type": "LIMIT", "quantity": 75,
            "product": "MIS", "validity": "DAY", "price": 101, "tag": "t",
        },
    }
    with pytest.raises(BrokerCallFailed):
        daemon.dispatch(bad)


def test_place_order_posts_typea_form_once(adapter, monkeypatch):
    seen = {}

    def fake_urlopen(req, timeout=None):
        seen["url"] = req.full_url
        seen["data"] = urllib.parse.parse_qs(req.data.decode("utf-8"))
        seen["headers"] = req.headers
        seen.setdefault("calls", 0)
        seen["calls"] += 1
        return _Response(
            b'{"status":"success","data":{"order_id":"MOCK-ORDER-1"}}'
        )

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    result = adapter.place_order(
        variety="reg", exchange="NFO", tradingsymbol="NIFTY26NOV20000CE",
        transaction_type="BUY", order_type="LIMIT", quantity=75,
        product="MIS", validity="DAY", price=101.0, tag="S9L-BUY-ABC",
    )
    assert result == {"order_id": "MOCK-ORDER-1", "status": "ACCEPTED"}
    assert seen["calls"] == 1
    assert seen["url"] == "https://api.mstock.trade/openapi/typea/orders/reg"
    assert seen["data"]["tradingsymbol"] == ["NIFTY26NOV20000CE"]
    assert seen["data"]["quantity"] == ["75"]
    assert seen["data"]["tag"] == ["S9L-BUY-ABC"]
    assert "Content-type" in seen["headers"]


def test_place_order_accepts_market_with_zero_price(adapter, monkeypatch):
    seen = {}

    def fake_urlopen(req, timeout=None):
        seen["data"] = urllib.parse.parse_qs(req.data.decode("utf-8"))
        return _Response(
            b'{"status":"success","data":{"order_id":"MOCK-MARKET-1"}}'
        )

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    result = adapter.place_order(
        variety="reg", exchange="NFO", tradingsymbol="NIFTY26NOV20000CE",
        transaction_type="BUY", order_type="MARKET", quantity=65,
        product="MIS", validity="DAY", price=0, tag="S9L-BUY-MKT",
    )
    assert result["order_id"] == "MOCK-MARKET-1"
    assert seen["data"]["order_type"] == ["MARKET"]
    assert seen["data"]["price"] == ["0.0"]
    assert seen["data"]["quantity"] == ["65"]


def test_place_order_rejects_bad_fields_without_network(adapter, monkeypatch):
    def no_call(*args, **kwargs):
        raise AssertionError("network must not be called")

    monkeypatch.setattr(urllib.request, "urlopen", no_call)
    with pytest.raises(BrokerCallFailed):
        adapter.place_order(
            variety="amo", exchange="NFO", tradingsymbol="X",
            transaction_type="HOLD", order_type="LIMIT", quantity=75,
            product="MIS", validity="DAY", price=101, tag="t",
        )


def test_place_order_never_retries_on_timeout(adapter, monkeypatch):
    calls = []

    def timeout(*args, **kwargs):
        calls.append(1)
        raise TimeoutError("timed out")

    monkeypatch.setattr(urllib.request, "urlopen", timeout)
    with pytest.raises(BrokerCallFailed, match="may be pending"):
        adapter.place_order(
            variety="reg", exchange="NFO", tradingsymbol="X",
            transaction_type="BUY", order_type="LIMIT", quantity=75,
            product="MIS", validity="DAY", price=101, tag="t",
        )
    assert len(calls) == 1


def test_order_status_maps_broker_status(adapter, monkeypatch):
    rows = [{
        "order_id": "MOCK-ORDER-1", "status": "COMPLETE", "filled_quantity": 75,
        "quantity": 75, "status_message": "ok",
    }]
    monkeypatch.setattr(adapter, "_get_json", lambda path: {"status": "success", "data": rows})
    assert adapter.order_status(broker_order_id="MOCK-ORDER-1")["status"] == "FILLED"
    rows[0]["status"] = "Rejected"
    assert adapter.order_status(broker_order_id="MOCK-ORDER-1")["status"] == "REJECTED"
    assert adapter.order_status(broker_order_id="MISSING")["status"] == "UNKNOWN"


def test_order_status_exposes_average_fill_price(adapter, monkeypatch):
    rows = [{
        "order_id": "MOCK-ORDER-1", "status": "COMPLETE",
        "average_price": "101.25", "status_message": "filled",
    }]
    monkeypatch.setattr(adapter, "_get_json", lambda path: {"status": "success", "data": rows})
    result = adapter.order_status(broker_order_id="MOCK-ORDER-1")
    assert result["status"] == "FILLED"
    assert result["fill_price"] == 101.25
    assert result["raw_status"] == "COMPLETE"
    assert result["status_message"] == "filled"


def test_order_status_missing_order_has_no_fill_price(adapter, monkeypatch):
    monkeypatch.setattr(
        adapter, "_get_json", lambda path: {"status": "success", "data": []})
    assert adapter.order_status(broker_order_id="MISSING") == {
        "order_id": "MISSING", "status": "UNKNOWN", "fill_price": None,
    }


def test_fill_price_accepts_known_broker_field_names(adapter):
    for key in MStockAdapter._FILL_PRICE_KEYS:
        assert MStockAdapter._fill_price({key: "98.75"}) == 98.75
    assert MStockAdapter._fill_price({"average_price": "0"}) is None
    assert MStockAdapter._fill_price({"average_price": "bad"}) is None
