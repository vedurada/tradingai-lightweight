"""C7: quote freshness is enforced centrally at the gateway boundary."""
from __future__ import annotations

import datetime as dt

import pytest

from broker_gateway import daemon
from broker_gateway.daemon import _quote_age_seconds, _sanitize_quote

NOW = dt.datetime(2026, 11, 23, 8, 0, tzinfo=dt.timezone.utc)  # 13:30 IST, weekday


@pytest.fixture(autouse=True)
def _live_market(monkeypatch):
    monkeypatch.setattr(daemon, "_live_market", lambda now: True)


def test_quote_without_timestamp_is_fresh_and_normalized():
    result = _sanitize_quote({"mstock": {"last_price": 100.0}}, now=NOW)
    q = result["mstock"]
    assert q["last_price"] == 100.0
    assert q["age_seconds"] == 0.0
    assert q["last_trade_time"] is None


def test_recent_trade_time_keeps_price():
    stamp = NOW - dt.timedelta(seconds=30)
    result = _sanitize_quote({"zerodha": {"last_price": 100.0, "last_trade_time": stamp}}, now=NOW)
    q = result["zerodha"]
    assert q["last_price"] == 100.0
    assert 25 <= q["age_seconds"] <= 35


def test_stale_trade_time_drops_price_during_market_hours():
    stamp = NOW - dt.timedelta(seconds=900)
    result = _sanitize_quote({"zerodha": {"last_price": 100.0, "last_trade_time": stamp}}, now=NOW)
    q = result["zerodha"]
    assert "last_price" not in q
    assert q["age_seconds"] >= 890
    assert q["instrument_token"] if "instrument_token" in q else True


def test_stale_quote_keeps_price_outside_market_hours(monkeypatch):
    monkeypatch.setattr(daemon, "_live_market", lambda now: False)
    stamp = NOW - dt.timedelta(seconds=900)
    result = _sanitize_quote({"zerodha": {"last_price": 100.0, "last_trade_time": stamp}}, now=NOW)
    assert result["zerodha"]["last_price"] == 100.0


def test_iso_string_and_epoch_timestamps_are_understood():
    iso = (NOW - dt.timedelta(seconds=60)).isoformat()
    assert 50 <= _quote_age_seconds({"last_trade_time": iso}, NOW) <= 70
    epoch = (NOW - dt.timedelta(seconds=60)).timestamp()
    assert 50 <= _quote_age_seconds({"last_trade_time": epoch}, NOW) <= 70


def test_unparseable_timestamp_is_treated_as_fresh():
    assert _quote_age_seconds({"last_trade_time": "not-a-date"}, NOW) == 0.0
