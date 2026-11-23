"""Quote-derived 5m bars when the broker has not published today's history.

The gateway stays read-only and broker-agnostic. Broker historical candles
always win; only missing today bars are derived from fresh quote samples, and
they are explicitly labelled so scanners can show the real provenance.
"""
from __future__ import annotations

import datetime as dt

import pytest

from broker_gateway.compat import kiteconnect as kmod
from broker_gateway.compat.kiteconnect import KiteConnect

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
TOKEN = 64479


@pytest.fixture
def fake_gateway(monkeypatch):
    state = {"quote": [], "history": [], "calls": []}

    def fake_call(_broker, method, **params):
        state["calls"].append((method, params))
        if method == "quote":
            return state["quote"]
        if method == "historical_data":
            return list(state["history"])
        return {}

    monkeypatch.setattr(kmod, "call", fake_call)
    return state


def _quote(price, token=TOKEN):
    return {"NFO:TEST": {"instrument_token": token,
                         "last_price": price}}


def _history(today=False):
    stamp = dt.datetime.now(IST).replace(hour=9, minute=15, second=0,
                                         microsecond=0)
    if not today:
        stamp = dt.datetime(2026, 11, 20, 15, 40, tzinfo=IST)
    return [{"date": stamp.isoformat(), "open": 100.0, "high": 101.0,
             "low": 99.0, "close": 100.5, "volume": 0}]


def test_quote_samples_become_labelled_5m_bars(fake_gateway):
    client = KiteConnect()
    fake_gateway["history"] = _history(today=False)
    fake_gateway["quote"] = _quote(100.0)

    client.quote("NFO:TEST")  # first sample
    fake_gateway["quote"] = _quote(102.0)
    client.quote("NFO:TEST")  # second sample, same 5m bucket

    bars = client.historical_data(
        TOKEN,
        dt.datetime.now(IST) - dt.timedelta(days=45),
        dt.datetime.now(IST),
        "5minute",
    )
    derived = [b for b in bars if b.get("source") == "quote_derived"]
    assert len(derived) == 1
    assert derived[0]["open"] == 100.0
    assert derived[0]["high"] == 102.0
    assert derived[0]["low"] == 100.0
    assert derived[0]["close"] == 102.0
    assert client.bar_source == "quote_derived"
    # Broker history is still present and sorted before today's derived bar.
    assert bars[0]["date"].startswith("2026-11-20")


def test_broker_history_wins_when_today_bar_exists(fake_gateway):
    client = KiteConnect()
    fake_gateway["quote"] = _quote(150.0)
    client.quote("NFO:TEST")
    now = dt.datetime.now(IST)
    bucket = now.replace(minute=(now.minute // 5) * 5, second=0,
                         microsecond=0)
    fake_gateway["history"] = [
        {"date": bucket.isoformat(), "open": 10, "high": 12,
         "low": 9, "close": 11, "volume": 1, "source": "broker_history"},
    ]

    bars = client.historical_data(TOKEN, now - dt.timedelta(days=7), now,
                                  "5minute")
    assert len(bars) == 1
    assert bars[0]["close"] == 11
    assert client.bar_source == "broker_history"


def test_no_samples_leaves_broker_history_untouched(fake_gateway):
    client = KiteConnect()
    fake_gateway["history"] = _history(today=False)
    now = dt.datetime.now(IST)
    bars = client.historical_data(TOKEN, now - dt.timedelta(days=7), now,
                                  "5minute")
    assert bars == fake_gateway["history"]
    assert client.bar_source == "broker_history"


def test_non_5minute_intervals_never_use_derived_bars(fake_gateway):
    client = KiteConnect()
    fake_gateway["quote"] = _quote(100.0)
    client.quote("NFO:TEST")
    fake_gateway["history"] = []
    now = dt.datetime.now(IST)
    bars = client.historical_data(TOKEN, now - dt.timedelta(days=7), now,
                                  "day")
    assert bars == []
    assert client.bar_source == "broker_history"
