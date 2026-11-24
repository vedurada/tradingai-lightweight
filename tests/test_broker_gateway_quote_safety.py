"""Quote responses must never hand a nonpositive price to paper scanners.

Scanners do ``float(quote[symbol]["last_price"])`` inside a try/except and
treat a failed lookup as "LTP unavailable" (no entry, no exit). The gateway
therefore strips any invalid price so a bad broker tick cannot create a bogus
paper fill. This is broker-agnostic and needs no scanner change.
"""
from __future__ import annotations

import math

from broker_gateway.daemon import _sanitize_quote


def test_positive_prices_are_passthrough():
    entry = {"last_price": 150.5, "instrument_token": 123, "ohlc": {"close": 149.0}}
    result = _sanitize_quote({"NFO:X": entry})
    assert result["NFO:X"]["last_price"] == 150.5
    assert result["NFO:X"]["instrument_token"] == 123


def test_zero_and_negative_prices_are_stripped():
    result = _sanitize_quote({
        "A": {"last_price": 0.0, "instrument_token": 1},
        "B": {"last_price": -5.0, "instrument_token": 2},
        "C": {"last_price": 25.0, "instrument_token": 3},
    })
    assert "last_price" not in result["A"]
    assert "last_price" not in result["B"]
    assert result["C"]["last_price"] == 25.0
    # Other fields survive so callers can still identify the instrument.
    assert result["A"]["instrument_token"] == 1


def test_missing_none_and_non_numeric_prices_are_stripped():
    result = _sanitize_quote({
        "missing": {"instrument_token": 1},
        "none": {"last_price": None, "instrument_token": 2},
        "text": {"last_price": "abc", "instrument_token": 3},
    })
    for entry in result.values():
        assert "last_price" not in entry


def test_non_finite_prices_are_stripped():
    result = _sanitize_quote({
        "nan": {"last_price": float("nan")},
        "inf": {"last_price": float("inf")},
        "-inf": {"last_price": float("-inf")},
        "ok": {"last_price": 1.0},
    })
    assert all("last_price" not in result[k] for k in ("nan", "inf", "-inf"))
    assert result["ok"]["last_price"] == 1.0
    assert not math.isnan(result["ok"]["last_price"])


def test_numeric_strings_are_accepted():
    result = _sanitize_quote({"x": {"last_price": "123.45"}})
    # Preserve the original value; only validate it, do not mutate good data.
    assert result["x"]["last_price"] == "123.45"


def test_non_dict_payload_is_unchanged():
    assert _sanitize_quote(None) is None
    assert _sanitize_quote([1, 2, 3]) == [1, 2, 3]
