"""Regression tests for live ATM CE/PE contract selection.

mStock's weekly NIFTY symbols cannot be derived from an ISO expiry alone:
2026-12-01 is NIFTY26D01..., while NIFTY26DEC... expires on 2026-12-29.
The display API must quote the token held in the requesting scanner's
heartbeat, or resolve it from the instrument master when no scanner is named.
"""
from __future__ import annotations

import json
import sqlite3

from app.api import live_atm_api as m


QUOTES = {
    "NSE:NIFTY 50": {"last_price": 25349.65, "ohlc": {"close": 25349.65}},
    "47804": {"instrument_token": 47804, "last_price": 263.55},
    "47805": {"instrument_token": 47805, "last_price": 242.9},
    "63989": {"instrument_token": 47804, "last_price": 263.55},
    "NFO:NIFTY26DEC25350CE": {"instrument_token": 63989, "last_price": 544.85},
    "NFO:NIFTY26DEC25350PE": {"instrument_token": 63990, "last_price": 406.5},
}

INSTRUMENTS = [
    {
        "instrument_token": 47804,
        "tradingsymbol": "NIFTY26D0125350CE",
        "instrument_type": "CE",
        "strike": 25350.0,
        "expiry": "2026-12-01",
    },
    {
        "instrument_token": 47805,
        "tradingsymbol": "NIFTY26D0125350PE",
        "instrument_type": "PE",
        "strike": 25350.0,
        "expiry": "2026-12-01",
    },
    {
        "instrument_token": 63989,
        "tradingsymbol": "NIFTY26DEC25350CE",
        "instrument_type": "CE",
        "strike": 25350.0,
        "expiry": "2026-12-29",
    },
    {
        "instrument_token": 70188,
        "tradingsymbol": "FINNIFTY26DEC25350CE",
        "instrument_type": "CE",
        "strike": 25350.0,
        "expiry": "2026-12-01",
    },
]


def _write_heartbeat(tmp_path, *, expiry="2026-12-01", ce_token=47804):
    db = tmp_path / "sma9.db"
    conn = sqlite3.connect(str(db))
    conn.execute(
        "CREATE TABLE sma9_scan_state "
        "(key TEXT PRIMARY KEY, value TEXT, updated_at TEXT)"
    )
    state = {
        "expiry": expiry,
        "options": {
            "CE": {
                "token": ce_token,
                "tradingsymbol": "NIFTY26D0125350CE",
                "strike": 25350.0,
                "expiry": expiry,
            },
            "PE": {
                "token": 47805,
                "tradingsymbol": "NIFTY26D0125350PE",
                "strike": 25350.0,
                "expiry": expiry,
            },
        },
    }
    conn.execute(
        "INSERT INTO sma9_scan_state VALUES (?, ?, ?)",
        ("live_status", json.dumps(state), "2026-11-24T18:46:15+05:30"),
    )
    conn.commit()
    conn.close()
    return db


def _patch(monkeypatch, db=None, *, master_rows=True):
    monkeypatch.setattr(
        m, "SCANNER_STATES", {"sma9": (str(db), "sma9_scan_state")} if db else {}
    )
    monkeypatch.setattr(m, "broker_for", lambda _: "mstock")

    def fake_call(broker, method, **params):
        if method == "instruments":
            return INSTRUMENTS if master_rows else []
        return QUOTES

    monkeypatch.setattr(m, "call", fake_call)
    monkeypatch.setattr(m, "_cache", {})
    monkeypatch.setattr(m, "_last_good", {})
    monkeypatch.setattr(m, "_master_contract_cache", {})


def test_heartbeat_token_wins_over_derived_month_symbol(tmp_path, monkeypatch):
    _patch(monkeypatch, _write_heartbeat(tmp_path))

    value = m._fresh_value("sma9", "2026-12-01")

    assert value["contract_source"] == "scanner_heartbeat_token"
    ce = value["premiums"]["CE"]
    pe = value["premiums"]["PE"]
    assert ce["symbol"] == "NFO:NIFTY26D0125350CE"
    assert ce["instrument_token"] == 47804
    assert ce["token_verified"] is True
    assert ce["ltp"] == 263.55
    assert pe["symbol"] == "NFO:NIFTY26D0125350PE"
    assert pe["ltp"] == 242.9


def test_wrong_token_is_not_displayed_as_a_quote(tmp_path, monkeypatch):
    _patch(monkeypatch, _write_heartbeat(tmp_path, ce_token=63989))

    value = m._fresh_value("sma9", "2026-12-01")
    ce = value["premiums"]["CE"]

    assert ce["error"] == "instrument token mismatch"
    assert ce["expected_token"] == 63989
    assert ce["actual_token"] == 47804
    assert "ltp" not in ce


def test_no_scanner_resolves_contract_from_instrument_master(monkeypatch):
    _patch(monkeypatch)

    value = m._fresh_value("", "2026-12-01")

    assert value["contract_source"] == "instrument_master"
    ce = value["premiums"]["CE"]
    pe = value["premiums"]["PE"]
    assert ce["symbol"] == "NFO:NIFTY26D0125350CE"
    assert ce["instrument_token"] == 47804
    assert ce["token_verified"] is True
    assert ce["ltp"] == 263.55
    assert pe["symbol"] == "NFO:NIFTY26D0125350PE"
    assert pe["ltp"] == 242.9


def test_legacy_derivation_is_only_a_labelled_last_resort(monkeypatch):
    _patch(monkeypatch, master_rows=False)

    value = m._fresh_value("", "2026-12-01")

    assert value["contract_source"] == "derived_symbol"
    assert value["premiums"]["CE"]["symbol"] == "NFO:NIFTY26DEC25350CE"
    assert value["premiums"]["CE"]["ltp"] == 544.85
